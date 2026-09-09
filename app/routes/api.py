from datetime import datetime, timedelta, timezone
import csv
import io
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy import text, or_
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import (
    AuditLog, CollectorRun, Company, CompanyActivity, Contact, Evidence, Opportunity, OpportunityEvidence, OpportunityScore, Project, Proposal, User,
    ProspectSignal, SalesTask, ScoreFactor, Signal, Source, SourceDocument, TimelineEvent, VisitRecord, Watchlist, WebsiteAnalysis,
)
from ..services.entity_resolution import resolve_company, resolve_project
from ..services.intelligence import as_datetime, company_completeness, lead_readiness, link_evidence_and_products, record_evidence, score_opportunity
from ..tenant import current_tenant, current_user, require_permission

api_bp = Blueprint("api", __name__, url_prefix="/api")
STATUSES = {"NOVO", "QUALIFICADO", "CONTATO_REALIZADO", "RESPONDEU", "DIAGNOSTICO", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO", "PERDIDO", "MONITORAMENTO", "DESCARTADO"}
BUYING_STAGES = {"AWARENESS", "RESEARCH", "PROJECT_PLANNING", "SUPPLIER_DISCOVERY", "RFQ", "PROCUREMENT", "NEGOTIATION", "PURCHASE", "POSTPONED", "UNKNOWN"}


def _audit(action, entity_type, entity_id, details=None):
    tenant = current_tenant()
    user = current_user()
    db.session.add(AuditLog(
        tenant_id=tenant.id, user_id=user.id if user else None, action=action,
        entity_type=entity_type, entity_id=str(entity_id), details=details or {},
    ))




def _ensure_next_action(opportunity, status=None, base_time=None):
    """Keep one clear next commercial action aligned with the current stage."""
    now = base_time or datetime.now(timezone.utc)
    status = status or opportunity.status
    rules = {
        "NOVO": ("Validar empresa y contacto responsable", 1, "RESEARCH"),
        "QUALIFICADO": ("Realizar primer contacto", 1, "OUTREACH"),
        "CONTATO_REALIZADO": ("Hacer seguimiento del primer contacto", 3, "FOLLOW_UP"),
        "RESPONDEU": ("Responder y acordar diagnóstico / próximo paso", 1, "REPLY"),
        "DIAGNOSTICO": ("Completar diagnóstico y acordar visita / solución", 2, "DIAGNOSIS"),
        "VISITA": ("Preparar o registrar resultado de la visita", 1, "VISIT"),
        "ORCAMENTO": ("Hacer seguimiento de la propuesta", 4, "PROPOSAL"),
        "NEGOCIACAO": ("Actualizar negociación y siguiente decisión", 2, "NEGOTIATION"),
        "MONITORAMENTO": ("Revisar cuenta en seguimiento", 14, "FOLLOW_UP"),
    }
    if status in {"GANHO", "PERDIDO", "DESCARTADO"}:
        SalesTask.query.filter_by(opportunity_id=opportunity.id, status="PENDING").update({"status": "CANCELLED"})
        opportunity.next_action_at = None
        return None
    rule = rules.get(status)
    if not rule:
        return None
    title, days, channel = rule
    due = now + timedelta(days=days)
    # Cancel stale automatic tasks from earlier stages, preserving manually created tasks (sequence_step=0).
    SalesTask.query.filter(SalesTask.opportunity_id == opportunity.id, SalesTask.status == "PENDING", SalesTask.sequence_step < 0).update({"status": "CANCELLED"}, synchronize_session=False)
    task = SalesTask(opportunity_id=opportunity.id, title=title, channel=channel, due_at=due, status="PENDING", sequence_step=-1)
    db.session.add(task)
    opportunity.next_action_at = due
    opportunity.next_best_action = title
    return task


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



def _email_profile(email):
    value=(email or "").strip().lower()
    local=value.split("@",1)[0] if "@" in value else value
    region=None
    for token,label in (("asuncion","Asunción"),("cde","Ciudad del Este"),("ciudaddeleste","Ciudad del Este"),("este","Ciudad del Este"),("hernandarias","Hernandarias"),("encarnacion","Encarnación")):
        if token in local:
            region=label; break
    rules=[
        (("mantenimiento","mant","ingenier","tecnico","tecnica","infraestructura","proyecto"),"Área técnica / Mantenimiento / Ingeniería","TECHNICAL_INFLUENCER",88),
        (("compra","compras","procurement","abastecimiento","supply"),"Compras / Abastecimiento","BUYER",90),
        (("operacion","operaciones","logistica","logistica","deposito","expedicion"),"Operaciones / Logística","USER",84),
        (("gerencia","gerente","direccion","director","directorio","ceo","administracion"),"Gerencia / Dirección","DECISION_MAKER",82),
        (("marketing","mercadeo","comunicacion","prensa"),"Marketing / Comunicación","GATEKEEPER",82),
        (("venta","ventas","comercial","sales"),"Ventas / Comercial","GATEKEEPER",80),
        (("rrhh","recursoshumanos","talento","jobs","empleo"),"Recursos Humanos","GATEKEEPER",72),
        (("info","contacto","contact","hola","recepcion","sac","atencion"),"Correo general / Recepción","GATEKEEPER",68),
    ]
    label="Correo general"; buying="GATEKEEPER"; confidence=62
    compact=local.replace("_","").replace("-","").replace(".","")
    for keys,found_label,found_buying,found_conf in rules:
        if any(k.replace("_","").replace("-","") in compact for k in keys):
            label,buying,confidence=found_label,found_buying,found_conf; break
    if region: label=f"{label} · {region}"
    dept=_department_context(None,value)
    return {"label":label,"buyingRole":buying,"confidence":confidence,"department":dept,"region":region}


def _sync_discovered_contacts(company, analysis):
    tenant=current_tenant()
    created=[]
    existing={str(c.email or "").strip().casefold():c for c in Contact.query.filter_by(tenant_id=tenant.id,company_id=company.id).all() if c.email}
    for email in analysis.emails or []:
        key=str(email).strip().casefold()
        if not key or "@" not in key: continue
        profile=_email_profile(key)
        row=existing.get(key)
        if row:
            if not row.role: row.role=profile["label"]
            if row.buying_role in (None,"","UNKNOWN"): row.buying_role=profile["buyingRole"]
            row.confidence=max(row.confidence or 0,profile["confidence"]); row.source_url=row.source_url or analysis.url
            continue
        row=Contact(tenant_id=tenant.id,company_id=company.id,name=profile["label"],role=profile["label"],buying_role=profile["buyingRole"],email=key,source_url=analysis.url,confidence=profile["confidence"],status="ACTIVE")
        db.session.add(row); existing[key]=row; created.append(key)
    return created

def _company_message(company, contact=None, channel="EMAIL", opportunity=None):
    brand = current_tenant().settings or {}
    is_pt = brand.get("language") == "pt-BR"
    brand_name = brand.get("brand_short") or brand.get("brand_name") or current_tenant().name
    company_name = company.name
    contact_name = contact.name.strip() if contact and contact.name else ""
    email = (contact.email if contact else None) or company.email_business or company.email or ""
    whatsapp = (contact.whatsapp if contact else None) or (contact.phone if contact else None) or company.whatsapp or company.phone_business or company.phone or ""
    dept = _department_context(contact, email)
    sector = company.sector or ("sua operação" if is_pt else "su operación")
    products = (opportunity.products if opportunity else []) or []
    product_phrase = ", ".join(products[:3]) if products else ("soluções de acessos automáticos e industriais" if is_pt else "soluciones de accesos automáticos e industriales")
    if is_pt:
        greeting = f"Prezado(a) {contact_name}," if contact_name else f"Prezada equipe da {company_name},"
        intro = f"Meu nome é David Granja e represento a {brand_name}, empresa especializada em soluções de acessos automáticos e industriais."
        context_map = {
            "MARKETING":"Entendo que este contato corresponde à área de Marketing ou Comunicação. Gostaria de apresentar brevemente nossa empresa e solicitar sua orientação para chegar ao responsável técnico adequado.",
            "COMPRAS":"Gostaríamos de nos apresentar como fornecedor e entender o canal correto para futuras cotações, homologações ou processos de compra relacionados a acessos industriais.",
            "TECNICO":f"Pelo perfil da operação, vemos possíveis aplicações para {product_phrase}, além de instalação, manutenção preventiva, corretiva e modernização de equipamentos existentes.",
            "OPERACIONES":f"Em operações como a da {company_name}, os acessos podem influenciar o fluxo de mercadorias, segurança, carga e descarga e continuidade operacional.",
            "DIRECCION":"Gostaríamos de apresentar nossa capacidade e avaliar aderência a projetos atuais ou futuros de infraestrutura, expansão, logística ou manutenção.",
            "GENERAL":f"Em empresas do segmento {sector}, os acessos podem influenciar a segurança, o fluxo de pessoas e mercadorias e a continuidade da operação.",
        }
        ask_map={
            "MARKETING":"Poderia me indicar o nome e o contato direto do responsável por Manutenção, Infraestrutura, Operações, Logística, Engenharia ou Projetos?",
            "COMPRAS":"Poderia me indicar quem responde por Compras/Abastecimento e quem faz a validação técnica desse tipo de solução?",
            "TECNICO":"Seria possível coordenarmos uma breve conversa para entender a operação atual, prioridades e eventuais projetos em que possamos contribuir?",
            "OPERACIONES":"Poderia me indicar o responsável por Operações, Logística, Manutenção, Infraestrutura ou Projetos?",
            "DIRECCION":"Com quem de Manutenção, Engenharia, Infraestrutura, Operações, Logística ou Projetos seria adequado seguir esta conversa?",
            "GENERAL":"Poderiam me indicar o nome e o contato direto do responsável por Manutenção, Infraestrutura, Operações, Logística, Engenharia ou Projetos?",
        }
        body=f"{greeting}\n\nÉ um prazer falar com vocês.\n\n{intro}\n\nGostaríamos de apresentar nossa empresa e nos colocar à disposição da {company_name}.\n\n{context_map[dept]}\n\n{ask_map[dept]}\n\nDesde já, agradeço pela orientação.\n\nAtenciosamente,\nDavid Granja\n{brand_name}"
        subject=brand.get("subject_first_contact") or f"{brand_name} | Primeiro Contato"
        if channel.upper()=="WHATSAPP": body=f"Olá{(' ' + contact_name) if contact_name else ''}, tudo bem? Sou David Granja, da {brand_name}. {context_map[dept]} {ask_map[dept]} Obrigado!"
        elif channel.upper()=="CALL": body=f"Objetivo da ligação: apresentar-se como David Granja da {brand_name}; contextualizar {company_name}; {ask_map[dept]} Registrar nome, cargo, contato direto, necessidade, prazo e próximo passo."
    else:
        greeting = f"Estimado/a {contact_name}," if contact_name else f"Estimado equipo de {company_name},"
        intro = f"Mi nombre es David Granja y represento a {brand_name}, empresa especializada en soluciones de accesos automáticos e industriales, con fábrica ubicada en el km 13 de Ciudad del Este."
        context_map={
            "MARKETING":"Entiendo que este contacto corresponde al área de Marketing o Comunicación. Mi intención es presentar brevemente nuestra empresa y solicitar su orientación para llegar al responsable técnico adecuado.",
            "COMPRAS":"Nos gustaría quedar registrados como proveedor y conocer el canal correcto para futuras cotizaciones, homologaciones o procesos de compra relacionados con accesos industriales.",
            "TECNICO":f"Por el perfil de su operación, vemos posibles aplicaciones para {product_phrase}, además de instalación, mantenimiento preventivo, correctivo y modernización de equipos existentes.",
            "OPERACIONES":f"En operaciones como la de {company_name}, los accesos pueden influir directamente en el flujo de mercaderías, la seguridad, los tiempos de carga y descarga y la continuidad operacional.",
            "DIRECCION":"Nos gustaría presentar nuestra capacidad industrial y evaluar si existe encaje para proyectos actuales o futuros de infraestructura, expansión, logística o mantenimiento.",
            "GENERAL":f"En empresas del segmento {sector}, los accesos pueden influir en la seguridad, el flujo de personas y mercaderías y la continuidad de la operación.",
        }
        ask_map={
            "MARKETING":"¿Podría indicarme el nombre y el correo directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos?",
            "COMPRAS":"¿Podría indicarme quién gestiona Compras o Abastecimiento y quién valida técnicamente este tipo de solución?",
            "TECNICO":"¿Sería posible coordinar una conversación breve para conocer la operación actual, prioridades y eventuales proyectos en los que podamos aportar?",
            "OPERACIONES":"¿Podría indicarme quién es el responsable de Operaciones, Logística, Mantenimiento, Infraestructura o Proyectos?",
            "DIRECCION":"¿Con quién de Mantenimiento, Ingeniería, Infraestructura, Operaciones, Logística o Proyectos sería conveniente continuar esta conversación?",
            "GENERAL":"¿Podrían indicarme el nombre y el correo directo del responsable de Mantenimiento, Infraestructura, Operaciones, Logística, Ingeniería o Proyectos?",
        }
        body=f"{greeting}\n\nEs un gusto saludarle.\n\n{intro}\n\nNos gustaría presentar nuestra empresa y ponernos a disposición de {company_name}.\n\n{context_map[dept]}\n\nAdjunto nuestra carta de presentación institucional y catálogo comercial.\n\n{ask_map[dept]}\n\nDesde ya, agradezco mucho su orientación.\n\nSaludos cordiales,\nDavid Granja\n{brand_name}"
        subject=brand.get("subject_first_contact") or "Puertas Brasil Paraguay | Primer Contacto"
        if channel.upper()=="WHATSAPP": body=f"Hola{(' ' + contact_name) if contact_name else ''}, ¿cómo está? Soy David Granja, de {brand_name}. {context_map[dept]} {ask_map[dept]} Muchas gracias."
        elif channel.upper()=="CALL": body=f"Objetivo de la llamada: presentarse como David Granja de {brand_name}; contextualizar {company_name}; {ask_map[dept]} Registrar nombre, cargo, contacto directo, necesidad, plazo y próximo paso."
    destination = whatsapp if channel.upper() == "WHATSAPP" else (email if channel.upper() == "EMAIL" else (whatsapp or email))
    return {"subject": subject, "body": body, "department": dept, "recipient": destination, "recipientLabel": contact_name or company_name, "channel": channel.upper()}



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
    result["contactsCreated"]=_sync_discovered_contacts(company, analysis)
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
        city=data.get("city"), department=data.get("department") or data.get("region"), country=data.get("country") or (tenant.settings or {}).get("default_country", "Paraguay"),
        phone=data.get("phone"), phone_business=data.get("phone"), whatsapp=data.get("whatsapp") or data.get("phone"),
        email=data.get("email"), email_business=data.get("email"), linkedin_url=data.get("linkedin"),
        registration_id=data.get("registrationId"), description=data.get("companyDescription"),
    )
    db.session.flush()
    project = resolve_project(
        tenant.id, company, data.get("project") or data.get("sourceTitle") or "Proyecto por validar",
        city=data.get("city") or "Por validar", department=data.get("department") or data.get("region") or "Por validar",
        country=data.get("country") or (tenant.settings or {}).get("default_country", "Paraguay"), project_type=data.get("projectType") or data.get("event") or "UNKNOWN",
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
        "evidence": f"Empresa identificada por fuente pública en {data.get('city') or (tenant.settings or {}).get('default_country', 'Paraguay')}.",
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
    previous_status = opportunity.status
    if status is not None:
        opportunity.status = status
        changes.append(f"Estado actualizado a {status}")
        if status in {"RESPONDEU", "GANHO", "PERDIDO", "DESCARTADO"}:
            SalesTask.query.filter_by(opportunity_id=opportunity.id, status="PENDING").update({"status": "CANCELLED"})

        # Mantiene el historial comercial sincronizado con el avance manual del CRM.
        # Antes, cambiar el estado solo modificaba Opportunity.status y el reporte
        # seguía mostrando 0 respuestas/visitas. Registramos el evento una sola vez
        # cuando realmente hay transición de etapa.
        if status != previous_status:
            _ensure_next_action(opportunity, status=status)
            status_activity = {
                "RESPONDEU": ("REPLY", "Respuesta registrada desde el CRM"),
                "VISITA": ("VISIT_SCHEDULED", "Visita marcada desde el CRM"),
                "ORCAMENTO": ("PROPOSAL_SENT", "Propuesta/presupuesto registrado desde el CRM"),
            }.get(status)
            if status_activity:
                activity_type, subject = status_activity
                company_id = opportunity.project.company.id
                already_exists = CompanyActivity.query.filter_by(
                    tenant_id=tenant.id, opportunity_id=opportunity.id, activity_type=activity_type
                ).first()
                if not already_exists:
                    db.session.add(CompanyActivity(
                        tenant_id=tenant.id,
                        company_id=company_id,
                        opportunity_id=opportunity.id,
                        activity_type=activity_type,
                        channel="CRM",
                        direction="INBOUND" if activity_type == "REPLY" else "OUTBOUND",
                        subject=subject,
                        summary=f"Etapa comercial actualizada a {status}.",
                        created_by=(current_user().name if current_user() else "Equipo comercial"),
                    ))
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
    # Backfill para empresas calificadas antes de V13: transforma todos los correos del análisis original en destinatarios del CRM.
    if opportunities:
        analysis = WebsiteAnalysis.query.filter(WebsiteAnalysis.tenant_id==tenant.id, WebsiteAnalysis.opportunity_id.in_([o.id for o in opportunities])).order_by(WebsiteAnalysis.created_at.desc()).first()
        if analysis and analysis.emails:
            created=_sync_discovered_contacts(company,analysis)
            if created:
                db.session.commit()
                contacts = Contact.query.filter_by(tenant_id=tenant.id, company_id=company.id, status="ACTIVE").order_by(Contact.influence_score.desc()).all()
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
            "discoveredEmails": sorted({x for x in ([company.email_business, company.email] + [c.email for c in contacts]) if x}),
            "rucSource": next((x for x in (company.data_sources or []) if isinstance(x, dict) and x.get("type") in {"DNIT_RUC","RUC_OFFICIAL"}), None),
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
    allowed={"CALL","EMAIL_SENT","WHATSAPP_SENT","VISIT","VISIT_SCHEDULED","MEETING","PROPOSAL_SENT","FOLLOW_UP","NOTE","REPLY","DATA_UPDATE"}
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
        elif activity_type in {"VISIT","VISIT_SCHEDULED","MEETING"} and op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="VISITA"
        elif activity_type == "PROPOSAL_SENT" and op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="ORCAMENTO"
        if next_at:
            op.next_action_at=next_at
        else:
            _ensure_next_action(op, status=op.status, base_time=occurred)
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
@require_permission("WRITE_CRM")
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
    subject = brand.get("subject_first_contact") or ("Tech Doors | Primeiro Contato" if brand.get("language") == "pt-BR" else "Puertas Brasil Paraguay | Primer Contacto")
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
    discovered_contacts = _sync_discovered_contacts(opportunity.project.company, analysis)
    opportunity.project.company.data_completeness_score = company_completeness(opportunity.project.company)[0]
    lead_readiness(opportunity)
    db.session.add(TimelineEvent(
        opportunity=opportunity, event_type="WEBSITE_QUALIFICATION",
        description="Empresa calificada manualmente; mensajes comerciales personalizados generados",
    ))
    db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=opportunity.project.company.id, opportunity_id=opportunity.id, activity_type="DATA_UPDATE", channel="SITIO_WEB", subject="Empresa calificada desde su sitio", summary=f"Análisis web completado con puntuación {analysis.potential_score}/100 y {analysis.pages_analyzed} páginas analizadas. {len(discovered_contacts)} correo(s) convertidos en destinatarios."))
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
@require_permission("WRITE_CRM")
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


def _valid_image_upload(upload, extension):
    head = upload.stream.read(16)
    upload.stream.seek(0)
    signatures = {
        ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
    }
    if extension == ".webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in signatures.get(extension, ()))


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
        if extension not in {".jpg", ".jpeg", ".png", ".webp"} or not _valid_image_upload(uploaded, extension):
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
    tenant = current_tenant()
    safe_name = secure_filename(filename)
    if safe_name != filename or not safe_name:
        return jsonify(error="Archivo inválido"), 404
    visits = VisitRecord.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id).all()
    if not any(safe_name in (visit.photos or []) for visit in visits):
        return jsonify(error="Archivo no encontrado"), 404
    return send_from_directory(Path(current_app.config["DATA_DIR"]) / "uploads", safe_name)


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



def _report_period():
    """Resolve a report window from query params. Defaults to all activity so far."""
    now = datetime.now(timezone.utc)
    preset = (request.args.get("period") or "all").strip().lower()
    start = end = None
    if preset == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif preset == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif preset == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif preset == "custom":
        try:
            raw_start = (request.args.get("start") or "").strip()
            raw_end = (request.args.get("end") or "").strip()
            start = datetime.fromisoformat(raw_start).replace(tzinfo=timezone.utc) if raw_start else None
            end = (datetime.fromisoformat(raw_end).replace(tzinfo=timezone.utc) + timedelta(days=1)) if raw_end else now
        except ValueError:
            start, end = None, now
    return preset, start, end or now


def _apply_period(query, column, start, end):
    if start is not None:
        query = query.filter(column >= start)
    if end is not None:
        query = query.filter(column < end)
    return query


def _analysis_identity(analysis):
    """Stable company identity for report counts, even before CRM classification."""
    if analysis.opportunity and analysis.opportunity.project and analysis.opportunity.project.company:
        return f"company:{analysis.opportunity.project.company.id}"
    domain = _website_domain(analysis.url)
    if domain:
        return f"domain:{domain}"
    from ..services.entity_resolution import normalize_name
    name = normalize_name(analysis.company_name or "")
    return f"name:{name}" if name else f"analysis:{analysis.id}"


def _build_activity_report():
    tenant = current_tenant()
    user_filter = (request.args.get("user") or "").strip()
    preset, start, end = _report_period()

    analyses_q = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id)
    analyses_q = _apply_period(analyses_q, WebsiteAnalysis.created_at, start, end)
    analyses = analyses_q.all()

    activities_q = CompanyActivity.query.filter_by(tenant_id=tenant.id)
    activities_q = _apply_period(activities_q, CompanyActivity.occurred_at, start, end)
    if user_filter:
        activities_q = activities_q.filter(CompanyActivity.created_by == user_filter)
    activities = activities_q.order_by(CompanyActivity.occurred_at.desc()).all()

    opportunities_q = Opportunity.query.filter_by(tenant_id=tenant.id)
    opportunities_q = _apply_period(opportunities_q, Opportunity.discovered_at, start, end)
    opportunities = opportunities_q.all()

    proposals_q = Proposal.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id)
    proposals_q = _apply_period(proposals_q, Proposal.created_at, start, end)
    proposals = proposals_q.all()

    # Tareas son trabajo pendiente, no empresas. Se calculan aparte y nunca
    # alimentan KPIs de cantidad de empresas.
    tasks_q = SalesTask.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id)
    if user_filter:
        tasks_q = tasks_q.filter(Opportunity.owner_name == user_filter)
    pending_tasks = tasks_q.filter(SalesTask.status == "PENDING").count()
    overdue_tasks = tasks_q.filter(SalesTask.status == "PENDING", SalesTask.due_at < datetime.now(timezone.utc)).count()

    # Empresas únicas analizadas / clasificadas. Reanalizar un sitio no aumenta
    # la cantidad de empresas del informe.
    latest_analysis = {}
    for analysis in sorted(analyses, key=lambda row: row.created_at or datetime.min.replace(tzinfo=timezone.utc)):
        latest_analysis[_analysis_identity(analysis)] = analysis
    analysed_keys = set(latest_analysis)
    classified_keys = {key for key, analysis in latest_analysis.items() if analysis.decision == "QUALIFIED"}
    disqualified_keys = {key for key, analysis in latest_analysis.items() if analysis.decision == "DISQUALIFIED"}

    commercial_types = {"EMAIL_SENT", "WHATSAPP_SENT", "CALL", "REPLY", "MEETING", "VISIT_SCHEDULED", "VISIT", "PROPOSAL_SENT"}
    commercial_activities = [a for a in activities if a.activity_type in commercial_types]
    type_counts = {}
    for a in commercial_activities:
        type_counts[a.activity_type] = type_counts.get(a.activity_type, 0) + 1

    email_count = type_counts.get("EMAIL_SENT", 0)
    whatsapp_count = type_counts.get("WHATSAPP_SENT", 0)
    calls = type_counts.get("CALL", 0)
    meetings = type_counts.get("MEETING", 0)

    contacted_company_ids = {a.company_id for a in commercial_activities if a.activity_type in {"EMAIL_SENT", "WHATSAPP_SENT", "CALL"}}
    reply_company_ids = {a.company_id for a in commercial_activities if a.activity_type == "REPLY"}
    visit_company_ids = {a.company_id for a in commercial_activities if a.activity_type in {"VISIT", "VISIT_SCHEDULED"}}
    completed_visit_company_ids = {a.company_id for a in commercial_activities if a.activity_type == "VISIT"}
    proposal_company_ids = {a.company_id for a in commercial_activities if a.activity_type == "PROPOSAL_SENT"}

    latest_opportunity_by_company = {}
    all_tenant_opps = Opportunity.query.filter_by(tenant_id=tenant.id).order_by(Opportunity.updated_at.desc()).all()
    for o in all_tenant_opps:
        cid = o.project.company_id
        latest_opportunity_by_company.setdefault(cid, o)

    # Backward compatibility with stages saved before event tracking existed.
    for o in opportunities:
        cid = o.project.company_id
        if o.status in {"CONTATO_REALIZADO", "RESPONDEU", "DIAGNOSTICO", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO", "PERDIDO"}:
            contacted_company_ids.add(cid)
        if o.status in {"RESPONDEU", "DIAGNOSTICO", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO"}:
            reply_company_ids.add(cid)
        if o.status == "VISITA":
            visit_company_ids.add(cid)
        if o.status in {"ORCAMENTO", "NEGOCIACAO", "GANHO"}:
            proposal_company_ids.add(cid)

    visits_q = VisitRecord.query.join(Opportunity).filter(Opportunity.tenant_id == tenant.id)
    visits_q = _apply_period(visits_q, VisitRecord.visited_at, start, end)
    if user_filter:
        visits_q = visits_q.filter(Opportunity.owner_name == user_filter)
    for visit in visits_q.all():
        cid = visit.opportunity.project.company_id
        visit_company_ids.add(cid)
        completed_visit_company_ids.add(cid)

    for proposal in proposals:
        proposal_company_ids.add(proposal.opportunity.project.company_id)

    wins = {o.project.company_id for o in opportunities if o.status == "GANHO"}
    losses = {o.project.company_id for o in opportunities if o.status == "PERDIDO"}

    touched_company_ids = set(contacted_company_ids) | set(reply_company_ids) | set(visit_company_ids) | set(proposal_company_ids)
    touched_company_ids |= {a.company_id for a in commercial_activities}
    touched_company_ids |= {o.project.company_id for o in opportunities}
    contacts_identified = Contact.query.filter(Contact.tenant_id == tenant.id, Contact.company_id.in_(touched_company_ids)).count() if touched_company_ids else 0

    metrics = {
        "analysed": len(analysed_keys),
        "analysesPerformed": len(analyses),
        "classified": len(classified_keys),
        "disqualified": len(disqualified_keys),
        "crmCompanies": Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").count(),
        "contactedCompanies": len(contacted_company_ids),
        "emails": email_count, "whatsapps": whatsapp_count, "calls": calls,
        "replies": len(reply_company_ids), "meetings": meetings,
        "visits": len(visit_company_ids), "visitsScheduled": len(visit_company_ids), "visitsCompleted": len(completed_visit_company_ids),
        "proposals": len(proposal_company_ids), "opportunities": len({o.project.company_id for o in opportunities}),
        "wins": len(wins), "losses": len(losses), "contacts": contacts_identified,
        "pendingFollowups": pending_tasks, "overdueFollowups": overdue_tasks,
    }

    summary = (
        f"Durante el período se trabajaron {metrics['analysed']} empresas únicas ({metrics['analysesPerformed']} análisis realizados); "
        f"{metrics['classified']} fueron clasificadas y {metrics['disqualified']} descartadas. "
        f"Se contactaron {metrics['contactedCompanies']} empresas mediante {metrics['emails']} correos, "
        f"{metrics['whatsapps']} WhatsApps y {metrics['calls']} llamadas. "
        f"{metrics['replies']} empresas respondieron, se marcaron {metrics['visitsScheduled']} visitas "
        f"({metrics['visitsCompleted']} realizadas) y {metrics['proposals']} empresas llegaron a propuesta. "
        f"Las tareas se muestran aparte: {metrics['pendingFollowups']} pendientes y {metrics['overdueFollowups']} vencidas."
    )

    # One consolidated row per company: the executive report should show the
    # commercial state, not every internal click or website enrichment step.
    activities_by_company = {}
    for a in commercial_activities:
        activities_by_company.setdefault(a.company_id, []).append(a)
    for cid in touched_company_ids:
        activities_by_company.setdefault(cid, [])

    pending_tasks_rows = SalesTask.query.join(Opportunity).filter(
        Opportunity.tenant_id == tenant.id, SalesTask.status == "PENDING"
    ).order_by(SalesTask.due_at.asc()).all()
    next_task_by_company = {}
    for task in pending_tasks_rows:
        cid = task.opportunity.project.company_id
        next_task_by_company.setdefault(cid, task)

    companies_rows = []
    for cid, company_activities in activities_by_company.items():
        company = db.session.get(Company, cid)
        if not company or company.status != "ACTIVE":
            continue
        latest = company_activities[0] if company_activities else None
        opp = latest_opportunity_by_company.get(cid)
        channels = []
        for a in company_activities:
            label = a.channel or a.activity_type
            if label and label not in channels:
                channels.append(label)
        next_task = next_task_by_company.get(cid)
        next_action = ""
        next_action_at = None
        for a in company_activities:
            if a.next_action:
                next_action = a.next_action
                next_action_at = a.next_action_at.isoformat() if a.next_action_at else None
                break
        if not next_action and next_task:
            next_action = next_task.title
            next_action_at = next_task.due_at.isoformat() if next_task.due_at else None
        companies_rows.append({
            "companyId": cid,
            "company": company.name,
            "sector": company.sector or "—",
            "city": company.city or company.department or "—",
            "status": opp.status if opp else "CRM",
            "lastActivity": latest.activity_type if latest else "—",
            "lastContactAt": latest.occurred_at.isoformat() if latest and latest.occurred_at else None,
            "channels": channels,
            "replied": cid in reply_company_ids,
            "visitScheduled": cid in visit_company_ids,
            "visitCompleted": cid in completed_visit_company_ids,
            "proposal": cid in proposal_company_ids,
            "nextAction": next_action,
            "nextActionAt": next_action_at,
            "owner": opp.owner_name if opp else (latest.created_by if latest else "Equipo comercial"),
        })
    companies_rows.sort(key=lambda row: row.get("lastContactAt") or "", reverse=True)

    rows=[]
    for a in commercial_activities[:300]:
        rows.append({
            "date": a.occurred_at.isoformat() if a.occurred_at else None,
            "company": a.company.name if a.company else "Empresa",
            "type": a.activity_type, "channel": a.channel, "subject": a.subject or "",
            "summary": a.summary or "", "outcome": a.outcome or "", "nextAction": a.next_action or "",
            "createdBy": a.created_by or "Equipo comercial",
        })
    users = sorted({a.created_by for a in CompanyActivity.query.filter_by(tenant_id=tenant.id).all() if a.created_by})
    return {
        "period": preset,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "user": user_filter,
        "metrics": metrics,
        "summary": summary,
        "companies": companies_rows,
        "activities": rows,
        "users": users,
    }


@api_bp.get("/reports/activity")
@require_permission("READ_INTELLIGENCE")
def report_activity():
    return jsonify(_build_activity_report())


@api_bp.get("/reports/activity.csv")
@require_permission("READ_INTELLIGENCE")
def report_activity_csv():
    data = _build_activity_report()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Empresa", "Sector", "Ciudad", "Estado CRM", "Último contacto", "Canales", "Respondió", "Visita marcada", "Visita realizada", "Propuesta", "Próxima acción", "Responsable"])
    for row in data["companies"]:
        writer.writerow([
            row["company"], row["sector"], row["city"], row["status"], row["lastContactAt"] or "",
            " / ".join(row["channels"]), "Sí" if row["replied"] else "No",
            "Sí" if row["visitScheduled"] else "No", "Sí" if row["visitCompleted"] else "No",
            "Sí" if row["proposal"] else "No", row["nextAction"], row["owner"],
        ])
    stream = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    stream.seek(0)
    return send_file(stream, mimetype="text/csv; charset=utf-8", as_attachment=True, download_name="Informe-empresas-comercial.csv")


@api_bp.get("/reports/activity.pdf")
@require_permission("READ_INTELLIGENCE")
def report_activity_pdf():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether

    data = _build_activity_report()
    tenant = current_tenant()
    user = current_user()
    brand = tenant.settings or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=17*mm, bottomMargin=17*mm)
    styles = getSampleStyleSheet()
    green = colors.HexColor("#075C43")
    dark = colors.HexColor("#15382D")
    muted = colors.HexColor("#667D74")
    yellow = colors.HexColor("#F2C94C")
    light = colors.HexColor("#F2F7F5")
    line = colors.HexColor("#D8E7E1")
    styles.add(ParagraphStyle(name="PBTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=25, textColor=dark, alignment=TA_LEFT, spaceAfter=4))
    styles.add(ParagraphStyle(name="PBSub", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=muted, spaceAfter=10))
    styles.add(ParagraphStyle(name="PBH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=green, spaceBefore=8, spaceAfter=7))
    styles.add(ParagraphStyle(name="PBBody", parent=styles["BodyText"], fontSize=9, leading=13, textColor=dark))
    styles.add(ParagraphStyle(name="PBSmall", parent=styles["BodyText"], fontSize=7.7, leading=10, textColor=dark))

    story=[]
    logo_path = Path(current_app.root_path) / "static" / brand.get("logo_file", "puertas-brasil-logo-oficial.jpg")
    header_cells=[]
    if logo_path.exists():
        header_cells.append(Image(str(logo_path), width=46*mm, height=18*mm, kind="proportional"))
    else:
        header_cells.append(Paragraph(f"<b>{brand.get('brand_name', tenant.name)}</b>", styles["PBH2"]))
    header_cells.append(Paragraph(f"<b>RADAR COMERCIAL</b><br/><font color='#667D74'>{'Inteligência industrial para prospecção' if brand.get('language') == 'pt-BR' else 'Inteligencia industrial para prospección'}</font>", styles["PBBody"]))
    header=Table([header_cells], colWidths=[80*mm, 95*mm])
    header.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEBELOW",(0,0),(-1,-1),1,green),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
    story += [header, Spacer(1, 7*mm), Paragraph("Informe de actividad comercial", styles["PBTitle"])]
    start_label = data['start'][:10] if data['start'] else "Inicio de la operación"
    end_label = data['end'][:10] if data['end'] else datetime.now(timezone.utc).date().isoformat()
    responsible = data['user'] or (user.name if user else "Equipo comercial")
    story.append(Paragraph(f"Período: <b>{start_label}</b> a <b>{end_label}</b> &nbsp;&nbsp;|&nbsp;&nbsp; Responsable/filtro: <b>{responsible}</b>", styles["PBSub"]))
    story.append(Paragraph(data["summary"], styles["PBBody"]))
    story.append(Spacer(1, 5*mm))

    m=data["metrics"]
    cards=[
        ("Empresas únicas analizadas",m["analysed"]),("Clasificadas",m["classified"]),("Empresas contactadas",m["contactedCompanies"]),("Empresas que respondieron",m["replies"]),
        ("Visitas marcadas",m["visitsScheduled"]),("Visitas realizadas",m["visitsCompleted"]),("Empresas con propuesta",m["proposals"]),("Ganadas",m["wins"]),
    ]
    card_rows=[]
    for i in range(0,len(cards),4):
        row=[]
        for label,value in cards[i:i+4]:
            row.append(Paragraph(f"<font size='16'><b>{value}</b></font><br/><font color='#667D74' size='7'>{label.upper()}</font>", styles["PBBody"]))
        card_rows.append(row)
    table=Table(card_rows, colWidths=[43.5*mm]*4, rowHeights=[21*mm]*len(card_rows), hAlign='LEFT')
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),light),("BOX",(0,0),(-1,-1),0.5,line),("INNERGRID",(0,0),(-1,-1),0.5,colors.white),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),7)]))
    task_note=Paragraph(
        f"<b>Actividad:</b> {m['emails']} correos · {m['whatsapps']} WhatsApps · {m['calls']} llamadas &nbsp;&nbsp; "
        f"<b>Tareas:</b> {m['pendingFollowups']} pendientes · {m['overdueFollowups']} vencidas. "
        f"Las tareas no se contabilizan como empresas.", styles["PBSub"]
    )
    story += [table, Spacer(1, 3*mm), task_note, Spacer(1, 4*mm), Paragraph("Empresas trabajadas", styles["PBH2"])]

    rows=[["Empresa","Estado","Último contacto","Respuesta","Visita","Propuesta","Próxima acción"]]
    for row in data["companies"][:160]:
        last=(row["lastContactAt"] or "")[:10] or "—"
        visit="Realizada" if row["visitCompleted"] else ("Marcada" if row["visitScheduled"] else "—")
        next_action=row["nextAction"] or "—"
        if len(next_action)>55: next_action=next_action[:52]+"..."
        rows.append([
            Paragraph(row["company"],styles["PBSmall"]), Paragraph(row["status"],styles["PBSmall"]),
            Paragraph(last,styles["PBSmall"]), Paragraph("Sí" if row["replied"] else "—",styles["PBSmall"]),
            Paragraph(visit,styles["PBSmall"]), Paragraph("Sí" if row["proposal"] else "—",styles["PBSmall"]),
            Paragraph(next_action,styles["PBSmall"]),
        ])
    act=Table(rows, repeatRows=1, colWidths=[43*mm,22*mm,24*mm,17*mm,20*mm,17*mm,32*mm], hAlign='LEFT')
    act.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),green),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),6.7),("GRID",(0,0),(-1,-1),0.35,line),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,light]),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(act)
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph((f"Este relatório foi gerado por {brand.get('brand_name', tenant.name)} - Radar Comercial. Os dados refletem as atividades registradas no período selecionado." if brand.get("language") == "pt-BR" else f"Este informe fue generado por {brand.get('brand_name', tenant.name)} - Radar Comercial. Los datos reflejan las actividades registradas en el sistema durante el período seleccionado."), styles["PBSub"]))

    def footer(canvas, doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(line); canvas.line(15*mm, 12*mm, width-15*mm, 12*mm)
        canvas.setFillColor(muted); canvas.setFont("Helvetica", 7.5)
        footer_text = " · ".join(filter(None,[brand.get("sales_phone"),brand.get("sales_email"),brand.get("website")]))
        canvas.drawString(15*mm, 7.5*mm, footer_text[:110])
        canvas.drawRightString(width-15*mm, 7.5*mm, f"Página {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=("Relatorio-Comercial-Tech-Doors.pdf" if brand.get("language") == "pt-BR" else "Informe-Comercial-Puertas-Brasil.pdf"))

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


@api_bp.post("/companies/<int:company_id>/archive")
@require_permission("WRITE_CRM")
def company_archive(company_id):
    tenant=current_tenant()
    company=Company.query.filter_by(id=company_id,tenant_id=tenant.id,status="ACTIVE").first_or_404()
    company.status="ARCHIVED"; company.deleted_at=datetime.now(timezone.utc)
    for op in Opportunity.query.join(Project).filter(Project.company_id==company.id,Opportunity.tenant_id==tenant.id).all():
        if op.status not in {"GANHO","PERDIDO","DESCARTADO"}: op.status="DESCARTADO"
    _audit("ARCHIVE","COMPANY",company.id,{"name":company.name})
    db.session.commit()
    return jsonify(ok=True,companyId=company.id,status=company.status)


@api_bp.delete("/companies/<int:company_id>")
@require_permission("MANAGE_USERS")
def company_delete(company_id):
    tenant=current_tenant()
    company=Company.query.filter_by(id=company_id,tenant_id=tenant.id).first_or_404()
    name=company.name; cid=company.id
    _audit("DELETE","COMPANY",cid,{"name":name})
    # Delete dependent opportunities/projects using ORM cascades. Activities and contacts cascade with Company.
    db.session.delete(company); db.session.commit()
    return jsonify(ok=True,companyId=cid,name=name)


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
    # Evita duplicar personas ya registradas en la misma empresa. Email y WhatsApp
    # son claves fuertes; nombre+cargo sirve como última coincidencia segura.
    clean_email = str(data.get("email") or "").strip().casefold()
    clean_phone = "".join(ch for ch in str(data.get("whatsapp") or data.get("phone") or "") if ch.isdigit())
    clean_name = str(data.get("name") or "").strip()
    clean_role = str(data.get("role") or "").strip()
    existing_contacts = Contact.query.filter_by(tenant_id=tenant.id, company_id=company.id, status="ACTIVE").all()
    existing = None
    for row in existing_contacts:
        row_email = str(row.email or "").strip().casefold()
        row_phone = "".join(ch for ch in str(row.whatsapp or row.phone or "") if ch.isdigit())
        same_name = row.name.strip().casefold() == clean_name.casefold() if row.name and clean_name else False
        same_role = str(row.role or "").strip().casefold() == clean_role.casefold() if clean_role else True
        if (clean_email and row_email == clean_email) or (clean_phone and row_phone == clean_phone) or (same_name and same_role):
            existing = row
            break
    if existing:
        changed=[]
        for attr,key in (("role","role"),("email","email"),("phone","phone"),("whatsapp","whatsapp"),("linkedin_url","linkedin")):
            value=str(data.get(key) or "").strip()
            if value and not getattr(existing,attr):
                setattr(existing,attr,value); changed.append(key)
        if changed:
            existing.verified_at=datetime.now(timezone.utc)
            db.session.add(CompanyActivity(tenant_id=tenant.id, company_id=company.id, contact_id=existing.id, activity_type="DATA_UPDATE", channel="CRM", subject="Contacto existente completado", summary=f"Se completaron datos de {existing.name}: {', '.join(changed)}", created_by=(current_user().name if current_user() else "Equipo comercial")))
            db.session.commit()
        return jsonify(id=existing.id, companyId=company.id, name=existing.name, role=existing.role, buyingRole=existing.buying_role, email=existing.email, phone=existing.phone, whatsapp=existing.whatsapp, confidence=existing.confidence, duplicatePrevented=True, changed=changed), 200
    contact = Contact(
        tenant_id=tenant.id, company_id=company.id, name=clean_name, role=data.get("role"),
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
    return jsonify(
        id=contact.id, companyId=company.id, name=contact.name, role=contact.role,
        buyingRole=contact.buying_role, email=contact.email, phone=contact.phone,
        whatsapp=contact.whatsapp, confidence=contact.confidence
    ), 201




@api_bp.patch("/companies/<int:company_id>/contacts/<int:contact_id>")
@require_permission("WRITE_CRM")
def company_contact_update(company_id, contact_id):
    tenant = current_tenant()
    company = Company.query.filter_by(id=company_id, tenant_id=tenant.id).first_or_404()
    contact = Contact.query.filter_by(id=contact_id, tenant_id=tenant.id, company_id=company.id, status="ACTIVE").first_or_404()
    data = request.get_json(silent=True) or {}
    fields = {
        "name": "name", "role": "role", "buyingRole": "buying_role", "email": "email",
        "phone": "phone", "whatsapp": "whatsapp", "linkedin": "linkedin_url",
        "influence": "influence_score", "confidence": "confidence",
    }
    changed=[]
    for key, attr in fields.items():
        if key not in data:
            continue
        value=data.get(key)
        if key in {"influence", "confidence"} and value not in (None, ""):
            try:
                value=max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return jsonify(error=f"Valor inválido para {key}"), 400
        if key == "buyingRole" and value:
            value=str(value).upper()
        if key in {"name", "role", "email", "phone", "whatsapp", "linkedin"} and isinstance(value, str):
            value=value.strip() or None
        setattr(contact, attr, value)
        changed.append(key)
    if not changed:
        return jsonify(error="No se recibieron cambios"), 400
    if not contact.name:
        return jsonify(error="El contacto necesita un nombre"), 400
    contact.verified_at=datetime.now(timezone.utc)
    company.last_enriched_at=datetime.now(timezone.utc)
    db.session.add(CompanyActivity(
        tenant_id=tenant.id, company_id=company.id, contact_id=contact.id, activity_type="DATA_UPDATE", channel="CRM",
        subject="Contacto actualizado", summary=f"Se actualizaron datos de {contact.name}: {', '.join(changed)}",
        created_by=(current_user().name if current_user() else "Equipo comercial")
    ))
    for opportunity in Opportunity.query.join(Project).filter(Project.company_id == company.id, Opportunity.tenant_id == tenant.id).all():
        lead_readiness(opportunity)
    _audit("UPDATE", "COMPANY_CONTACT", contact.id, {"companyId": company.id, "fields": changed})
    db.session.commit()
    return jsonify(
        id=contact.id, companyId=company.id, name=contact.name, role=contact.role,
        buyingRole=contact.buying_role, email=contact.email, phone=contact.phone,
        whatsapp=contact.whatsapp, confidence=contact.confidence, changed=changed
    )



@api_bp.post("/imports/history/preview")
@require_permission("WRITE_CRM")
def import_history_preview():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Seleccione una planilla .xlsx o .csv"), 400
    if Path(secure_filename(upload.filename)).suffix.lower() not in {".xlsx", ".csv"}:
        return jsonify(error="Formato de archivo no permitido"), 400
    try:
        from ..services.import_history import preview
        return jsonify(preview(upload))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        current_app.logger.exception("history import preview failed")
        return jsonify(error=f"No se pudo leer la planilla: {exc}"), 400


@api_bp.post("/imports/history")
@require_permission("WRITE_CRM")
def import_history_execute():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Seleccione una planilla .xlsx o .csv"), 400
    if Path(secure_filename(upload.filename)).suffix.lower() not in {".xlsx", ".csv"}:
        return jsonify(error="Formato de archivo no permitido"), 400
    try:
        import json
        from ..services.import_history import import_rows
        mapping = json.loads(request.form.get("mapping") or "{}")
        tenant = current_tenant()
        user = current_user()
        result = import_rows(upload, mapping, tenant, user)
        _audit("IMPORT", "COMMERCIAL_HISTORY", tenant.id, result)
        db.session.commit()
        return jsonify(ok=True, **result)
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("history import failed")
        return jsonify(error=f"No se pudo importar la planilla: {exc}"), 400


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
        result["contactsCreated"]=_sync_discovered_contacts(company,analysis)
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
    _ensure_next_action(opportunity, status=opportunity.status)
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


@api_bp.get("/companies/global-search")
def companies_global_search():
    tenant = current_tenant()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify(items=[])
    like = f"%{q}%"
    rows = Company.query.filter(
        Company.tenant_id == tenant.id, Company.status == "ACTIVE",
        or_(
            Company.name.ilike(like), Company.legal_name.ilike(like), Company.ruc.ilike(like),
            Company.registration_id.ilike(like), Company.domain.ilike(like), Company.website.ilike(like),
            Company.email_business.ilike(like), Company.email.ilike(like),
        )
    ).order_by(Company.name.asc()).limit(20).all()
    items=[]
    for c in rows:
        opp = Opportunity.query.join(Project).filter(Project.company_id == c.id, Opportunity.tenant_id == tenant.id).order_by(Opportunity.updated_at.desc()).first()
        items.append({
            "id": c.id, "name": c.name, "legalName": c.legal_name, "ruc": c.ruc or c.registration_id,
            "domain": c.domain or c.website, "city": c.city, "sector": c.sector,
            "status": opp.status if opp else None, "opportunityId": opp.id if opp else None,
        })
    return jsonify(items=items)


@api_bp.get("/data-quality")
def data_quality_dashboard():
    tenant=current_tenant()
    companies=Company.query.filter_by(tenant_id=tenant.id,status="ACTIVE").order_by(Company.name.asc()).all()
    incomplete=[]; no_contact=[]; no_next=[]; duplicate_candidates=[]
    seen={}
    from ..services.entity_resolution import normalize_domain, normalize_name
    for c in companies:
        completeness, missing=company_completeness(c)
        if completeness < 80:
            incomplete.append({"id":c.id,"name":c.name,"completeness":completeness,"missing":missing})
        active_contacts=Contact.query.filter_by(tenant_id=tenant.id,company_id=c.id,status="ACTIVE").count()
        if not active_contacts and not (c.email_business or c.email or c.whatsapp or c.phone_business or c.phone):
            no_contact.append({"id":c.id,"name":c.name})
        ops=Opportunity.query.join(Project).filter(Project.company_id==c.id,Opportunity.tenant_id==tenant.id,~Opportunity.status.in_({"GANHO","PERDIDO","DESCARTADO"})).all()
        if ops and not any(op.next_action_at for op in ops):
            no_next.append({"id":c.id,"name":c.name,"opportunityIds":[op.id for op in ops]})
        keys=[]
        if c.ruc or c.registration_id: keys.append(("RUC", ''.join(ch for ch in (c.ruc or c.registration_id) if ch.isdigit())))
        dom=normalize_domain(c.domain or c.website)
        if dom: keys.append(("DOMINIO",dom))
        nm=normalize_name(c.canonical_name or c.name)
        if nm and len(nm)>=6: keys.append(("NOMBRE",nm))
        for key in keys:
            if not key[1]: continue
            if key in seen and seen[key]["id"] != c.id:
                duplicate_candidates.append({"keyType":key[0],"key":key[1],"companies":[seen[key],{"id":c.id,"name":c.name}]})
            else: seen[key]={"id":c.id,"name":c.name}
    return jsonify(summary={
        "companies":len(companies),"incomplete":len(incomplete),"withoutContact":len(no_contact),
        "withoutNextAction":len(no_next),"duplicateCandidates":len(duplicate_candidates),
    }, incomplete=incomplete[:100], withoutContact=no_contact[:100], withoutNextAction=no_next[:100], duplicates=duplicate_candidates[:100])


@api_bp.get("/audit-log")
def audit_log_list():
    tenant=current_tenant()
    limit=min(max(int(request.args.get("limit",100)),1),300)
    rows=AuditLog.query.filter_by(tenant_id=tenant.id).order_by(AuditLog.created_at.desc()).limit(limit).all()
    users={u.id:u.name for u in User.query.filter_by(tenant_id=tenant.id).all()}
    return jsonify(items=[{
        "id":r.id,"action":r.action,"entityType":r.entity_type,"entityId":r.entity_id,"details":r.details or {},
        "user":users.get(r.user_id,"Sistema"),"createdAt":r.created_at.isoformat() if r.created_at else None,
    } for r in rows])


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


# V15.3 — personalización persistente de módulos por operación
_UI_MODULE_KEYS = [
    "triage","research","salesready","hoy","crm","reportes","pipeline","visitas",
    "radar","captacion","oportunidades","smartlists","metrics","admin"
]

@api_bp.route("/ui-config", methods=["GET", "PUT"])
def ui_config():
    tenant = current_tenant()
    user = current_user()
    settings = dict(tenant.settings or {})
    saved = settings.get("ui_modules") or {}
    if request.method == "GET":
        return jsonify(modules=saved)
    if not user or user.role not in {"ADMIN", "GROUP_ADMIN"}:
        return jsonify(error="Solo administradores pueden personalizar módulos"), 403
    payload = request.get_json(silent=True) or {}
    incoming = payload.get("modules") or {}
    clean = {}
    for key in _UI_MODULE_KEYS:
        row = incoming.get(key)
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()[:70]
        try:
            order = int(row.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        clean[key] = {
            "label": label,
            "visible": bool(row.get("visible", True)),
            "order": max(-100, min(order, 100)),
        }
    settings["ui_modules"] = clean
    tenant.settings = settings
    db.session.commit()
    _audit("UPDATE_UI_CONFIG", "TENANT", tenant.id, {"modules": list(clean)})
    db.session.commit()
    return jsonify(ok=True, modules=clean)
