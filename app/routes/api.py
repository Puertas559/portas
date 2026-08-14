from flask import Blueprint, jsonify, request
from sqlalchemy import text
from ..extensions import db
from ..models import CollectorRun, Company, Opportunity, Project, ProspectSignal, TimelineEvent, WebsiteAnalysis

api_bp = Blueprint("api", __name__, url_prefix="/api")
STATUSES = {"NOVO", "QUALIFICADO", "CONTATO_REALIZADO", "RESPONDEU", "VISITA", "ORCAMENTO", "NEGOCIACAO", "GANHO", "PERDIDO", "MONITORAMENTO", "DESCARTADO"}


@api_bp.get("/opportunities")
def opportunities_list():
    rows = Opportunity.query.order_by(Opportunity.score.desc()).limit(500).all()
    return jsonify([row.to_dict() for row in rows])


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
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="DISCOVERY", description="Oportunidad registrada en el radar"))
    db.session.commit()
    return jsonify(opportunity.to_dict()), 201


@api_bp.patch("/opportunities/<int:opportunity_id>")
def opportunity_update(opportunity_id):
    opportunity = db.get_or_404(Opportunity, opportunity_id)
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in STATUSES:
        return jsonify(error="Estado inválido"), 400
    opportunity.status = status
    db.session.add(TimelineEvent(opportunity=opportunity, event_type="CRM_STATUS", description=f"Estado actualizado a {status}"))
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
