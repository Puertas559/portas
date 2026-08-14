from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError
from ..models import Opportunity

web_bp = Blueprint("web", __name__)

DEMO = [
    {"id": 1, "company": "Logística Guaraní S.A.", "sector": "Logística", "origin": "Paraguai", "city": "Minga Guazú", "department": "Alto Paraná", "event": "NEW_LOGISTICS_CENTER", "project": "Novo centro logístico de 12.000 m²", "score": 94, "level": "HOT", "status": "NOVO", "products": ["Porta seccional", "Porta rápida", "Automação"], "evidence": "Comunicado empresarial informa início das obras de um novo centro logístico.", "stage": "Obra iniciada", "investment": "US$ 8,5 milhões", "demo": True},
    {"id": 2, "company": "FríoPar Alimentos", "sector": "Alimentos", "origin": "Paraguai", "city": "Hernandarias", "department": "Alto Paraná", "event": "EXPANSION", "project": "Ampliação da unidade frigorífica", "score": 89, "level": "HIGH", "status": "QUALIFICADO", "products": ["Porta rápida", "Porta seccional", "Manutenção"], "evidence": "A empresa anunciou ampliação de capacidade e novas áreas de expedição.", "stage": "Projeto aprovado", "investment": "US$ 4,2 milhões", "demo": True},
    {"id": 3, "company": "NovaMaq Brasil", "sector": "Metalúrgica", "origin": "Brasil", "city": "Ciudad del Este", "department": "Alto Paraná", "event": "NEW_COMPANY", "project": "Primeira operação industrial no Paraguai", "score": 86, "level": "HIGH", "status": "NOVO", "products": ["Porta de enrolar", "Porta seccional", "Automatizadores"], "evidence": "Nota pública anuncia a instalação da primeira operação paraguaia.", "stage": "Instalação anunciada", "investment": "Não divulgado", "demo": True},
]


@web_bp.get("/")
def index():
    try:
        rows = Opportunity.query.order_by(Opportunity.score.desc()).limit(100).all()
        leads = [row.to_dict() for row in rows]
    except SQLAlchemyError:
        leads = []
    demo_mode = not leads
    return render_template("index.html", leads=leads or DEMO, demo_mode=demo_mode)
