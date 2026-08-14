from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError
from ..models import CollectorRun, Opportunity, ProspectSignal, WebsiteAnalysis

web_bp = Blueprint("web", __name__)

DEMO = [
    {"id": 1, "company": "Logística Guaraní S.A.", "sector": "Logística", "origin": "Paraguay", "city": "Minga Guazú", "department": "Alto Paraná", "event": "NEW_LOGISTICS_CENTER", "project": "Nuevo centro logístico de 12.000 m²", "score": 94, "level": "HOT", "status": "NOVO", "products": ["Puerta seccional", "Puerta rápida", "Automatización"], "evidence": "Un comunicado empresarial informa el inicio de las obras de un nuevo centro logístico.", "stage": "Obra iniciada", "investment": "USD 8,5 millones", "demo": True},
    {"id": 2, "company": "FríoPar Alimentos", "sector": "Alimentos", "origin": "Paraguay", "city": "Hernandarias", "department": "Alto Paraná", "event": "EXPANSION", "project": "Ampliación de la planta frigorífica", "score": 89, "level": "HIGH", "status": "QUALIFICADO", "products": ["Puerta rápida", "Puerta seccional", "Mantenimiento"], "evidence": "La empresa anunció una ampliación de capacidad y nuevas áreas de expedición.", "stage": "Proyecto aprobado", "investment": "USD 4,2 millones", "demo": True},
    {"id": 3, "company": "NovaMaq Brasil", "sector": "Metalúrgica", "origin": "Brasil", "city": "Ciudad del Este", "department": "Alto Paraná", "event": "NEW_COMPANY", "project": "Primera operación industrial en Paraguay", "score": 86, "level": "HIGH", "status": "NOVO", "products": ["Puerta enrollable", "Puerta seccional", "Automatizadores"], "evidence": "Una nota pública anuncia la instalación de la primera operación paraguaya.", "stage": "Instalación anunciada", "investment": "No divulgado", "demo": True},
]


@web_bp.get("/")
def index():
    try:
        rows = Opportunity.query.order_by(Opportunity.score.desc()).limit(100).all()
        leads = [row.to_dict() for row in rows]
    except SQLAlchemyError:
        leads = []
    try:
        prospect_signals = ProspectSignal.query.filter_by(status="PENDING_VALIDATION").order_by(ProspectSignal.score.desc(), ProspectSignal.discovered_at.desc()).limit(30).all()
        last_collector_run = CollectorRun.query.order_by(CollectorRun.started_at.desc()).first()
        prospect_total = ProspectSignal.query.filter_by(status="PENDING_VALIDATION").count()
    except SQLAlchemyError:
        prospect_signals, last_collector_run, prospect_total = [], None, 0
    try:
        website_analyses = WebsiteAnalysis.query.order_by(WebsiteAnalysis.created_at.desc()).limit(12).all()
    except SQLAlchemyError:
        website_analyses = []
    demo_mode = not leads
    return render_template("index.html", leads=leads or DEMO, demo_mode=demo_mode, prospect_signals=prospect_signals, last_collector_run=last_collector_run, prospect_total=prospect_total, website_analyses=website_analyses)
