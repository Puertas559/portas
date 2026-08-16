from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy import text
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import (
    AuditLog, CollectorRun, Company, Contact, Evidence, Opportunity, OpportunityEvidence, OpportunityScore, Project, Proposal,
    ProspectSignal, SalesTask, ScoreFactor, Signal, Source, SourceDocument, TimelineEvent, VisitRecord, Watchlist, WebsiteAnalysis,
)
from ..services.entity_resolution import resolve_company, resolve_project
from ..services.intelligence import as_datetime, link_evidence_and_products, record_evidence, score_opportunity
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


def _create_cadence(opportunity):
    if opportunity.tasks:
        return
    now = datetime.now(timezone.utc)
    steps = [
        (0, "WHATSAPP", "Enviar primer contacto personalizado por WhatsApp"),
        (2, "CALL", "Llamar e identificar al responsable de mantenimiento, operaciones o compras"),
        (5, "EMAIL", "Enviar carta de presentación y casos aplicables"),
        (10, "VISIT", "Proponer una visita técnica presencial"),
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
    try:
        from ..services.site_analyzer import analyze_website
        analysis = analyze_website(data["url"])
        return jsonify(analysis.to_dict()), 201
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        db.session.rollback()
        return jsonify(error="No se pudo analizar el sitio. Verifique que sea público y esté disponible."), 502


@api_bp.get("/website-analysis")
def website_analysis_list():
    tenant = current_tenant()
    rows = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id).order_by(WebsiteAnalysis.created_at.desc()).limit(30).all()
    return jsonify([row.to_dict() for row in rows])


def _commercial_messages(analysis):
    brand = current_tenant().settings or {}
    brand_name = brand.get("brand_name", "Puertas Brasil PY")
    contact = analysis.contacts[0] if analysis.contacts else f"equipo de {analysis.company_name}"
    products = analysis.products or ["soluciones de accesos automáticos"]
    services = analysis.services or ["evaluación técnica y proyecto a medida"]
    product_text = ", ".join(products[:3])
    service_text = ", ".join(services[:2])
    whatsapp = (
        f"Hola, {contact}. Soy parte del equipo comercial de {brand_name}. "
        f"Al conocer la actividad de {analysis.company_name} en el sector {analysis.sector}, "
        f"identificamos una posible aplicación para {product_text}. "
        f"Podemos realizar {service_text} para validar la solución adecuada. "
        "¿Con quién podríamos coordinar una breve conversación técnica?"
    )
    subject = f"Propuesta de soluciones de accesos automáticos para {analysis.company_name}"
    email = (
        f"Estimado/a {contact}:\n\n"
        f"Es un gusto presentarle a {brand_name}, empresa especializada en soluciones "
        "de cerramientos automáticos para los segmentos industrial, logístico, comercial y aeronáutico.\n\n"
        f"A partir de la información pública de {analysis.company_name}, dedicada al sector {analysis.sector}, "
        f"identificamos una posible oportunidad de mejora mediante {product_text}. Nuestra propuesta puede incluir "
        f"{service_text}, además de instalación, mantenimiento preventivo y correctivo, reparaciones, repuestos "
        "multimarca y retrofit.\n\n"
        "Nos gustaría conocer su operación y verificar, sin compromiso, si estas soluciones pueden aportar mayor "
        "seguridad, eficiencia y continuidad operativa. Quedamos a disposición para coordinar una visita técnica "
        "o una breve reunión con la persona responsable de mantenimiento, operaciones o compras.\n\n"
        f"Atentamente,\nEquipo comercial de {brand_name}\n"
        f"{brand.get('sales_phone', '')}\n{brand.get('sales_email', '')}\n{brand.get('website', '')}"
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
    db.session.add(TimelineEvent(
        opportunity=opportunity, event_type="WEBSITE_QUALIFICATION",
        description="Empresa calificada manualmente; mensajes comerciales personalizados generados",
    ))
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
    return jsonify(
        opportunities=len(opportunities), contacted=len(contacted), proposals=len(proposals), won=len(won),
        pipelineValue=sum(row.estimated_value or 0 for row in active),
        weightedValue=sum((row.estimated_value or 0) * (row.probability or 0) / 100 for row in active),
        proposalValue=sum(row.amount for row in proposals), overdueTasks=overdue,
        responseRate=round(100 * len(contacted) / len(opportunities), 1) if opportunities else 0,
        winRate=round(100 * len(won) / len(opportunities), 1) if opportunities else 0,
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
    company.accessibility_score = min(100, (company.accessibility_score or 0) + 15)
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


@api_bp.get("/prospecting-map/config")
def prospecting_map_config():
    import os
    return jsonify(
        enabled=True,
        googlePlacesEnabled=bool(os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")),
        browserKey=os.getenv("GOOGLE_MAPS_BROWSER_KEY") or "",
        maxCalls=int(os.getenv("GOOGLE_PLACES_MAX_CALLS", "120")),
    )


@api_bp.get("/prospecting-map/search")
def prospecting_map_search():
    from ..services.google_places import search_places
    tenant = current_tenant()
    try:
        payload = search_places(
            query=request.args.get("q", ""),
            city=request.args.get("city", ""),
            region=request.args.get("region", ""),
            industry=request.args.get("industry", ""),
            depth=request.args.get("depth", "deep"),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 502

    source_ids = [row.get("sourceId") or (f"gplace:{row['placeId']}" if row.get("placeId") else None) for row in payload["results"]]
    source_ids = [value for value in source_ids if value]
    crm_by_source = {}
    if source_ids:
        for company in Company.query.filter(Company.tenant_id == tenant.id, Company.registration_id.in_(source_ids)).all():
            crm_by_source[company.registration_id] = company.id
    for row in payload["results"]:
        source_id = row.get("sourceId") or (f"gplace:{row['placeId']}" if row.get("placeId") else None)
        company_id = crm_by_source.get(source_id)
        row["inCrm"] = bool(company_id)
        row["crmCompanyId"] = company_id
    return jsonify(payload)


@api_bp.post("/prospecting-map/import")
@require_permission("WRITE_CRM")
def prospecting_map_import():
    data = request.get_json(silent=True) or {}
    rows = data.get("places") or []
    if not isinstance(rows, list) or not rows:
        return jsonify(error="Seleccione al menos una empresa"), 400
    if len(rows) > 100:
        return jsonify(error="Importe como máximo 100 empresas por lote"), 400

    created, existing, errors = [], [], []
    for row in rows:
        if not row.get("company") or not (row.get("sourceId") or row.get("placeId")):
            continue
        payload = {
            "company": row.get("company"),
            "project": "Empresa identificada en mapa de prospección",
            "event": "TERRITORIAL_DISCOVERY",
            "projectType": "TERRITORIAL_PROSPECTING",
            "stage": "Prospección territorial",
            "city": data.get("city") or "Por validar",
            "department": data.get("region") or "Por validar",
            "country": "Paraguay",
            "sector": row.get("primaryType") or data.get("industry") or "Industria y manufactura",
            "website": row.get("website"),
            "phone": row.get("phone"),
            "whatsapp": row.get("phone"),
            "address": row.get("address"),
            "registrationId": row.get("sourceId") or f"gplace:{row.get('placeId')}",
            "sourceName": row.get("source") or "Territorial Discovery",
            "sourceUrl": row.get("mapsUrl") or row.get("website"),
            "sourceTitle": row.get("company"),
            "evidence": f"Empresa identificada durante barrido territorial por {row.get('source') or 'fuente empresarial'}. Coincidencia: {row.get('matchedTerm') or 'búsqueda empresarial'}.",
            "evidenceClassification": "FACT",
            "dataConfidence": 72 if row.get("website") or row.get("phone") else 60,
            "icpFit": 65,
            "intent": 25,
            "probability": 10,
            "products": [],
        }
        try:
            opportunity, was_created = _create_intelligence_opportunity(payload)
            db.session.commit()
            if was_created:
                created.append({"opportunityId": opportunity.id, "company": opportunity.project.company.name})
            else:
                existing.append({"opportunityId": opportunity.id, "company": opportunity.project.company.name})
        except Exception as exc:
            db.session.rollback()
            errors.append({"company": row.get("company"), "error": str(exc)[:180]})
            continue
    return jsonify(created=created, existing=existing, errors=errors, imported=len(created), skipped=len(existing))


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
