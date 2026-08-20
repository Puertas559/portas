from flask import Blueprint, render_template, redirect, session, url_for, abort
from sqlalchemy.exc import SQLAlchemyError
from ..models import CollectorRun, Opportunity, ProspectSignal, WebsiteAnalysis, Company, Tenant
from ..tenant import current_tenant, current_user, ensure_group_operations, seed_products

web_bp = Blueprint("web", __name__)

DEMO = [
    {"id": 1, "company": "Logística Guaraní S.A.", "sector": "Logística", "origin": "Paraguay", "city": "Minga Guazú", "department": "Alto Paraná", "event": "NEW_LOGISTICS_CENTER", "project": "Nuevo centro logístico de 12.000 m²", "score": 94, "level": "HOT", "status": "NOVO", "products": ["Puerta seccional", "Puerta rápida", "Automatización"], "evidence": "Un comunicado empresarial informa el inicio de las obras de un nuevo centro logístico.", "stage": "Obra iniciada", "investment": "USD 8,5 millones", "demo": True},
    {"id": 2, "company": "FríoPar Alimentos", "sector": "Alimentos", "origin": "Paraguay", "city": "Hernandarias", "department": "Alto Paraná", "event": "EXPANSION", "project": "Ampliación de la planta frigorífica", "score": 89, "level": "HIGH", "status": "QUALIFICADO", "products": ["Puerta rápida", "Puerta seccional", "Mantenimiento"], "evidence": "La empresa anunció una ampliación de capacidad y nuevas áreas de expedición.", "stage": "Proyecto aprobado", "investment": "USD 4,2 millones", "demo": True},
    {"id": 3, "company": "NovaMaq Brasil", "sector": "Metalúrgica", "origin": "Brasil", "city": "Ciudad del Este", "department": "Alto Paraná", "event": "NEW_COMPANY", "project": "Primera operación industrial en Paraguay", "score": 86, "level": "HIGH", "status": "NOVO", "products": ["Puerta enrollable", "Puerta seccional", "Automatizadores"], "evidence": "Una nota pública anuncia la instalación de la primera operación paraguaya.", "stage": "Instalación anunciada", "investment": "No divulgado", "demo": True},
]


@web_bp.get("/group")
def group_home():
    user = current_user()
    if not user or user.role != "GROUP_ADMIN":
        return redirect(url_for("web.index"))
    ensure_group_operations()
    operations = []
    for tenant in Tenant.query.filter(Tenant.slug.in_(["puertas-brasil-py", "techdoors-br"])).order_by(Tenant.id.asc()).all():
        settings = tenant.settings or {}
        operations.append({
            "id": tenant.id, "name": tenant.name, "slug": tenant.slug, "settings": settings,
            "companies": Company.query.filter_by(tenant_id=tenant.id, status="ACTIVE").count(),
            "active": tenant.status == "ACTIVE",
        })
    premium = {
        "name": "Premium Portas e Portões", "slug": "premium-portas-br", "country": "Brasil",
        "website": "https://premiumportas.com.br/", "phone": "(47) 9 9111 5057",
        "email": "contato@premiumportas.com.br",
        "address": "Palmitos - SC / Frederico Westphalen - RS",
        "description": "Empresa do HG Grupo especializada em portas e portões seccionados para aplicações residenciais e industriais.",
        "radar_enabled": False,
    }
    return render_template("group.html", user=user, operations=operations, premium=premium)


@web_bp.get("/group/operation/<slug>")
def switch_operation(slug):
    user = current_user()
    if not user or user.role != "GROUP_ADMIN":
        abort(403)
    ensure_group_operations()
    tenant = Tenant.query.filter_by(slug=slug, status="ACTIVE").first_or_404()
    seed_products(tenant); tenant.settings = tenant.settings or {}; session["active_tenant_id"] = tenant.id
    return redirect(url_for("web.index"))


@web_bp.get("/")
def index():
    tenant = current_tenant()
    user = current_user()
    try:
        rows = Opportunity.query.filter_by(tenant_id=tenant.id).order_by(Opportunity.score.desc()).limit(100).all()
        leads = [row.to_dict() for row in rows]
    except SQLAlchemyError:
        leads = []
    try:
        prospect_signals = ProspectSignal.query.filter_by(tenant_id=tenant.id, status="PENDING_VALIDATION").order_by(ProspectSignal.score.desc(), ProspectSignal.discovered_at.desc()).limit(30).all()
        last_collector_run = CollectorRun.query.filter_by(tenant_id=tenant.id).order_by(CollectorRun.started_at.desc()).first()
        prospect_total = ProspectSignal.query.filter_by(tenant_id=tenant.id, status="PENDING_VALIDATION").count()
    except SQLAlchemyError:
        prospect_signals, last_collector_run, prospect_total = [], None, 0
    try:
        website_analyses = WebsiteAnalysis.query.filter_by(tenant_id=tenant.id).order_by(WebsiteAnalysis.created_at.desc()).limit(12).all()
    except SQLAlchemyError:
        website_analyses = []
    # Nunca injetar empresas DEMO em operações reais. Cada operação deve exibir apenas
    # os registros pertencentes ao seu próprio tenant_id.
    demo_mode = False
    return render_template("index.html", leads=leads, demo_mode=demo_mode, prospect_signals=prospect_signals, last_collector_run=last_collector_run, prospect_total=prospect_total, website_analyses=website_analyses, tenant=tenant, brand=tenant.settings or {}, user=user)
