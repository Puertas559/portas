from flask import Blueprint, jsonify, request
from sqlalchemy import text
from ..extensions import db
from ..models import Company, Opportunity, Project, TimelineEvent

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
