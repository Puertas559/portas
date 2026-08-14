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
