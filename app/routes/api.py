from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy import text
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import CollectorRun, Company, Opportunity, Project, Proposal, ProspectSignal, SalesTask, TimelineEvent, VisitRecord, WebsiteAnalysis

api_bp = Blueprint("api", __name__, url_prefix="/api")
STATUSES = {"NOVO", "QUALIFICADO", "CONTATO_REALIZADO", "RESPONDEU", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO", "PERDIDO", "MONITORAMENTO", "DESCARTADO"}


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


@api_bp.get("/opportunities")
def opportunities_list():
    rows = Opportunity.query.order_by(Opportunity.score.desc()).limit(500).all()
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
def company_search_add():
    data = request.get_json(silent=True) or {}
    if not data.get("company"):
        return jsonify(error="Falta el nombre de la empresa"), 400
    company = Company.query.filter_by(name=data["company"].strip()).first()
    if not company:
        company = Company(name=data["company"].strip(), origin_country="Paraguay")
        db.session.add(company)
    company.sector = data.get("sector") or company.sector or "Por validar"
    company.website = data.get("website") or company.website
    company.address = data.get("address") or company.address
    company.phone = data.get("phone") or company.phone
    company.whatsapp = data.get("phone") or company.whatsapp
    company.email = data.get("email") or company.email
    company.linkedin_url = data.get("linkedin") or company.linkedin_url
    project = Project(
        company=company, name="Empresa identificada por búsqueda geográfica",
        city=data.get("city") or "Por validar", department=data.get("region") or "Por validar",
        stage="Prospección geográfica",
    )
    try:
        score = max(0, min(100, int(data.get("score", 55))))
    except (TypeError, ValueError):
        score = 55
    opportunity = Opportunity(
        project=project, event_type="COMPANY_DISCOVERY", score=score,
        level="HIGH" if score >= 75 else "MEDIUM", status="NOVO",
        products=[], evidence=f"Empresa identificada por fuente pública en {data.get('city') or 'Paraguay'}.",
        source_name=data.get("source") or "Buscador empresarial", source_url=data.get("website"),
    )
    db.session.add(opportunity)
    db.session.flush()
    _create_cadence(opportunity)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="GEOGRAPHIC_DISCOVERY", description="Empresa añadida desde la búsqueda por región e industria"))
    db.session.commit()
    return jsonify(opportunity.to_dict()), 201


@api_bp.post("/opportunities")
def opportunities_create():
    data = request.get_json(silent=True) or {}
    required = ("company", "project", "city", "department", "event", "evidence")
    missing = [key for key in required if not data.get(key)]
    if missing:
        return jsonify(error="Faltan campos obligatorios", fields=missing), 400
    score = max(0, min(100, int(data.get("score", 0))))
    level = "HOT" if score >= 90 else "HIGH" if score >= 75 else "MEDIUM" if score >= 55 else "LOW" if score >= 30 else "VERY_LOW"
    company = Company.query.filter_by(name=data["company"].strip()).first()
    if not company:
        company = Company(name=data["company"].strip(), sector=data.get("sector"), origin_country=data.get("origin"))
        db.session.add(company)
    project = Project(company=company, name=data["project"].strip(), city=data["city"].strip(), department=data["department"].strip(), stage=data.get("stage"), investment=data.get("investment"))
    opportunity = Opportunity(project=project, event_type=data["event"], score=score, level=level, products=data.get("products") or [], evidence=data["evidence"], source_name=data.get("sourceName"), source_url=data.get("sourceUrl"))
    db.session.add(opportunity)
    db.session.flush()
    _create_cadence(opportunity)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="DISCOVERY", description="Oportunidad registrada en el radar"))
    db.session.commit()
    return jsonify(opportunity.to_dict()), 201


@api_bp.patch("/opportunities/<int:opportunity_id>")
def opportunity_update(opportunity_id):
    opportunity = db.get_or_404(Opportunity, opportunity_id)
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
            changes.append("Valor estimado actualizado")
        except (TypeError, ValueError):
            return jsonify(error="Valor estimado inválido"), 400
    if data.get("probability") is not None:
        try:
            opportunity.probability = max(0, min(100, int(data["probability"])))
            changes.append("Probabilidad actualizada")
        except (TypeError, ValueError):
            return jsonify(error="Probabilidad inválida"), 400
    if not changes:
        return jsonify(error="No se recibió ningún cambio"), 400
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="CRM_UPDATE", description=" · ".join(changes)))
    db.session.commit()
    return jsonify(opportunity.to_dict())


@api_bp.get("/timeline/<int:opportunity_id>")
def timeline(opportunity_id):
    rows = TimelineEvent.query.filter_by(opportunity_id=opportunity_id).order_by(TimelineEvent.occurred_at.desc()).all()
    return jsonify([{"id": row.id, "type": row.event_type, "description": row.description, "occurredAt": row.occurred_at.isoformat()} for row in rows])


@api_bp.get("/exports/status")
def export_status():
    return jsonify(dataDir="/data", status="ready")


@api_bp.get("/collector/status")
def collector_status():
    last_run = CollectorRun.query.order_by(CollectorRun.started_at.desc()).first()
    pending = ProspectSignal.query.filter_by(status="PENDING_VALIDATION").count()
    return jsonify(enabled=True, pending=pending, lastRun=last_run.to_dict() if last_run else None)


@api_bp.post("/collector/run")
def collector_run():
    from datetime import datetime, timedelta, timezone
    recent = CollectorRun.query.order_by(CollectorRun.started_at.desc()).first()
    if recent and recent.started_at and recent.started_at > datetime.now(timezone.utc) - timedelta(minutes=1):
        return jsonify(error="La captación ya fue ejecutada recientemente", run=recent.to_dict()), 429
    from ..services.collector import run_collector
    run = run_collector()
    return jsonify(run.to_dict())


@api_bp.post("/signals/<int:signal_id>/approve")
def signal_approve(signal_id):
    signal = db.get_or_404(ProspectSignal, signal_id)
    if signal.opportunity_id:
        return jsonify(signal.to_dict())
    company = Company.query.filter_by(name=signal.company_name).first()
    if not company:
        company = Company(name=signal.company_name, sector="Por validar", origin_country="Paraguay")
        db.session.add(company)
    project = Project(company=company, name=signal.title, city=signal.city or "Por validar", department=signal.department or "Por validar", stage="Prospección automática")
    opportunity = Opportunity(project=project, event_type=signal.event_type, score=signal.score, level=signal.level, products=signal.products or [], evidence=signal.summary, source_name=signal.source_name, source_url=signal.source_url)
    db.session.add(opportunity)
    db.session.flush()
    _create_cadence(opportunity)
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="AUTOMATIC_DISCOVERY", description=f"Señal aprobada desde {signal.source_name}"))
    signal.status, signal.opportunity_id = "APPROVED", opportunity.id
    db.session.commit()
    return jsonify(opportunity=opportunity.to_dict(), signal=signal.to_dict()), 201


@api_bp.post("/signals/<int:signal_id>/discard")
def signal_discard(signal_id):
    signal = db.get_or_404(ProspectSignal, signal_id)
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
    rows = WebsiteAnalysis.query.order_by(WebsiteAnalysis.created_at.desc()).limit(30).all()
    return jsonify([row.to_dict() for row in rows])


def _commercial_messages(analysis):
    contact = analysis.contacts[0] if analysis.contacts else f"equipo de {analysis.company_name}"
    products = analysis.products or ["soluciones de accesos automáticos"]
    services = analysis.services or ["evaluación técnica y proyecto a medida"]
    product_text = ", ".join(products[:3])
    service_text = ", ".join(services[:2])
    whatsapp = (
        f"Hola, {contact}. Soy parte del equipo comercial de Puertas Brasil PY. "
        f"Al conocer la actividad de {analysis.company_name} en el sector {analysis.sector}, "
        f"identificamos una posible aplicación para {product_text}. "
        f"Podemos realizar {service_text} para validar la solución adecuada. "
        "¿Con quién podríamos coordinar una breve conversación técnica?"
    )
    subject = f"Propuesta de soluciones de accesos automáticos para {analysis.company_name}"
    email = (
        f"Estimado/a {contact}:\n\n"
        "Es un gusto presentarle a Puertas Brasil PY, fábrica paraguaya especializada en soluciones "
        "de cerramientos automáticos para los segmentos industrial, logístico, comercial y aeronáutico.\n\n"
        f"A partir de la información pública de {analysis.company_name}, dedicada al sector {analysis.sector}, "
        f"identificamos una posible oportunidad de mejora mediante {product_text}. Nuestra propuesta puede incluir "
        f"{service_text}, además de instalación, mantenimiento preventivo y correctivo, reparaciones, repuestos "
        "multimarca y retrofit.\n\n"
        "Nos gustaría conocer su operación y verificar, sin compromiso, si estas soluciones pueden aportar mayor "
        "seguridad, eficiencia y continuidad operativa. Quedamos a disposición para coordinar una visita técnica "
        "o una breve reunión con la persona responsable de mantenimiento, operaciones o compras.\n\n"
        "Atentamente,\nEquipo comercial de Puertas Brasil PY\n"
        "+595 986 986215\ngerenciacomercial@puertasbrasil.com.py\npuertasbrasil.com.py"
    )
    return whatsapp, subject, email


@api_bp.post("/website-analysis/<int:analysis_id>/qualify")
def website_analysis_qualify(analysis_id):
    analysis = db.get_or_404(WebsiteAnalysis, analysis_id)
    if analysis.opportunity_id:
        return jsonify(analysis=analysis.to_dict(), opportunity=analysis.opportunity.to_dict())
    company = Company.query.filter_by(name=analysis.company_name).first()
    if not company:
        company = Company(name=analysis.company_name, sector=analysis.sector, origin_country="Paraguay", website=analysis.url)
        db.session.add(company)
    else:
        company.website = company.website or analysis.url
        company.sector = company.sector or analysis.sector
    company.address = company.address or analysis.address
    company.phone = company.phone or (analysis.phones[0] if analysis.phones else None)
    company.whatsapp = company.whatsapp or analysis.whatsapp
    company.email = company.email or (analysis.emails[0] if analysis.emails else None)
    company.linkedin_url = company.linkedin_url or (analysis.social_links or {}).get("linkedin")
    project = Project(
        company=company, name=f"Calificación comercial desde {analysis.url}",
        city=(analysis.address or "Por validar")[:120], department="Por validar",
        stage="Empresa calificada desde análisis web",
    )
    level = {"MUY ALTO": "HOT", "ALTO": "HIGH", "MEDIO": "MEDIUM", "BAJO": "LOW"}.get(analysis.potential_level, "MEDIUM")
    evidence = "; ".join(analysis.reasons or []) or analysis.summary or "Análisis público del sitio empresarial"
    opportunity = Opportunity(
        project=project, event_type="BUYING_INTENT", score=analysis.potential_score, level=level,
        status="QUALIFICADO", products=analysis.products or [], evidence=evidence,
        source_name="Análisis minucioso del sitio", source_url=analysis.url,
    )
    db.session.add(opportunity)
    db.session.flush()
    _create_cadence(opportunity)
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
def website_analysis_disqualify(analysis_id):
    analysis = db.get_or_404(WebsiteAnalysis, analysis_id)
    if analysis.opportunity_id:
        return jsonify(error="La empresa ya ingresó al CRM; márquela como descartada desde el CRM"), 409
    analysis.decision = "DISQUALIFIED"
    db.session.commit()
    return jsonify(analysis.to_dict())


@api_bp.post("/tasks/ensure")
def tasks_ensure():
    created = 0
    rows = Opportunity.query.filter(~Opportunity.status.in_({"RESPONDEU", "GANHO", "PERDIDO", "DESCARTADO"})).all()
    for opportunity in rows:
        if not opportunity.tasks:
            _create_cadence(opportunity)
            created += 4
    db.session.commit()
    return jsonify(created=created)


@api_bp.get("/dashboard/today")
def dashboard_today():
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    tasks = SalesTask.query.filter(SalesTask.status == "PENDING", SalesTask.due_at <= tomorrow).order_by(SalesTask.due_at.asc()).limit(50).all()
    return jsonify(
        tasks=[task.to_dict() for task in tasks],
        overdue=sum(1 for task in tasks if task.due_at.replace(tzinfo=timezone.utc) < now if task.due_at.tzinfo is None) + sum(1 for task in tasks if task.due_at.tzinfo is not None and task.due_at < now),
        dueToday=len(tasks),
    )


@api_bp.patch("/tasks/<int:task_id>")
def task_update(task_id):
    task = db.get_or_404(SalesTask, task_id)
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
def visit_create():
    data = request.form if request.files else (request.get_json(silent=True) or {})
    opportunity = db.get_or_404(Opportunity, int(data.get("opportunityId", 0)))
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
def proposal_create(opportunity_id):
    import textwrap
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    opportunity = db.get_or_404(Opportunity, opportunity_id)
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
    pdf.setFillColorRGB(1, 1, 1); pdf.setFont("Helvetica-Bold", 22); pdf.drawString(45, height - 55, "PUERTAS BRASIL PY")
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
    pdf.setFont("Helvetica", 9); pdf.drawString(45, 65, "+595 986 986215 · gerenciacomercial@puertasbrasil.com.py · puertasbrasil.com.py")
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
    proposal = db.get_or_404(Proposal, proposal_id)
    path = Path(current_app.config["DATA_DIR"]) / "proposals" / proposal.pdf_filename
    return send_file(path, as_attachment=True, download_name=f"Propuesta-{proposal.number}.pdf")


@api_bp.get("/metrics")
def commercial_metrics():
    opportunities = Opportunity.query.all()
    proposals = Proposal.query.all()
    active = [row for row in opportunities if row.status not in {"GANHO", "PERDIDO", "DESCARTADO"}]
    contacted = [row for row in opportunities if row.status not in {"NOVO", "QUALIFICADO", "DESCARTADO"}]
    won = [row for row in opportunities if row.status == "GANHO"]
    overdue = SalesTask.query.filter(SalesTask.status == "PENDING", SalesTask.due_at < datetime.now(timezone.utc)).count()
    return jsonify(
        opportunities=len(opportunities), contacted=len(contacted), proposals=len(proposals), won=len(won),
        pipelineValue=sum(row.estimated_value or 0 for row in active),
        weightedValue=sum((row.estimated_value or 0) * (row.probability or 0) / 100 for row in active),
        proposalValue=sum(row.amount for row in proposals), overdueTasks=overdue,
        responseRate=round(100 * len(contacted) / len(opportunities), 1) if opportunities else 0,
        winRate=round(100 * len(won) / len(opportunities), 1) if opportunities else 0,
    )


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
