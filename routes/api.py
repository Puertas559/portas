from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from email.message import EmailMessage
from email.policy import SMTP
from uuid import uuid4
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy import text
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import (
    AuditLog, CollectorRun, Company, CompanyActivity, Contact, Evidence, Opportunity, OpportunityEvidence, OpportunityScore, Project, Proposal,
    ProspectSignal, SalesTask, ScoreFactor, Signal, Source, SourceDocument, TimelineEvent, VisitRecord, Watchlist, WebsiteAnalysis,
)
from ..services.entity_resolution import resolve_company, resolve_project
from ..services.intelligence import as_datetime, company_completeness, lead_readiness, link_evidence_and_products, record_evidence, score_opportunity
from ..tenant import current_tenant, current_user, require_permission

api_bp = Blueprint("api", __name__, url_prefix="/api")
STATUSES = {"NOVO", "QUALIFICADO", "CONTATO_REALIZADO", "RESPONDEU", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO", "PERDIDO", "MONITORAMENTO", "DESCARTADO"}
BUYING_STAGES = {"AWARENESS", "RESEARCH", "PROJECT_PLANNING", "SUPPLIER_DISCOVERY", "RFQ", "PROCUREMENT", "NEGOTIATION", "PURCHASE", "POSTPONED", "UNKNOWN"}


def _audit(action, entity_type, entity_id, details=None):
    tenant = current_tenant()
    user = current_user()
    db.session.add(AuditLog(
        tenant_id=tenant.id, user_id=user.id if user else None, action=action,
        entity_type=entity_type, entity_id=str(entity_id), details=details or {},
    ))


def _optional_number(value):
    if value in (None, ""):
        return None
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        raise ValueError("Valor numérico inválido")


def _department_context(contact=None, email=None):
    blob = " ".join(filter(None, [getattr(contact, "role", None), getattr(contact, "buying_role", None), email])).lower()
    if any(k in blob for k in ("marketing", "mercadeo", "comunicacion", "comunicación")):
        return "MARKETING"
    if any(k in blob for k in ("compra", "buyer", "procurement", "abastecimiento")):
        return "COMPRAS"
    if any(k in blob for k in ("mantenimiento", "ingenier", "infraestructura", "proyecto", "técnic", "tecnic")):
        return "TECNICO"
    if any(k in blob for k in ("logistica", "logística", "operacion", "operación", "deposito", "depósito")):
        return "OPERACIONES"
    if any(k in blob for k in ("direccion", "dirección", "gerencia", "director", "gerente", "ceo")):
        return "DIRECCION"
    return "GENERAL"


def _company_message(company, contact=None, channel="EMAIL", opportunity=None):
    company_name = company.name
    contact_name = contact.name.strip() if contact and contact.name else ""
    email = (contact.email if contact else None) or company.email_business or company.email or ""
    dept = _department_context(contact, email)
    greeting = f"Estimado/a {contact_name}," if contact_name else f"Estimado equipo de {company_name},"
    sector = company.sector or "su operación"
    products = (opportunity.products if opportunity else []) or []
    product_phrase = ", ".join(products[:3]) if products else "soluciones de accesos automáticos e industriales"
    intro = (
        "Mi nombre es David Granja y represento a Puertas Brasil, empresa especializada en soluciones de accesos automáticos e industriales, "
        "con fábrica ubicada en el km 13 de Ciudad del Este."
    )
    context_map = {
        "MARKETING": "Entiendo que este contacto corresponde al área de Marketing o Comunicación. Mi intención es presentar brevemente nuestra empresa y solicitar su orientación para llegar al responsable técnico adecuado.",
        "COMPRAS": "Nos gustaría quedar registrados como proveedor y conocer el canal correcto para futuras cotizaciones, homologaciones o procesos de compra relacionados con accesos industriales.",
        "TECNICO": f"Por el perfil de su operación, vemos posibles aplicaciones para {product_phrase}, además de instalación, mantenimiento preventivo, correctivo y modernización de equipos existentes.",
        "OPERACIONES": f"En operaciones como la de {company_name}, los accesos pueden influir directamente en el flujo de mercaderías, la seguridad, los tiempos de carga y descarga y la continuidad operacional.",
        "DIRECCION": "Nos gustaría presentar nuestra capacidad industrial y evaluar si existe encaje para proyectos actuales o futuros de infraestructura, expansión, logística o mantenimiento.",
        "GENERAL": f"En empresas del segmento {sector}, los accesos pueden influir en la seguridad, el flujo de personas y mercaderías y la continuidad de la operación.",
    }
    ask_map = {
        "MARKETING": "¿Podría indicarme el nombre y el correo directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos?",
        "COMPRAS": "¿Podría indicarme quién gestiona Compras o Abastecimiento y quién valida técnicamente este tipo de solución en Mantenimiento, Ingeniería, Infraestructura, Operaciones o Proyectos?",
        "TECNICO": "¿Sería posible coordinar una conversación breve para conocer la operación actual, prioridades y eventuales proyectos en los que podamos aportar?",
        "OPERACIONES": "¿Podría indicarme quién es el responsable de Operaciones, Logística, Mantenimiento, Infraestructura o Proyectos para conversar brevemente sobre estas necesidades?",
        "DIRECCION": "¿Con quién de Mantenimiento, Ingeniería, Infraestructura, Operaciones, Logística o Proyectos sería conveniente continuar esta conversación?",
        "GENERAL": "¿Podrían indicarme el nombre y el correo directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos?",
    }
    body = f"{greeting}\n\nEs un gusto saludarle.\n\n{intro}\n\nNos gustaría presentar nuestra empresa y ponernos a disposición de {company_name}.\n\n{context_map[dept]}\n\nAdjunto nuestra carta de presentación institucional y catálogo comercial.\n\n{ask_map[dept]}\n\nDesde ya, agradezco mucho su orientación.\n\nSaludos cordiales,\nDavid Granja\nPuertas Brasil"
    subject = "Puertas Brasil Paraguay | Primer Contacto"
    if channel.upper() == "WHATSAPP":
        body = f"Hola{(' ' + contact_name) if contact_name else ''}, ¿cómo está? Soy David Granja, de Puertas Brasil. {context_map[dept]} {ask_map[dept]} Muchas gracias."
    elif channel.upper() == "CALL":
        body = f"Objetivo de la llamada: presentarse como David Granja de Puertas Brasil; contextualizar {company_name}; {ask_map[dept]} Registrar nombre, cargo, contacto directo, necesidad, plazo y próximo paso."
    return {"subject": subject, "body": body, "department": dept, "recipient": contact_name or company_name, "recipientEmail": email}



def _website_domain(value):
    raw=(value or "").strip()
    if not raw:
        return None
    try:
        parsed=urlparse(raw if "://" in raw else "https://"+raw)
        return (parsed.hostname or "").lower().removeprefix("www.") or None
    except Exception:
        return None


def _analysis_enrichment(analysis):
    data=dict((analysis.diagnostics or {}).get("enrichment") or {})
    data.setdefault("legalName", None)
    data.setdefault("ruc", None)
    data.setdefault("foundedYear", None)
    data.setdefault("owners", [])
    data.setdefault("operationPlants", [])
    data.setdefault("keyActivities", [])
    data.setdefault("city", None)
    data.setdefault("department", None)
    data.setdefault("address", analysis.address)
    data.setdefault("officialWebsite", analysis.url)
    data.setdefault("domain", _website_domain(analysis.url))
    data.setdefault("socialLinks", analysis.social_links or {})
    data.setdefault("products", analysis.products or [])
    data.setdefault("fieldConfidence", {})
    data.setdefault("reviewRequired", [])
    return data


def _merge_company_enrichment(company, analysis, *, overwrite=False, source_label="Análisis automático del sitio"):
    enrichment=_analysis_enrichment(analysis)
    confidence=enrichment.get("fieldConfidence") or {}
    updated=[]; preserved=[]; review=set(enrichment.get("reviewRequired") or [])

    def assign(attr, value, key, min_conf=0):
        if value in (None, "", [], {}):
            return
        current=getattr(company, attr)
        field_conf=int(confidence.get(key) or 0)
        if field_conf and field_conf < min_conf:
            review.add(key); return
        if overwrite or current in (None, "", [], {}):
            setattr(company, attr, value); updated.append(key)
        else:
            preserved.append(key)

    assign("legal_name", enrichment.get("legalName"), "legalName", 70)
    assign("ruc", enrichment.get("ruc"), "ruc", 78)
    assign("founded_year", enrichment.get("foundedYear"), "foundedYear", 70)
    owners=[]
    for item in enrichment.get("owners") or []:
        if isinstance(item, dict):
            if int(item.get("confidence") or 0) >= 80:
                owners.append(item.get("name"))
            else:
                review.add("owners")
        elif item:
            owners.append(str(item))
    assign("owners", [x for x in owners if x], "owners", 0)
    assign("operation_plants", enrichment.get("operationPlants") or [], "operationPlants", 0)
    assign("key_activities", enrichment.get("keyActivities") or [], "keyActivities", 0)
    assign("city", enrichment.get("city"), "city", 0)
    assign("department", enrichment.get("department"), "department", 0)
    assign("address", enrichment.get("address") or analysis.address, "address", 70)
    assign("company_size", analysis.company_size if analysis.company_size != "No determinado" else None, "companySize", 0)
    assign("sector", analysis.sector if analysis.sector != "Por validar" else None, "sector", 0)
    assign("description", analysis.summary, "description", 0)
    assign("website", enrichment.get("officialWebsite") or analysis.url, "website", 0)
    assign("domain", enrichment.get("domain") or _website_domain(analysis.url), "domain", 0)
    if analysis.emails:
        assign("email_business", analysis.emails[0], "email", 0)
    if analysis.phones:
        assign("phone_business", analysis.phones[0], "phone", 0)
    if analysis.whatsapp:
        assign("whatsapp", analysis.whatsapp, "whatsapp", 0)
    social=dict(enrichment.get("socialLinks") or analysis.social_links or {})
    if social.get("linkedin"):
        assign("linkedin_url", social.get("linkedin"), "linkedin", 0)

    presence=dict(company.digital_presence or {})
    presence["officialWebsite"] = company.website or analysis.url
    presence["alternativeSites"] = analysis.alternative_sites or presence.get("alternativeSites") or []
    presence["socialLinks"] = {**(presence.get("socialLinks") or {}), **social}
    presence["lastVerifiedAt"] = datetime.now(timezone.utc).isoformat()
    presence["autoEnrichment"] = {
        "sourceUrl": analysis.url,
        "source": source_label,
        "lastRunAt": datetime.now(timezone.utc).isoformat(),
        "updatedFields": updated,
        "preservedManualFields": preserved,
        "reviewRequired": sorted(review),
        "fieldConfidence": confidence,
        "pagesAnalyzed": analysis.pages_analyzed,
    }
    company.digital_presence=presence
    sources=list(company.data_sources or [])
    source_record={"type":"COMPANY_WEBSITE","url":analysis.url,"label":source_label,"verifiedAt":datetime.now(timezone.utc).isoformat()}
    if not any(isinstance(x,dict) and x.get("url")==analysis.url for x in sources):
        sources.append(source_record)
    company.data_sources=sources[-30:]
    company.last_enriched_at=datetime.now(timezone.utc)
    company.research_status="REVIEW" if review else "ENRICHED"
    company.identity_confidence=max(company.identity_confidence or 0, min(95, 50 + analysis.pages_analyzed * 3))
    company.data_completeness_score=company_completeness(company)[0]
    return {"updated":updated,"preserved":preserved,"reviewRequired":sorted(review),"completeness":company.data_completeness_score}


def _match_company_for_analysis(tenant_id, analysis):
    domain=_website_domain(analysis.url)
    if domain:
        row=Company.query.filter_by(tenant_id=tenant_id, status="ACTIVE", domain=domain).first()
        if row:
            return row
        row=Company.query.filter(Company.tenant_id==tenant_id, Company.status=="ACTIVE", Company.website.ilike(f"%{domain}%")).first()
        if row:
            return row
    return None


def _auto_sync_existing_company(analysis):
    tenant=current_tenant()
    company=_match_company_for_analysis(tenant.id, analysis)
    if not company:
        return None
    result=_merge_company_enrichment(company, analysis)
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=company.id, activity_type="DATA_UPDATE", channel="SITIO_WEB", subject="Enriquecimiento automático", summary=f"El sitio fue revisado automáticamente. {len(result['updated'])} campos fueron completados y {len(result['reviewRequired'])} requieren revisión.", extra_data=result))
    db.session.commit()
    return {"companyId":company.id, **result}

def _create_cadence(opportunity):
    if opportunity.tasks:
        return
    now = datetime.now(timezone.utc)
    steps = [
        (0, "WHATSAPP", "Enviar primer contacto personalizado por WhatsApp"),
        (1, "CALL", "Llamar e identificar al responsable técnico y validar la etapa del proyecto"),
        (3, "EMAIL", "Enviar presentación ejecutiva con solución vinculada al contexto de la empresa"),
        (7, "FOLLOW_UP", "Hacer seguimiento con una pregunta de avance o cronograma"),
        (14, "VISIT", "Proponer visita técnica o reunión de diagnóstico"),
    ]
    for step, (days, channel, title) in enumerate(steps, 1):
        db.session.add(SalesTask(opportunity=opportunity, title=title, channel=channel, due_at=now + timedelta(days=days), sequence_step=step))


def _create_intelligence_opportunity(data, status="NOVO"):
    tenant = current_tenant()
    company = resolve_company(
        tenant.id, data.get("company"), sector=data.get("sector"), origin_country=data.get("origin"),
        website=data.get("website"), address=data.get("address"),
        city=data.get("city"), department=data.get("department") or data.get("region"), country=data.get("country") or "Paraguay",
        phone=data.get("phone"), phone_business=data.get("phone"), whatsapp=data.get("whatsapp") or data.get("phone"),
        email=data.get("email"), email_business=data.get("email"), linkedin_url=data.get("linkedin"),
        registration_id=data.get("registrationId"), description=data.get("companyDescription"),
    )
    db.session.flush()
    project = resolve_project(
        tenant.id, company, data.get("project") or data.get("sourceTitle") or "Proyecto por validar",
        city=data.get("city") or "Por validar", department=data.get("department") or data.get("region") or "Por validar",
        country=data.get("country") or "Paraguay", project_type=data.get("projectType") or data.get("event") or "UNKNOWN",
        stage=data.get("stage"), investment=data.get("investment"), investment_amount=_optional_number(data.get("investmentAmount")),
        investment_currency=(data.get("investmentCurrency") or "USD")[:3].upper(), area_m2=_optional_number(data.get("areaM2")),
        description=data.get("projectDescription"), announced_at=as_datetime(data.get("announcedAt")), started_at=as_datetime(data.get("startedAt")),
    )
    db.session.flush()
    signal, evidence = record_evidence(tenant, company, project, data)
    linked = OpportunityEvidence.query.join(Opportunity).filter(
        OpportunityEvidence.evidence_id == evidence.id,
        Opportunity.tenant_id == tenant.id,
        ~Opportunity.status.in_({"PERDIDO", "DESCARTADO"}),
    ).first()
    if linked:
        return linked.opportunity, False
    buying_stage = (data.get("buyingStage") or "UNKNOWN").upper()
    if buying_stage not in BUYING_STAGES:
        buying_stage = "UNKNOWN"
    try:
        probability = max(0, min(100, int(data.get("probability", 20))))
        potential_value = max(0, float(data.get("potentialDealValue", data.get("estimatedValue", 0))))
    except (TypeError, ValueError):
        probability, potential_value = 20, 0
    opportunity = Opportunity(
        tenant_id=tenant.id, project=project, event_type=signal.signal_type, score=0, level="MEDIUM", status=status,
        products=data.get("products") or [], evidence=evidence.claim, source_name=signal.source_document.source.name,
        source_url=signal.source_document.canonical_url, probability=probability,
        estimated_value=potential_value, potential_deal_value=potential_value, buying_stage=buying_stage,
    )
    db.session.add(opportunity)
    db.session.flush()
    score_opportunity(tenant, opportunity, data)
    link_evidence_and_products(tenant, opportunity, evidence, opportunity.products, data.get("productFit", 70))
    _create_cadence(opportunity)
    db.session.add(TimelineEvent(
        opportunity=opportunity, event_type="INTELLIGENCE_CREATED",
        description=f"Oportunidad creada desde señal {signal.signal_type} con evidencia trazable y scoring {opportunity.score_version}",
    ))
    _audit("CREATE", "OPPORTUNITY", opportunity.id, {"signal_id": signal.id, "project_id": project.id, "score": opportunity.score})
    return opportunity, True


@api_bp.get("/opportunities")
def opportunities_list():
    tenant = current_tenant()
    rows = Opportunity.query.filter_by(tenant_id=tenant.id).order_by(Opportunity.score.desc()).limit(500).all()
    return jsonify([row.to_dict() for row in rows])


@api_bp.get("/company-search")
def company_search():
    try:
        from ..services.company_search import search_companies
        rows = search_companies(
            query=request.args.get("q", ""), city=request.args.get("city", ""),
            region=request.args.get("region", ""), industry=request.args.get("industry", ""),
        )
        return jsonify(results=rows, count=len(rows))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        return jsonify(error="No se pudo consultar el buscador público. Intente nuevamente."), 502


@api_bp.post("/company-search/add")
@require_permission("WRITE_CRM")
def company_search_add():
    data = request.get_json(silent=True) or {}
    if not data.get("company"):
        return jsonify(error="Falta el nombre de la empresa"), 400
    payload = dict(data)
    payload.update({
        "project": data.get("project") or "Empresa identificada por búsqueda geográfica",
        "event": "COMPANY_DISCOVERY", "department": data.get("region") or "Por validar",
        "stage": "Prospección geográfica", "sourceName": data.get("source") or "Buscador empresarial",
        "sourceUrl": data.get("website"),
        "evidence": f"Empresa identificada por fuente pública en {data.get('city') or 'Paraguay'}.",
        "dataConfidence": data.get("score", 55), "intent": 35, "icpFit": data.get("score", 55),
        "evidenceClassification": "FACT",
    })
    try:
        opportunity, created = _create_intelligence_opportunity(payload)
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    db.session.commit()
    return jsonify(opportunity.to_dict()), 201 if created else 200


@api_bp.post("/opportunities")
@require_permission("WRITE_CRM")
def opportunities_create():
    data = request.get_json(silent=True) or {}
    required = ("company", "project", "city", "department", "event", "evidence")
    missing = [key for key in required if not data.get(key)]
    if missing:
        return jsonify(error="Faltan campos obligatorios", fields=missing), 400
    try:
        opportunity, created = _create_intelligence_opportunity(data)
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    db.session.commit()
    return jsonify(opportunity.to_dict()), 201 if created else 200


@api_bp.patch("/opportunities/<int:opportunity_id>")
@require_permission("WRITE_CRM")
def opportunity_update(opportunity_id):
    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status is not None and status not in STATUSES:
        return jsonify(error="Estado inválido"), 400
    changes = []
    if status is not None:
        opportunity.status = status
        changes.append(f"Estado actualizado a {status}")
        if status in {"RESPONDEU", "GANHO", "PERDIDO", "DESCARTADO"}:
            SalesTask.query.filter_by(opportunity_id=opportunity.id, status="PENDING").update({"status": "CANCELLED"})
    if "contactVerified" in data:
        opportunity.contact_verified = bool(data["contactVerified"])
        changes.append("Contacto validado" if opportunity.contact_verified else "Contacto pendiente de validación")
    if data.get("nextActionAt"):
        try:
            opportunity.next_action_at = datetime.fromisoformat(data["nextActionAt"].replace("Z", "+00:00"))
            changes.append("Próxima acción comercial programada")
        except ValueError:
            return jsonify(error="Fecha de seguimiento inválida"), 400
    if data.get("owner") is not None:
        opportunity.owner_name = str(data["owner"]).strip() or "Equipo comercial"
        changes.append("Responsable comercial actualizado")
    if data.get("estimatedValue") is not None:
        try:
            opportunity.estimated_value = max(0, float(data["estimatedValue"]))
            opportunity.potential_deal_value = opportunity.estimated_value
            changes.append("Valor estimado actualizado")
        except (TypeError, ValueError):
            return jsonify(error="Valor estimado inválido"), 400
    if data.get("probability") is not None:
        try:
            opportunity.probability = max(0, min(100, int(data["probability"])))
            changes.append("Probabilidad actualizada")
        except (TypeError, ValueError):
            return jsonify(error="Probabilidad inválida"), 400
    opportunity.expected_revenue = (opportunity.potential_deal_value or 0) * (opportunity.probability or 0) / 100
    if not changes:
        return jsonify(error="No se recibió ningún cambio"), 400
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="CRM_UPDATE", description=" · ".join(changes)))
    _audit("UPDATE", "OPPORTUNITY", opportunity.id, {"changes": changes})
    db.session.commit()
    return jsonify(opportunity.to_dict())


@api_bp.get("/timeline/<int:opportunity_id>")
def timeline(opportunity_id):
    tenant = current_tenant()
    Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    rows = TimelineEvent.query.filter_by(opportunity_id=opportunity_id).order_by(TimelineEvent.occurred_at.desc()).all()
    return jsonify([{"id": row.id, "type": row.event_type, "description": row.description, "occurredAt": row.occurred_at.isoformat()} for row in rows])


@api_bp.get("/companies/<int:company_id>/dossier")
def company_dossier(company_id):
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id, status="ACTIVE").first_or_404()
    contacts = Contact.query.filter_by(tenant_id=tenant.id, company_id=company.id, status="ACTIVE").order_by(Contact.influence_score.desc()).all()
    projects = Project.query.filter_by(tenant_id=tenant.id, company_id=company.id).order_by(Project.updated_at.desc()).all()
    opportunities = Opportunity.query.join(Project).filter(Project.company_id == company.id, Opportunity.tenant_id == tenant.id).order_by(Opportunity.updated_at.desc()).all()
    activities = CompanyActivity.query.filter_by(tenant_id=tenant.id, company_id=company.id).order_by(CompanyActivity.occurred_at.desc()).limit(200).all()
    completeness, missing = company_completeness(company)
    last_contact = activities[0].occurred_at if activities else None
    return jsonify(
        company={
            "id": company.id, "name": company.name, "legalName": company.legal_name, "ruc": company.ruc or company.registration_id,
            "sector": company.sector, "description": company.description, "website": company.website, "domain": company.domain,
            "country": company.country, "department": company.department, "city": company.city, "address": company.address,
            "headquarters": company.headquarters, "phone": company.phone_business or company.phone, "whatsapp": company.whatsapp,
            "email": company.email_business or company.email, "linkedin": company.linkedin_url, "companySize": company.company_size,
            "employeeEstimate": company.employee_estimate, "foundedYear": company.founded_year, "owners": company.owners or [],
            "operationPlants": company.operation_plants or [], "keyActivities": company.key_activities or [],
            "facilityProfile": company.facility_profile or {}, "digitalPresence": company.digital_presence or {}, "commercialNotes": company.commercial_notes,
            "dataSources": company.data_sources or [], "fit": company.account_fit_score, "accessibility": company.accessibility_score,
            "momentum": company.momentum_score, "completeness": completeness, "missing": missing,
            "lastEnrichedAt": company.last_enriched_at.isoformat() if company.last_enriched_at else None,
            "lastContactAt": last_contact.isoformat() if last_contact else None,
        },
        contacts=[{
            "id": c.id, "name": c.name, "role": c.role, "buyingRole": c.buying_role, "influence": c.influence_score,
            "email": c.email, "phone": c.phone, "whatsapp": c.whatsapp, "linkedin": c.linkedin_url,
            "confidence": c.confidence, "verifiedAt": c.verified_at.isoformat() if c.verified_at else None,
        } for c in contacts],
        projects=[{
            "id": pr.id, "name": pr.name, "type": pr.project_type, "stage": pr.stage, "lifecycle": pr.lifecycle_stage,
            "city": pr.city, "department": pr.department, "investment": pr.investment, "areaM2": float(pr.area_m2 or 0),
            "description": pr.description, "buyingWindow": pr.buying_window_score, "demandProbability": pr.demand_probability,
        } for pr in projects],
        opportunities=[op.to_dict() for op in opportunities],
        activities=[row.to_dict() for row in activities],
        stats={
            "contacts": len(contacts), "projects": len(projects), "opportunities": len(opportunities), "activities": len(activities),
            "openPipeline": round(sum(float(op.potential_deal_value or op.estimated_value or 0) for op in opportunities if op.status not in {"GANHO","PERDIDO","DESCARTADO"}), 2),
        },
    )


@api_bp.patch("/companies/<int:company_id>/profile")
@require_permission("WRITE_CRM")
def company_profile_update(company_id):
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    fields = {
        "name":"name", "legalName":"legal_name", "ruc":"ruc", "sector":"sector", "description":"description",
        "website":"website", "city":"city", "department":"department", "address":"address", "headquarters":"headquarters",
        "phone":"phone_business", "whatsapp":"whatsapp", "email":"email_business", "linkedin":"linkedin_url",
        "companySize":"company_size", "foundedYear":"founded_year", "commercialNotes":"commercial_notes",
        "owners":"owners", "operationPlants":"operation_plants", "keyActivities":"key_activities", "dataSources":"data_sources", "digitalPresence":"digital_presence",
    }
    changed=[]
    for key, attr in fields.items():
        if key in data:
            value=data[key]
            if key == "foundedYear" and value not in (None, ""):
                try: value=int(value)
                except (TypeError,ValueError): return jsonify(error="Año de fundación inválido"),400
            setattr(company, attr, value if value != "" else None)
            changed.append(key)
    if not changed:
        return jsonify(error="No se recibieron cambios"),400
    company.last_enriched_at=datetime.now(timezone.utc)
    company.data_completeness_score=company_completeness(company)[0]
    _audit("UPDATE", "COMPANY_PROFILE", company.id, {"fields":changed})
    db.session.commit()
    return jsonify(ok=True, companyId=company.id, completeness=company.data_completeness_score)


@api_bp.get("/companies/<int:company_id>/activities")
def company_activities(company_id):
    tenant=current_tenant()
    Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    rows=CompanyActivity.query.filter_by(tenant_id=tenant.id, company_id=company_id).order_by(CompanyActivity.occurred_at.desc()).limit(250).all()
    return jsonify([row.to_dict() for row in rows])


@api_bp.post("/companies/<int:company_id>/activities")
@require_permission("WRITE_CRM")
def company_activity_create(company_id):
    tenant=current_tenant(); user=current_user()
    company=Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data=request.get_json(silent=True) or {}
    activity_type=str(data.get("type") or "NOTE").upper()
    allowed={"CALL","EMAIL_SENT","WHATSAPP_SENT","VISIT","MEETING","PROPOSAL_SENT","FOLLOW_UP","NOTE","REPLY","DATA_UPDATE"}
    if activity_type not in allowed: return jsonify(error="Tipo de interacción inválido"),400
    next_at=None
    if data.get("nextActionAt"):
        try: next_at=datetime.fromisoformat(str(data["nextActionAt"]).replace("Z","+00:00"))
        except ValueError: return jsonify(error="Fecha de próxima acción inválida"),400
    occurred=datetime.now(timezone.utc)
    if data.get("occurredAt"):
        try: occurred=datetime.fromisoformat(str(data["occurredAt"]).replace("Z","+00:00"))
        except ValueError: pass
    row=CompanyActivity(
        tenant_id=tenant.id, company_id=company.id, opportunity_id=data.get("opportunityId"), contact_id=data.get("contactId"),
        activity_type=activity_type, channel=data.get("channel"), direction=str(data.get("direction") or "OUTBOUND").upper(),
        subject=data.get("subject"), summary=data.get("summary"), outcome=data.get("outcome"),
        next_action=data.get("nextAction"), next_action_at=next_at, occurred_at=occurred,
        created_by=(user.name if user else "Equipo comercial"), extra_data=data.get("extra") or {},
    )
    db.session.add(row)
    for op in Opportunity.query.join(Project).filter(Project.company_id==company.id, Opportunity.tenant_id==tenant.id).all():
        if activity_type in {"CALL","EMAIL_SENT","WHATSAPP_SENT","VISIT","MEETING","PROPOSAL_SENT","REPLY"}: op.last_contact_at=occurred
        if activity_type in {"CALL","EMAIL_SENT","WHATSAPP_SENT"} and op.status in {"NOVO","QUALIFICADO"}: op.status="CONTATO_REALIZADO"
        elif activity_type == "REPLY" and op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="RESPONDEU"
        elif activity_type in {"VISIT","MEETING"} and op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="VISITA"
        elif activity_type == "PROPOSAL_SENT" and op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="ORCAMENTO"
        if next_at: op.next_action_at=next_at
        db.session.add(TimelineEvent(opportunity=op,event_type=activity_type,description=data.get("summary") or data.get("subject") or "Interacción comercial registrada"))
    _audit("CREATE","COMPANY_ACTIVITY",company.id,{"type":activity_type})
    db.session.commit()
    return jsonify(row.to_dict()),201


@api_bp.post("/companies/<int:company_id>/message")
def company_contextual_message(company_id):
    tenant=current_tenant()
    company=Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data=request.get_json(silent=True) or {}
    contact=None
    if data.get("contactId"):
        contact=Contact.query.filter_by(id=data.get("contactId"), tenant_id=tenant.id, company_id=company.id).first()
    opportunity=None
    if data.get("opportunityId"):
        opportunity=Opportunity.query.filter_by(id=data.get("opportunityId"), tenant_id=tenant.id).first()
    if opportunity is None:
        opportunity=Opportunity.query.join(Project).filter(Project.company_id==company.id, Opportunity.tenant_id==tenant.id).order_by(Opportunity.score.desc()).first()
    return jsonify(_company_message(company, contact, str(data.get("channel") or "EMAIL"), opportunity))


@api_bp.post("/companies/<int:company_id>/email-draft")
@require_permission("WRITE_CRM")
def company_email_draft(company_id):
    """Genera un archivo .eml listo para abrir en Outlook con la carta institucional adjunta."""
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}

    contact = None
    if data.get("contactId"):
        contact = Contact.query.filter_by(
            id=data.get("contactId"), tenant_id=tenant.id, company_id=company.id
        ).first()

    opportunity = Opportunity.query.join(Project).filter(
        Project.company_id == company.id, Opportunity.tenant_id == tenant.id
    ).order_by(Opportunity.score.desc()).first()

    generated = _company_message(company, contact, "EMAIL", opportunity)
    recipient = str(data.get("recipient") or generated.get("recipientEmail") or "").strip()
    subject = str(data.get("subject") or generated.get("subject") or "Puertas Brasil Paraguay | Primer Contacto").strip()
    body = str(data.get("body") or generated.get("body") or "").strip()

    if not recipient or "@" not in recipient:
        return jsonify(
            error="No hay un correo electrónico válido para el destinatario.",
            action="Seleccione un contacto con correo o complete el correo general de la empresa en la Ficha 360°."
        ), 400

    attachment_path = Path(current_app.root_path) / "assets" / "Carta de presentacion - Puertas Brasil.pdf"
    if not attachment_path.exists():
        current_app.logger.error("Carta institucional no encontrada: %s", attachment_path)
        return jsonify(
            error="La carta institucional no está disponible en el servidor.",
            action="Verifique que el PDF institucional esté incluido en app/assets/."
        ), 500

    msg = EmailMessage(policy=SMTP)
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"
    # No se fija From: Outlook utilizará la cuenta configurada por el usuario al abrir el borrador.
    msg.set_content(body)
    pdf_bytes = attachment_path.read_bytes()
    msg.add_attachment(
        pdf_bytes, maintype="application", subtype="pdf",
        filename="Carta de presentacion - Puertas Brasil.pdf"
    )

    buffer = BytesIO(msg.as_bytes())
    buffer.seek(0)
    safe_company = secure_filename(company.name or "empresa")[:60] or "empresa"
    filename = f"Puertas_Brasil_Primer_Contacto_{safe_company}.eml"
    _audit("PREPARE", "EMAIL_DRAFT", company.id, {
        "recipient": recipient, "subject": subject, "contactId": contact.id if contact else None,
        "attachment": "Carta de presentacion - Puertas Brasil.pdf"
    })
    db.session.commit()
    return send_file(
        buffer, mimetype="message/rfc822", as_attachment=True, download_name=filename, max_age=0
    )


@api_bp.get("/exports/status")
def export_status():
    return jsonify(dataDir="/data", status="ready")


@api_bp.get("/collector/status")
def collector_status():
    tenant = current_tenant()
    last_run = CollectorRun.query.filter_by(tenant_id=tenant.id).order_by(CollectorRun.started_at.desc()).first()
    pending = ProspectSignal.query.filter_by(tenant_id=tenant.id, status="PENDING_VALIDATION").count()
    return jsonify(enabled=True, pending=pending, lastRun=last_run.to_dict() if last_run else None)


@api_bp.post("/collector/run")
@require_permission("RUN_COLLECTOR")
def collector_run():
    from datetime import datetime, timedelta, timezone
    tenant = current_tenant()
    recent = CollectorRun.query.filter_by(tenant_id=tenant.id).order_by(CollectorRun.started_at.desc()).first()
    if recent and recent.started_at and recent.started_at > datetime.now(timezone.utc) - timedelta(minutes=1):
        return jsonify(error="La captación ya fue ejecutada recientemente", run=recent.to_dict()), 429
    from ..services.collector import run_collector
    run = run_collector()
    return jsonify(run.to_dict())


@api_bp.post("/signals/<int:signal_id>/approve")
@require_permission("WRITE_CRM")
def signal_approve(signal_id):
    tenant = current_tenant()
    signal = ProspectSignal.query.filter_by(id=signal_id, tenant_id=tenant.id).first_or_404()
    if signal.opportunity_id:
        return jsonify(signal.to_dict())
    opportunity, _ = _create_intelligence_opportunity({
        "company": signal.company_name, "project": signal.title, "city": signal.city or "Por validar",
        "department": signal.department or "Por validar", "country": "Paraguay", "event": signal.event_type,
        "score": signal.score, "icpFit": signal.score, "intent": signal.score,
        "dataConfidence": signal.source_reliability, "products": signal.products or [],
        "evidence": signal.summary, "sourceName": signal.source_name, "sourceUrl": signal.source_url,
        "sourceType": signal.source_type, "sourceReliability": signal.source_reliability,
        "publishedAt": signal.published_at, "evidenceClassification": "FACT",
        "stage": "Prospección automática", "buyingWindow": signal.buying_window_score,
        "timing": signal.buying_window_score, "momentum": min(100, 45 + signal.momentum_delta),
        "projectValueFit": min(100, 45 + int(float(signal.estimated_deal_max or 0) / 2500)),
        "productFit": signal.demand_probability, "causality": signal.causality or [],
        "potentialDealValue": (float(signal.estimated_deal_min or 0) + float(signal.estimated_deal_max or 0)) / 2,
    })
    signal.status, signal.opportunity_id = "APPROVED", opportunity.id
    db.session.commit()
    return jsonify(opportunity=opportunity.to_dict(), signal=signal.to_dict()), 201


@api_bp.post("/signals/<int:signal_id>/discard")
@require_permission("WRITE_CRM")
def signal_discard(signal_id):
    tenant = current_tenant()
    signal = ProspectSignal.query.filter_by(id=signal_id, tenant_id=tenant.id).first_or_404()
    signal.status = "DISCARDED"
    db.session.commit()
    return jsonify(signal.to_dict())


@api_bp.post("/website-analysis")
def website_analysis_create():
    data = request.get_json(silent=True) or {}
    if not data.get("url"):
        return jsonify(error="Ingrese el sitio web de la empresa"), 400
    mode = str(data.get("mode") or "quick").lower()
    force = bool(data.get("force"))
    try:
        from ..services.site_analyzer import SiteAnalysisError, analyze_website, classify_site_error, normalize_website_url
        normalized = normalize_website_url(data["url"])
        tenant = current_tenant()
        fresh_since = datetime.now(timezone.utc) - timedelta(hours=12)
        cached = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id, url=normalized).filter(
            WebsiteAnalysis.created_at >= fresh_since, WebsiteAnalysis.status == "COMPLETED"
        ).order_by(WebsiteAnalysis.created_at.desc()).first()
        if cached and not force and (cached.diagnostics or {}).get("enrichment"):
            payload = cached.to_dict(); payload.update(cached=True, scanMode="deep")
            synced = _auto_sync_existing_company(cached)
            if synced: payload["crmSync"] = synced
            return jsonify(payload), 200
        if mode == "deep":
            analysis = analyze_website(normalized, max_pages=18, use_sitemap=True, request_timeout=12, status="COMPLETED")
            payload = analysis.to_dict(); payload.update(cached=False, scanMode="deep")
            synced = _auto_sync_existing_company(analysis)
            if synced: payload["crmSync"] = synced
            return jsonify(payload), 201
        analysis = analyze_website(normalized, max_pages=3, use_sitemap=False, request_timeout=8, status="QUICK")
        payload = analysis.to_dict(); payload.update(cached=False, scanMode="quick")
        synced = _auto_sync_existing_company(analysis)
        if synced: payload["crmSync"] = synced
        return jsonify(payload), 201
    except SiteAnalysisError as exc:
        db.session.rollback()
        return jsonify(error=exc.message, errorDetails=exc.to_dict(), alternatives=exc.alternatives), exc.status
    except Exception as exc:
        db.session.rollback()
        from ..services.site_analyzer import classify_site_error
        diagnosed = classify_site_error(data.get("url"), exc, "análisis del sitio")
        return jsonify(error=diagnosed.message, errorDetails=diagnosed.to_dict(), alternatives=diagnosed.alternatives), diagnosed.status


@api_bp.post("/website-analysis/<int:analysis_id>/deep")
def website_analysis_deep(analysis_id):
    tenant = current_tenant()
    analysis = WebsiteAnalysis.query.filter_by(id=analysis_id, tenant_id=tenant.id).first_or_404()
    try:
        from ..services.site_analyzer import SiteAnalysisError, analyze_website, classify_site_error
        analysis = analyze_website(analysis.url, max_pages=18, use_sitemap=True, request_timeout=12, analysis=analysis, status="COMPLETED")
        payload = analysis.to_dict(); payload.update(cached=False, scanMode="deep")
        synced = _auto_sync_existing_company(analysis)
        if synced: payload["crmSync"] = synced
        return jsonify(payload), 200
    except SiteAnalysisError as exc:
        db.session.rollback()
        return jsonify(error=exc.message, errorDetails=exc.to_dict(), alternatives=exc.alternatives), exc.status
    except Exception as exc:
        db.session.rollback()
        from ..services.site_analyzer import classify_site_error
        diagnosed = classify_site_error(analysis.url, exc, "análisis profundo")
        return jsonify(error=diagnosed.message, errorDetails=diagnosed.to_dict(), alternatives=diagnosed.alternatives), diagnosed.status


@api_bp.post("/website-analysis/alternatives")
def website_analysis_alternatives():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(error="Ingrese un sitio para buscar alternativas"), 400
    from ..services.site_analyzer import discover_alternative_sites
    alternatives = discover_alternative_sites(url, timeout=4)
    return jsonify(alternatives=alternatives, count=len(alternatives))


@api_bp.post("/website-analysis/bulk")
def website_analysis_bulk():
    data = request.get_json(silent=True) or {}
    raw = data.get("urls") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace("\r", "\n").split("\n") if part.strip()]
    urls = []
    for item in raw:
        candidate = str(item).strip()
        if candidate and candidate not in urls:
            urls.append(candidate)
    if not urls:
        return jsonify(error="Ingrese al menos un sitio o URL"), 400
    if len(urls) > 25:
        return jsonify(error="El análisis en lote admite hasta 25 sitios por ejecución"), 400
    from ..services.site_analyzer import analyze_website, normalize_website_url
    results, errors = [], []
    tenant = current_tenant()
    fresh_since = datetime.now(timezone.utc) - timedelta(hours=12)
    for url in urls:
        try:
            normalized = normalize_website_url(url)
            cached = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id, url=normalized).filter(
                WebsiteAnalysis.created_at >= fresh_since, WebsiteAnalysis.status == "COMPLETED"
            ).order_by(WebsiteAnalysis.created_at.desc()).first()
            if cached:
                payload = cached.to_dict(); payload.update(cached=True, scanMode="deep")
            else:
                analysis = analyze_website(normalized, max_pages=3, use_sitemap=False, request_timeout=8, status="QUICK")
                payload = analysis.to_dict(); payload.update(cached=False, scanMode="quick")
            results.append(payload)
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:180]})
    return jsonify(results=results, errors=errors, analyzed=len(results), failed=len(errors)), 207 if errors else 201


@api_bp.get("/website-analysis")
def website_analysis_list():
    tenant = current_tenant()
    rows = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id).order_by(WebsiteAnalysis.created_at.desc()).limit(30).all()
    return jsonify([row.to_dict() for row in rows])


def _commercial_messages(analysis):
    brand = current_tenant().settings or {}
    brand_name = brand.get("brand_name", "Puertas Brasil")
    company = analysis.company_name
    sector = analysis.sector or "su operación"
    products = analysis.products or []
    product_text = ", ".join(products[:3]) if products else "soluciones de accesos automáticos e industriales"
    whatsapp = (
        f"Hola, ¿cómo está? Soy David Granja, de {brand_name}. Me gustaría presentar nuestra empresa y ponernos a disposición de {company}. "
        f"Por el perfil de su operación en {sector}, vemos posibles aplicaciones para {product_text}. "
        "¿Podría indicarme el nombre o contacto directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos? Muchas gracias."
    )
    subject = f"Puertas Brasil Paraguay | Primer Contacto — {company}"
    email = (
        f"Estimado equipo de {company},\n\n"
        "Es un gusto saludarles.\n\n"
        "Mi nombre es David Granja y represento a Puertas Brasil, empresa especializada en soluciones de accesos automáticos e industriales, con fábrica ubicada en el km 13 de Ciudad del Este.\n\n"
        f"Nos gustaría presentar nuestra empresa y ponernos a disposición de {company}.\n\n"
        f"En operaciones del segmento {sector}, los accesos pueden influir en la seguridad, el flujo de mercaderías y personas y la continuidad de recepción, expedición y operación. Por el perfil identificado, vemos posibles aplicaciones para {product_text}.\n\n"
        "Adjunto nuestra carta de presentación institucional y catálogo comercial.\n\n"
        "¿Podrían indicarme el nombre y el correo directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos?\n\n"
        "Desde ya, agradezco mucho su orientación.\n\n"
        f"Saludos cordiales,\nDavid Granja\n{brand_name}"
    )
    return whatsapp, subject, email


@api_bp.post("/website-analysis/<int:analysis_id>/qualify")
@require_permission("WRITE_CRM")
def website_analysis_qualify(analysis_id):
    tenant = current_tenant()
    analysis = WebsiteAnalysis.query.filter_by(id=analysis_id, tenant_id=tenant.id).first_or_404()
    if analysis.opportunity_id:
        return jsonify(analysis=analysis.to_dict(), opportunity=analysis.opportunity.to_dict())
    evidence = "; ".join(analysis.reasons or []) or analysis.summary or "Análisis público del sitio empresarial"
    opportunity, _ = _create_intelligence_opportunity({
        "company": analysis.company_name, "sector": analysis.sector, "website": analysis.url,
        "address": analysis.address, "phone": analysis.phones[0] if analysis.phones else None,
        "whatsapp": analysis.whatsapp, "email": analysis.emails[0] if analysis.emails else None,
        "linkedin": (analysis.social_links or {}).get("linkedin"),
        "project": f"Calificación comercial desde {analysis.url}",
        "city": (analysis.address or "Por validar")[:120], "department": "Por validar",
        "stage": "Empresa calificada desde análisis web", "projectType": "ACCOUNT_RESEARCH",
        "event": "BUYING_INTENT", "score": analysis.potential_score, "icpFit": analysis.potential_score,
        "intent": analysis.potential_score, "productFit": analysis.potential_score,
        "dataConfidence": min(90, 45 + analysis.pages_analyzed * 10), "signalRecency": 100,
        "products": analysis.products or [], "evidence": evidence,
        "sourceName": "Análisis minucioso del sitio", "sourceUrl": analysis.url,
        "sourceType": "COMPANY_WEBSITE", "evidenceClassification": "INFERENCE",
        "buyingStage": "RESEARCH",
    }, status="QUALIFICADO")
    whatsapp, subject, email = _commercial_messages(analysis)
    analysis.decision, analysis.opportunity_id = "QUALIFIED", opportunity.id
    analysis.whatsapp_message, analysis.email_subject, analysis.email_body = whatsapp, subject, email
    opportunity.project.company.last_enriched_at = datetime.now(timezone.utc)
    presence = dict(opportunity.project.company.digital_presence or {})
    presence["officialWebsite"] = analysis.url
    presence["alternativeSites"] = analysis.alternative_sites or []
    presence["socialLinks"] = analysis.social_links or {}
    presence["lastVerifiedAt"] = datetime.now(timezone.utc).isoformat()
    opportunity.project.company.digital_presence = presence
    auto_fill = _merge_company_enrichment(opportunity.project.company, analysis, source_label="Calificación automática desde sitio")
    opportunity.project.company.data_completeness_score = company_completeness(opportunity.project.company)[0]
    lead_readiness(opportunity)
    db.session.add(TimelineEvent(
        opportunity=opportunity, event_type="WEBSITE_QUALIFICATION",
        description="Empresa calificada manualmente; mensajes comerciales personalizados generados",
    ))
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=opportunity.project.company.id, opportunity_id=opportunity.id, activity_type="DATA_UPDATE", channel="SITIO_WEB", subject="Empresa calificada desde su sitio", summary=f"Análisis web completado con puntuación {analysis.potential_score}/100 y {analysis.pages_analyzed} páginas analizadas."))
    db.session.commit()
    return jsonify(analysis=analysis.to_dict(), opportunity=opportunity.to_dict()), 201


@api_bp.post("/website-analysis/<int:analysis_id>/disqualify")
@require_permission("WRITE_CRM")
def website_analysis_disqualify(analysis_id):
    tenant = current_tenant()
    analysis = WebsiteAnalysis.query.filter_by(id=analysis_id, tenant_id=tenant.id).first_or_404()
    if analysis.opportunity_id:
        return jsonify(error="La empresa ya ingresó al CRM; márquela como descartada desde el CRM"), 409
    analysis.decision = "DISQUALIFIED"
    db.session.commit()
    return jsonify(analysis.to_dict())


@api_bp.post("/tasks/ensure")
def tasks_ensure():
    created = 0
    tenant = current_tenant()
    rows = Opportunity.query.filter(Opportunity.tenant_id == tenant.id, ~Opportunity.status.in_({"RESPONDEU", "GANHO", "PERDIDO", "DESCARTADO"})).all()
    for opportunity in rows:
        if not opportunity.tasks:
            _create_cadence(opportunity)
            created += 4
    db.session.commit()
    return jsonify(created=created)


@api_bp.get("/dashboard/today")
def dashboard_today():
    tenant = current_tenant()
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    tasks = SalesTask.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id, SalesTask.status == "PENDING", SalesTask.due_at <= tomorrow).order_by(SalesTask.due_at.asc()).limit(50).all()
    return jsonify(
        tasks=[task.to_dict() for task in tasks],
        overdue=sum(1 for task in tasks if task.due_at.replace(tzinfo=timezone.utc) < now if task.due_at.tzinfo is None) + sum(1 for task in tasks if task.due_at.tzinfo is not None and task.due_at < now),
        dueToday=len(tasks),
    )


@api_bp.patch("/tasks/<int:task_id>")
@require_permission("WRITE_CRM")
def task_update(task_id):
    tenant = current_tenant()
    task = SalesTask.query.join(Opportunity).filter(SalesTask.id == task_id, Opportunity.tenant_id == tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if data.get("status") not in {"DONE", "PENDING", "CANCELLED"}:
        return jsonify(error="Estado de tarea inválido"), 400
    task.status = data["status"]
    task.completed_at = datetime.now(timezone.utc) if task.status == "DONE" else None
    if task.status == "DONE":
        task.opportunity.next_action_at = min((row.due_at for row in task.opportunity.tasks if row.status == "PENDING"), default=None)
        db.session.add(TimelineEvent(opportunity=task.opportunity, event_type="TASK_DONE", description=f"Tarea completada: {task.title}"))
    db.session.commit()
    return jsonify(task.to_dict())


@api_bp.post("/visits")
@require_permission("WRITE_CRM")
def visit_create():
    data = request.form if request.files else (request.get_json(silent=True) or {})
    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=int(data.get("opportunityId", 0)), tenant_id=tenant.id).first_or_404()
    photos = []
    upload_dir = Path(current_app.config["DATA_DIR"]) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for uploaded in request.files.getlist("photos"):
        extension = Path(secure_filename(uploaded.filename or "")).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        filename = f"{uuid4().hex}{extension}"
        uploaded.save(upload_dir / filename)
        photos.append(filename)
    visit = VisitRecord(
        opportunity=opportunity, measurements=data.get("measurements"), needs=data.get("needs"),
        notes=data.get("notes"), next_step=data.get("nextStep"), photos=photos,
    )
    opportunity.status = "VISITA"
    opportunity.probability = max(opportunity.probability, 50)
    db.session.add(visit)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="VISIT", description=f"Visita registrada. Próximo paso: {data.get('nextStep') or 'por definir'}"))
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=opportunity.project.company.id, opportunity_id=opportunity.id, activity_type="VISIT", channel="PRESENCIAL", subject="Visita comercial registrada", summary=data.get("notes") or data.get("needs") or "Visita técnica/comercial", next_action=data.get("nextStep")))
    db.session.commit()
    return jsonify(id=visit.id, photos=[f"/api/uploads/{name}" for name in photos]), 201


@api_bp.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(Path(current_app.config["DATA_DIR"]) / "uploads", filename)


@api_bp.post("/proposals/<int:opportunity_id>")
@require_permission("WRITE_CRM")
def proposal_create(opportunity_id):
    import textwrap
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    brand = tenant.settings or {}
    data = request.get_json(silent=True) or {}
    try:
        amount = max(0, float(data.get("amount", 0)))
        validity = max(1, min(90, int(data.get("validityDays", 15))))
    except (TypeError, ValueError):
        return jsonify(error="Valor o validez inválidos"), 400
    scope = (data.get("scope") or "").strip()
    if not scope:
        return jsonify(error="Describa el alcance de la propuesta"), 400
    number = f"PB-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    folder = Path(current_app.config["DATA_DIR"]) / "proposals"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{number}.pdf"
    path = folder / filename
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    pdf.setFillColorRGB(.07, .12, .21); pdf.rect(0, height - 105, width, 105, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1); pdf.setFont("Helvetica-Bold", 22); pdf.drawString(45, height - 55, brand.get("brand_name", tenant.name).upper())
    pdf.setFont("Helvetica", 10); pdf.drawString(45, height - 78, f"Propuesta comercial {number}")
    y = height - 145; pdf.setFillColorRGB(.08, .13, .22)
    for title, value in (("Cliente", opportunity.project.company.name), ("Proyecto", opportunity.project.name), ("Ubicación", f"{opportunity.project.city}, {opportunity.project.department}"), ("Validez", f"{validity} días"), ("Valor estimado", f"USD {amount:,.2f}")):
        pdf.setFont("Helvetica-Bold", 10); pdf.drawString(45, y, f"{title}:"); pdf.setFont("Helvetica", 10); pdf.drawString(130, y, str(value)); y -= 22
    y -= 10; pdf.setFont("Helvetica-Bold", 13); pdf.drawString(45, y, "Alcance propuesto"); y -= 24
    pdf.setFont("Helvetica", 10)
    for line in textwrap.wrap(scope, 90): pdf.drawString(45, y, line); y -= 15
    y -= 16; pdf.setFont("Helvetica-Bold", 12); pdf.drawString(45, y, "Productos y servicios recomendados"); y -= 21
    pdf.setFont("Helvetica", 10)
    for product in opportunity.products or ["Evaluación técnica de accesos industriales"]: pdf.drawString(55, y, f"• {product}"); y -= 16
    pdf.setFont("Helvetica", 9); pdf.drawString(45, 65, " · ".join(filter(None, (brand.get("sales_phone"), brand.get("sales_email"), brand.get("website")))))
    pdf.save()
    proposal = Proposal(opportunity=opportunity, number=number, amount=amount, validity_days=validity, scope=scope, pdf_filename=filename)
    opportunity.status = "ORCAMENTO"; opportunity.estimated_value = amount; opportunity.probability = max(opportunity.probability, 60)
    db.session.add(proposal); db.session.flush()
    db.session.add(SalesTask(opportunity=opportunity, title="Acompañar respuesta de la propuesta comercial", channel="FOLLOW_UP", due_at=datetime.now(timezone.utc) + timedelta(days=3), sequence_step=90))
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="PROPOSAL", description=f"Propuesta {number} generada por USD {amount:,.2f}"))
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=opportunity.project.company.id, opportunity_id=opportunity.id, activity_type="PROPOSAL_SENT", channel="DOCUMENTO", subject=f"Propuesta {number}", summary=f"Propuesta comercial generada por USD {amount:,.2f}. Registrar el envío al cliente cuando sea efectivamente enviado.", outcome="GENERATED"))
    db.session.commit()
    return jsonify(id=proposal.id, number=number, downloadUrl=f"/api/proposals/{proposal.id}/download"), 201


@api_bp.get("/proposals/<int:proposal_id>/download")
def proposal_download(proposal_id):
    tenant = current_tenant()
    proposal = Proposal.query.join(Opportunity).filter(Proposal.id == proposal_id, Opportunity.tenant_id == tenant.id).first_or_404()
    path = Path(current_app.config["DATA_DIR"]) / "proposals" / proposal.pdf_filename
    return send_file(path, as_attachment=True, download_name=f"Propuesta-{proposal.number}.pdf")


@api_bp.get("/metrics")
def commercial_metrics():
    tenant = current_tenant()
    opportunities = Opportunity.query.filter_by(tenant_id=tenant.id).all()
    proposals = Proposal.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id).all()
    active = [row for row in opportunities if row.status not in {"GANHO", "PERDIDO", "DESCARTADO"}]
    contacted = [row for row in opportunities if row.status not in {"NOVO", "QUALIFICADO", "DESCARTADO"}]
    won = [row for row in opportunities if row.status == "GANHO"]
    overdue = SalesTask.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id, SalesTask.status == "PENDING", SalesTask.due_at < datetime.now(timezone.utc)).count()
    companies = Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").all()
    sales_ready = sum(1 for row in active if row.sales_ready)
    with_decision_maker = sum(1 for company in companies if company.contacts)
    completeness = round(sum(company.data_completeness_score or 0 for company in companies) / len(companies), 1) if companies else 0
    return jsonify(
        opportunities=len(opportunities), contacted=len(contacted), proposals=len(proposals), won=len(won),
        pipelineValue=sum(row.estimated_value or 0 for row in active),
        weightedValue=sum((row.estimated_value or 0) * (row.probability or 0) / 100 for row in active),
        proposalValue=sum(row.amount for row in proposals), overdueTasks=overdue, salesReady=sales_ready,
        responseRate=round(100 * len(contacted) / len(opportunities), 1) if opportunities else 0,
        winRate=round(100 * len(won) / len(opportunities), 1) if opportunities else 0,
        accounts=len(companies), withDecisionMaker=with_decision_maker, averageCompleteness=completeness,
        decisionMakerCoverage=round(100 * with_decision_maker / len(companies), 1) if companies else 0,
    )


def _pagination():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(100, int(request.args.get("perPage", 25))))
    except ValueError:
        page, per_page = 1, 25
    return page, per_page


@api_bp.get("/companies")
def companies_list():
    tenant = current_tenant()
    page, per_page = _pagination()
    query = Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE")
    if request.args.get("q"):
        query = query.filter(Company.normalized_name.contains(request.args["q"].strip().casefold()))
    pagination = query.order_by(Company.name).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[{
        "id": row.id, "name": row.name, "canonicalName": row.canonical_name,
        "normalizedName": row.normalized_name, "sector": row.sector, "domain": row.domain,
        "city": row.city, "department": row.department, "country": row.country,
        "identityConfidence": row.identity_confidence, "projects": len(row.projects),
        "accountFit": row.account_fit_score, "accessibility": row.accessibility_score,
        "momentum": row.momentum_score, "watchStatus": row.watch_status,
        "contacts": len(row.contacts), "lastSignalAt": row.last_signal_at.isoformat() if row.last_signal_at else None,
    } for row in pagination.items], page=page, perPage=per_page, total=pagination.total)


@api_bp.get("/projects")
def projects_list():
    tenant = current_tenant()
    page, per_page = _pagination()
    query = Project.query.filter_by(tenant_id=tenant.id, status="ACTIVE")
    if request.args.get("companyId"):
        query = query.filter_by(company_id=request.args["companyId"])
    pagination = query.order_by(Project.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[{
        "id": row.id, "companyId": row.company_id, "company": row.company.name,
        "name": row.name, "projectType": row.project_type, "city": row.city,
        "department": row.department, "country": row.country, "stage": row.stage,
        "investmentAmount": float(row.investment_amount) if row.investment_amount is not None else None,
        "investmentCurrency": row.investment_currency, "signals": len(row.signals),
        "lifecycleStage": row.lifecycle_stage, "buyingWindow": row.buying_window_score,
        "demandProbability": row.demand_probability, "momentum": row.momentum_score,
        "estimatedDealMin": float(row.estimated_deal_min or 0), "estimatedDealMax": float(row.estimated_deal_max or 0),
    } for row in pagination.items], page=page, perPage=per_page, total=pagination.total)


@api_bp.get("/sources")
def sources_list():
    tenant = current_tenant()
    page, per_page = _pagination()
    pagination = Source.query.filter_by(tenant_id=tenant.id).order_by(Source.reliability.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[{
        "id": row.id, "name": row.name, "type": row.source_type, "domain": row.domain,
        "reliability": row.reliability, "status": row.status, "documents": len(row.documents),
    } for row in pagination.items], page=page, perPage=per_page, total=pagination.total)


@api_bp.get("/intelligence/signals")
@api_bp.get("/signals")
def intelligence_signals_list():
    tenant = current_tenant()
    page, per_page = _pagination()
    query = Signal.query.filter_by(tenant_id=tenant.id)
    if request.args.get("type"):
        query = query.filter_by(signal_type=request.args["type"])
    pagination = query.order_by(Signal.detected_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[{
        "id": row.id, "company": row.company.name if row.company else "UNKNOWN",
        "project": row.project.name if row.project else "UNKNOWN", "type": row.signal_type,
        "title": row.title, "summary": row.summary, "confidence": row.confidence,
        "freshness": row.freshness, "relevance": row.relevance, "status": row.status,
        "impact": row.impact_score, "buyingWindow": row.buying_window_score,
        "lifecycleStage": row.lifecycle_stage, "causality": row.causality or [],
        "productHypothesis": row.product_hypothesis or [],
        "detectedAt": row.detected_at.isoformat(),
    } for row in pagination.items], page=page, perPage=per_page, total=pagination.total)


@api_bp.get("/scores")
def scores_list():
    tenant = current_tenant()
    page, per_page = _pagination()
    query = OpportunityScore.query.filter_by(tenant_id=tenant.id)
    if request.args.get("current", "true").lower() == "true":
        query = query.filter_by(is_current=True)
    pagination = query.order_by(OpportunityScore.calculated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[{
        "id": row.id, "opportunityId": row.opportunity_id, "total": row.total_score,
        "modelVersion": row.model_version, "isCurrent": row.is_current,
        "calculatedAt": row.calculated_at.isoformat(),
    } for row in pagination.items], page=page, perPage=per_page, total=pagination.total)


@api_bp.get("/opportunities/<int:opportunity_id>/intelligence")
def opportunity_intelligence(opportunity_id):
    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    evaluation = OpportunityScore.query.filter_by(
        tenant_id=tenant.id, opportunity_id=opportunity.id, is_current=True,
    ).order_by(OpportunityScore.calculated_at.desc()).first()
    evidence_rows = Evidence.query.join(OpportunityEvidence).filter(
        OpportunityEvidence.opportunity_id == opportunity.id, Evidence.tenant_id == tenant.id,
    ).order_by(Evidence.created_at.desc()).all()
    return jsonify(
        opportunity=opportunity.to_dict(),
        score={
            "total": evaluation.total_score, "modelVersion": evaluation.model_version,
            "calculatedAt": evaluation.calculated_at.isoformat(),
            "factors": [{
                "code": factor.factor_code, "value": float(factor.raw_value),
                "weight": float(factor.weight), "points": float(factor.points),
                "explanation": factor.explanation,
            } for factor in evaluation.factors],
        } if evaluation else None,
        evidence=[{
            "id": row.id, "classification": row.classification, "claim": row.claim,
            "confidence": row.confidence, "source": row.source_document.source.name,
            "url": row.source_document.canonical_url,
            "publishedAt": row.source_document.published_at.isoformat() if row.source_document.published_at else None,
        } for row in evidence_rows],
        productMatches=[{
            "product": row.product.name, "fit": row.fit_score, "confidence": row.confidence,
            "why": row.rationale,
        } for row in opportunity.product_matches],
    )


@api_bp.get("/dashboard/revenue-intelligence")
def revenue_intelligence_dashboard():
    tenant = current_tenant()
    opportunities = Opportunity.query.filter_by(tenant_id=tenant.id).all()
    active = [row for row in opportunities if row.status not in {"GANHO", "PERDIDO", "DESCARTADO"}]
    return jsonify(
        tenant={"id": tenant.id, "name": tenant.name},
        companies=Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").count(),
        projects=Project.query.filter_by(tenant_id=tenant.id, status="ACTIVE").count(),
        signals=Signal.query.filter_by(tenant_id=tenant.id).count(),
        sources=Source.query.filter_by(tenant_id=tenant.id).count(),
        opportunities=len(opportunities), hot=sum(1 for row in active if row.level == "HOT"),
        qualified=sum(1 for row in opportunities if row.status not in {"NOVO", "DESCARTADO"}),
        pipelineGenerated=sum(float(row.potential_deal_value or row.estimated_value or 0) for row in active),
        expectedRevenue=sum(float(row.expected_revenue or 0) for row in active),
        evidence=Evidence.query.filter_by(tenant_id=tenant.id).count(),
    )


@api_bp.get("/radar/command-center")
def radar_command_center():
    tenant = current_tenant()
    active = Opportunity.query.filter(
        Opportunity.tenant_id == tenant.id,
        ~Opportunity.status.in_({"GANHO", "PERDIDO", "DESCARTADO"}),
    ).all()
    hot_now = sorted(active, key=lambda row: (row.score, row.buying_window_score, row.momentum_score), reverse=True)[:12]
    momentum = sorted(active, key=lambda row: row.momentum_score, reverse=True)[:12]
    watch = Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").filter(Company.watch_status.in_({"WATCH", "WARM", "HOT"})).order_by(Company.momentum_score.desc()).limit(20).all()
    research_queue = Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").filter(
        (Company.accessibility_score < 35) | (Company.identity_confidence < 65)
    ).order_by(Company.account_fit_score.desc(), Company.momentum_score.desc()).limit(25).all()
    return jsonify(
        hotNow=[row.to_dict() for row in hot_now],
        momentum=[row.to_dict() for row in momentum],
        watchlist=[{
            "id": row.id, "company": row.name, "city": row.city, "department": row.department,
            "fit": row.account_fit_score, "accessibility": row.accessibility_score, "momentum": row.momentum_score,
            "status": row.watch_status, "lastSignalAt": row.last_signal_at.isoformat() if row.last_signal_at else None,
        } for row in watch],
        researchQueue=[{
            "id": row.id, "company": row.name, "fit": row.account_fit_score,
            "accessibility": row.accessibility_score, "identityConfidence": row.identity_confidence,
            "missing": [name for name, present in (("website", row.website), ("phone", row.phone_business or row.phone), ("email", row.email_business or row.email), ("decisionMaker", bool(row.contacts))) if not present],
        } for row in research_queue],
        summary={
            "activeOpportunities": len(active), "hot": sum(1 for row in active if row.level == "HOT"),
            "buyingWindow": sum(1 for row in active if row.buying_window_score >= 80),
            "accelerating": sum(1 for row in active if row.momentum_score >= 65),
            "pipelinePotential": round(sum(float(row.deal_value_max or row.potential_deal_value or 0) for row in active), 2),
        },
    )


@api_bp.get("/companies/<int:company_id>/contacts")
def company_contacts(company_id):
    tenant = current_tenant()
    Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    rows = Contact.query.filter_by(tenant_id=tenant.id, company_id=company_id, status="ACTIVE").order_by(Contact.influence_score.desc()).all()
    return jsonify([{
        "id": row.id, "name": row.name, "role": row.role, "buyingRole": row.buying_role,
        "influence": row.influence_score, "email": row.email, "phone": row.phone, "whatsapp": row.whatsapp,
        "linkedin": row.linkedin_url, "confidence": row.confidence,
    } for row in rows])


@api_bp.post("/companies/<int:company_id>/contacts")
@require_permission("WRITE_CRM")
def company_contact_create(company_id):
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify(error="Falta el nombre del contacto"), 400
    contact = Contact(
        tenant_id=tenant.id, company_id=company.id, name=str(data["name"]).strip(), role=data.get("role"),
        buying_role=(data.get("buyingRole") or "UNKNOWN").upper(), influence_score=max(0, min(100, int(data.get("influence", 50)))),
        email=data.get("email"), phone=data.get("phone"), whatsapp=data.get("whatsapp"),
        linkedin_url=data.get("linkedin"), source_url=data.get("sourceUrl"), confidence=max(0, min(100, int(data.get("confidence", 60)))),
    )
    db.session.add(contact)
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=company.id, contact_id=None, activity_type="DATA_UPDATE", channel="CRM", subject="Contacto añadido", summary=f"Se añadió el contacto {contact.name} · {contact.role or 'cargo por validar'}", created_by=(current_user().name if current_user() else "Equipo comercial")))
    company.accessibility_score = min(100, (company.accessibility_score or 0) + 15)
    company.last_enriched_at = datetime.now(timezone.utc)
    for opportunity in Opportunity.query.join(Project).filter(Project.company_id == company.id, Opportunity.tenant_id == tenant.id).all():
        lead_readiness(opportunity)
    db.session.commit()
    return jsonify(id=contact.id, companyId=company.id), 201


@api_bp.post("/companies/<int:company_id>/watch")
@require_permission("WRITE_CRM")
def company_watch(company_id):
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    row = Watchlist.query.filter_by(tenant_id=tenant.id, company_id=company.id).first()
    if not row:
        row = Watchlist(tenant_id=tenant.id, company_id=company.id)
        db.session.add(row)
    row.priority = max(0, min(100, int(data.get("priority", max(company.account_fit_score or 50, company.momentum_score or 0)))))
    row.reason = data.get("reason") or row.reason or "Cuenta estratégica para monitoreo de señales"
    row.status = "ACTIVE"
    row.next_check_at = datetime.now(timezone.utc) + timedelta(days=max(1, int(data.get("checkEveryDays", 7))))
    company.watch_status = "HOT" if company.momentum_score >= 75 else "WARM" if company.momentum_score >= 50 else "WATCH"
    db.session.commit()
    return jsonify(id=row.id, company=company.name, status=company.watch_status, priority=row.priority), 201


@api_bp.get("/watchlist")
def watchlist_list():
    tenant = current_tenant()
    rows = Watchlist.query.filter_by(tenant_id=tenant.id, status="ACTIVE").order_by(Watchlist.priority.desc()).all()
    return jsonify([{
        "id": row.id, "companyId": row.company_id, "company": row.company.name, "priority": row.priority,
        "reason": row.reason, "momentum": row.company.momentum_score, "fit": row.company.account_fit_score,
        "nextCheckAt": row.next_check_at.isoformat() if row.next_check_at else None,
    } for row in rows])



@api_bp.get("/companies/enrichment-queue")
def company_enrichment_queue():
    tenant=current_tenant()
    try:
        limit=max(1,min(200,int(request.args.get("limit",100))))
    except ValueError:
        limit=100
    rows=Company.query.filter_by(tenant_id=tenant.id,status="ACTIVE").order_by(Company.last_enriched_at.asc().nullsfirst(),Company.account_fit_score.desc()).limit(limit).all()
    return jsonify([{
        "id":c.id,"name":c.name,"website":c.website,"domain":c.domain,"completeness":company_completeness(c)[0],
        "lastEnrichedAt":c.last_enriched_at.isoformat() if c.last_enriched_at else None,
        "researchStatus":c.research_status,
        "canAutoEnrich":bool(c.website),
    } for c in rows])


@api_bp.post("/companies/<int:company_id>/auto-enrich")
@require_permission("WRITE_CRM")
def company_auto_enrich(company_id):
    tenant=current_tenant()
    company=Company.query.filter_by(id=company_id,tenant_id=tenant.id,status="ACTIVE").first_or_404()
    if not company.website:
        company.research_status="NEEDS_WEBSITE"
        db.session.commit()
        return jsonify(error="La empresa no tiene un sitio web registrado. Primero confirme su sitio oficial.",code="MISSING_WEBSITE"),400
    data=request.get_json(silent=True) or {}
    deep=bool(data.get("deep",True))
    overwrite=bool(data.get("overwrite",False))
    try:
        from ..services.site_analyzer import analyze_website
        analysis=analyze_website(company.website,max_pages=18 if deep else 4,use_sitemap=deep,request_timeout=12 if deep else 8,status="COMPLETED" if deep else "QUICK")
        result=_merge_company_enrichment(company,analysis,overwrite=overwrite,source_label="Actualización automática de empresa existente")
        db.session.add(CompanyActivity(tenant_id=tenant.id,company_id=company.id,activity_type="DATA_UPDATE",channel="SITIO_WEB",subject="Actualización automática de ficha 360°",summary=f"Se completaron {len(result['updated'])} campos. {len(result['reviewRequired'])} dato(s) quedaron pendientes de revisión.",extra_data=result))
        _audit("AUTO_ENRICH","COMPANY",company.id,result)
        db.session.commit()
        return jsonify(ok=True,companyId=company.id,name=company.name,analysis=analysis.to_dict(),result=result)
    except Exception as exc:
        db.session.rollback()
        from ..services.site_analyzer import classify_site_error
        diagnosed=classify_site_error(company.website,exc,"actualización automática de la ficha 360°")
        return jsonify(error=diagnosed.message,errorDetails=diagnosed.to_dict(),alternatives=diagnosed.alternatives),diagnosed.status


@api_bp.get("/workspace/overview")
def workspace_overview():
    tenant = current_tenant()
    now = datetime.now(timezone.utc)
    companies = Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").all()
    opportunities = Opportunity.query.filter_by(tenant_id=tenant.id).all()
    active = [row for row in opportunities if row.status not in {"GANHO", "PERDIDO", "DESCARTADO"}]
    research = []
    for company in companies:
        completeness, missing = company_completeness(company)
        company.data_completeness_score = completeness
        age_days = None
        if company.last_enriched_at:
            stamp = company.last_enriched_at if company.last_enriched_at.tzinfo else company.last_enriched_at.replace(tzinfo=timezone.utc)
            age_days = max(0, (now - stamp).days)
        research.append({
            "companyId": company.id, "company": company.name, "sector": company.sector, "city": company.city, "website": company.website,
            "fit": company.account_fit_score, "momentum": company.momentum_score, "accessibility": company.accessibility_score,
            "completeness": completeness, "missing": missing, "staleDays": age_days,
            "priority": round((company.account_fit_score or 0) * .45 + (company.momentum_score or 0) * .35 + (100-completeness) * .20),
        })
    research.sort(key=lambda row: row["priority"], reverse=True)
    sales_ready = []
    for row in active:
        score, blockers = lead_readiness(row)
        if row.sales_ready or score >= 60:
            item = row.to_dict(); item["blockers"] = blockers; sales_ready.append(item)
    sales_ready.sort(key=lambda row: (row.get("salesReady", False), row.get("leadReadiness", 0), row.get("score", 0)), reverse=True)
    stale = [row for row in research if row["staleDays"] is None or row["staleDays"] >= 90]
    smart = {
        "hotWithoutDecisionMaker": [row.to_dict() for row in active if row.score >= 75 and not (row.contact_verified or row.project.company.contacts)][:50],
        "buyingWindow": [row.to_dict() for row in active if row.buying_window_score >= 75][:50],
        "followUpDue": [row.to_dict() for row in active if row.next_action_at and row.next_action_at <= now + timedelta(days=1)][:50],
        "proposalStalled": [row.to_dict() for row in active if row.status in {"ORCAMENTO", "NEGOCIACAO"} and row.updated_at and (now - (row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc))).days >= 5][:50],
        "staleData": stale[:50],
    }
    db.session.commit()
    return jsonify(researchQueue=research[:100], salesReady=sales_ready[:100], smartLists=smart, summary={
        "salesReady": sum(1 for row in active if row.sales_ready), "needsResearch": sum(1 for row in research if row["completeness"] < 80),
        "staleAccounts": len(stale), "withoutDecisionMaker": sum(1 for company in companies if not company.contacts),
    })


@api_bp.post("/opportunities/<int:opportunity_id>/cadence")
@require_permission("WRITE_CRM")
def opportunity_cadence(opportunity_id):
    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    replace = bool((request.get_json(silent=True) or {}).get("replace"))
    if replace:
        SalesTask.query.filter_by(opportunity_id=opportunity.id, status="PENDING").delete()
        db.session.flush()
    _create_cadence(opportunity)
    db.session.flush()
    pending = [row for row in opportunity.tasks if row.status == "PENDING"]
    opportunity.next_action_at = min((row.due_at for row in pending), default=opportunity.next_action_at)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="CADENCE", description="Cadencia comercial creada/recalculada"))
    db.session.commit()
    return jsonify(tasks=[row.to_dict() for row in pending])


@api_bp.post("/opportunities/<int:opportunity_id>/outcome")
@require_permission("WRITE_CRM")
def opportunity_outcome(opportunity_id):
    tenant = current_tenant()
    opportunity = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    data = request.get_json(silent=True) or {}
    outcome = (data.get("outcome") or "").upper()
    valid = {"RESPONDED", "NO_RESPONSE", "WRONG_CONTACT", "FUTURE_PROJECT", "QUOTE_SENT", "WON", "LOST", "POSTPONED", "NO_FIT"}
    if outcome not in valid:
        return jsonify(error="Resultado comercial inválido"), 400
    lost_reason = (data.get("lostReason") or "").upper() or None
    opportunity.outcome_code = outcome; opportunity.lost_reason = lost_reason; opportunity.last_result_at = datetime.now(timezone.utc)
    if outcome in {"RESPONDED", "QUOTE_SENT", "WON", "LOST", "NO_FIT"}: opportunity.last_contact_at = datetime.now(timezone.utc)
    status_map = {"RESPONDED":"RESPONDEU", "QUOTE_SENT":"ORCAMENTO", "WON":"GANHO", "LOST":"PERDIDO", "NO_FIT":"DESCARTADO", "POSTPONED":"MONITORAMENTO", "FUTURE_PROJECT":"MONITORAMENTO"}
    if outcome in status_map: opportunity.status = status_map[outcome]
    if opportunity.status in {"GANHO", "PERDIDO", "DESCARTADO"}: SalesTask.query.filter_by(opportunity_id=opportunity.id, status="PENDING").update({"status":"CANCELLED"})
    lead_readiness(opportunity)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="COMMERCIAL_RESULT", description=f"Resultado: {outcome}" + (f" · Motivo: {lost_reason}" if lost_reason else "")))
    db.session.commit(); return jsonify(opportunity.to_dict())


@api_bp.post("/bulk/actions")
@require_permission("WRITE_CRM")
def bulk_actions():
    tenant = current_tenant(); data = request.get_json(silent=True) or {}
    ids = [int(value) for value in (data.get("opportunityIds") or []) if str(value).isdigit()][:100]
    action = (data.get("action") or "").upper()
    rows = Opportunity.query.filter(Opportunity.tenant_id == tenant.id, Opportunity.id.in_(ids)).all() if ids else []
    if not rows: return jsonify(error="Seleccione oportunidades"), 400
    for opportunity in rows:
        if action == "CREATE_CADENCE": _create_cadence(opportunity)
        elif action == "WATCH": opportunity.status = "MONITORAMENTO"; opportunity.project.company.watch_status = "WATCH"
        elif action == "QUALIFY": opportunity.status = "QUALIFICADO"
        elif action == "ASSIGN": opportunity.owner_name = str(data.get("owner") or "Equipo comercial").strip()
        else: return jsonify(error="Acción masiva inválida"), 400
        lead_readiness(opportunity)
    db.session.commit(); return jsonify(updated=len(rows), action=action)


@api_bp.get("/health")
def api_health():
    return _health()


def _health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database="connected")
    except Exception:
        return jsonify(status="degraded", database="unavailable"), 503


@api_bp.record_once
def register_health(state):
    state.app.add_url_rule("/health", "health", _health)


@api_bp.get("/opportunities/<int:opportunity_id>/similar")
def opportunity_similar(opportunity_id):
    tenant = current_tenant()
    target = Opportunity.query.filter_by(id=opportunity_id, tenant_id=tenant.id).first_or_404()
    target_products = set(target.products or [])
    target_sector = (target.project.company.sector or "").strip().lower()
    target_type = (target.project.project_type or "").strip().lower()
    candidates = Opportunity.query.filter(
        Opportunity.tenant_id == tenant.id, Opportunity.id != target.id,
        ~Opportunity.status.in_({"DESCARTADO", "PERDIDO"})
    ).order_by(Opportunity.score.desc()).limit(250).all()
    ranked = []
    for row in candidates:
        similarity = 0
        reasons = []
        sector = (row.project.company.sector or "").strip().lower()
        if target_sector and sector == target_sector:
            similarity += 45; reasons.append("mismo sector")
        elif target_sector and sector and (target_sector in sector or sector in target_sector):
            similarity += 25; reasons.append("sector relacionado")
        project_type = (row.project.project_type or "").strip().lower()
        if target_type and project_type == target_type:
            similarity += 15; reasons.append("tipo de proyecto similar")
        overlap = target_products.intersection(set(row.products or []))
        if overlap:
            similarity += min(25, 8 + len(overlap) * 6); reasons.append("productos coincidentes")
        if target.project.department and row.project.department == target.project.department:
            similarity += 8; reasons.append("misma región")
        if target.project.city and row.project.city == target.project.city:
            similarity += 7; reasons.append("misma ciudad")
        if similarity >= 25:
            ranked.append((similarity, row, reasons))
    ranked.sort(key=lambda item: (item[0], item[1].score), reverse=True)
    return jsonify([{
        "id": row.id, "company": row.project.company.name, "sector": row.project.company.sector,
        "project": row.project.name, "score": row.score, "similarity": similarity,
        "reasons": reasons[:3], "salesReady": row.sales_ready
    } for similarity, row, reasons in ranked[:6]])
