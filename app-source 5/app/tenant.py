import os
from functools import wraps
from flask import current_app, g, has_request_context, jsonify, session
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Product, Tenant, User


DEFAULT_SETTINGS = {
    "brand_name": "Puertas Brasil PY",
    "default_country": "Paraguay",
    "sales_phone": "+595 986 986215",
    "sales_email": "gerenciacomercial@puertasbrasil.com.py",
    "website": "puertasbrasil.com.py",
    "scoring_model_version": "phase1-v1",
    "scoring_weights": {
        "ICP_FIT": 0.18,
        "INTENT": 0.22,
        "TIMING": 0.12,
        "PROJECT_VALUE": 0.10,
        "PRODUCT_FIT": 0.14,
        "GEOGRAPHIC_FIT": 0.08,
        "DATA_CONFIDENCE": 0.08,
        "SIGNAL_RECENCY": 0.05,
        "COMMERCIAL_HISTORY": 0.03,
    },
}

DEFAULT_PRODUCTS = (
    ("Puertas seccionales", "PUERTAS INDUSTRIALES"),
    ("Puertas rápidas", "PUERTAS INDUSTRIALES"),
    ("Puertas de acero enrollables", "PUERTAS INDUSTRIALES"),
    ("Niveladoras de docas", "EQUIPAMIENTO DE MUELLES"),
    ("Abrigos y sellos de docas", "EQUIPAMIENTO DE MUELLES"),
    ("Automatización de accesos", "AUTOMATIZACIÓN"),
    ("Mantenimiento industrial", "SERVICIOS"),
)

ROLE_PERMISSIONS = {
    "GROUP_ADMIN": {"*"},
    "ADMIN": {"*"},
    "MANAGER": {"READ_INTELLIGENCE", "WRITE_CRM", "RUN_COLLECTOR", "MANAGE_SCORING"},
    "SALES": {"READ_INTELLIGENCE", "WRITE_CRM"},
    "VIEWER": {"READ_INTELLIGENCE"},
}


def normalize_email(value):
    return (value or "").strip().casefold()


def ensure_default_tenant():
    slug = current_app.config["DEFAULT_TENANT_SLUG"]
    tenant = Tenant.query.filter_by(slug=slug).first()
    if tenant:
        merged = DEFAULT_SETTINGS.copy()
        merged.update(tenant.settings or {})
        if merged != (tenant.settings or {}):
            tenant.settings = merged
            db.session.commit()
        return tenant
    tenant = Tenant(name=current_app.config["DEFAULT_TENANT_NAME"], slug=slug, settings=DEFAULT_SETTINGS.copy())
    db.session.add(tenant)
    db.session.flush()
    seed_products(tenant)
    db.session.commit()
    return tenant


def seed_products(tenant):
    from .services.entity_resolution import normalize_name
    for name, category in DEFAULT_PRODUCTS:
        normalized = normalize_name(name)
        exists = Product.query.filter_by(tenant_id=tenant.id, normalized_name=normalized).first()
        if not exists:
            db.session.add(Product(tenant_id=tenant.id, name=name, normalized_name=normalized, category=category))


def bootstrap_tenant():
    tenant = ensure_default_tenant()
    seed_products(tenant)
    email = normalize_email(os.getenv("ADMIN_EMAIL"))
    password = os.getenv("ADMIN_PASSWORD", "")
    # Si no existen usuarios todavía, el primer administrador puede crearse desde /setup.
    # Las variables ADMIN_* siguen siendo compatibles para un bootstrap automático.
    if email and password and not User.query.filter_by(tenant_id=tenant.id, normalized_email=email).first():
        first_user = db.session.query(User.id).first() is None
        db.session.add(User(
            tenant_id=tenant.id,
            name=os.getenv("ADMIN_NAME", "Administrador"),
            email=email,
            normalized_email=email,
            password_hash=generate_password_hash(password),
            role="GROUP_ADMIN" if first_user else "ADMIN",
        ))
    db.session.commit()
    # Limpieza conservadora e idempotente: consolida solamente duplicados con
    # identificadores fuertes (RUC/registro, dominio o nombre normalizado exacto).
    # Se ejecuta antes de iniciar Gunicorn porque start.sh llama bootstrap-tenant.
    try:
        operations = ensure_group_operations()
        from .services.data_quality import consolidate_exact_duplicates
        for operation in operations.values():
            consolidate_exact_duplicates(operation.id)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("No se pudo ejecutar consolidación automática de duplicados: %s", exc)
    return tenant


def current_user():
    if hasattr(g, "radar_user"):
        return g.radar_user
    user_id = session.get("user_id") if has_request_context() else None
    user = db.session.get(User, user_id) if user_id else None
    if user and (user.status != "ACTIVE" or not user.tenant or user.tenant.status != "ACTIVE"):
        if has_request_context():
            session.clear()
        user = None
    g.radar_user = user
    return g.radar_user


def current_tenant():
    if hasattr(g, "radar_tenant"):
        return g.radar_tenant
    user = current_user()
    if not user:
        g.radar_tenant = ensure_default_tenant()
        return g.radar_tenant
    active_id = session.get("active_tenant_id")
    if user.role == "GROUP_ADMIN" and active_id:
        tenant = db.session.get(Tenant, active_id)
        if tenant and tenant.status == "ACTIVE":
            g.radar_tenant = tenant
            return tenant
    g.radar_tenant = user.tenant
    return g.radar_tenant


def has_permission(permission):
    if not current_app.config["AUTH_REQUIRED"]:
        return True
    user = current_user()
    allowed = ROLE_PERMISSIONS.get(user.role if user else "", set())
    return "*" in allowed or permission in allowed


def require_permission(permission):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not has_permission(permission):
                return jsonify(error="Permiso insuficiente", permission=permission), 403
            return function(*args, **kwargs)
        return wrapped
    return decorator

GROUP_OPERATIONS = {
    "puertas-brasil-py": {
        "name": "Puertas Brasil PY",
        "settings": {
            "brand_name": "Puertas Brasil PY", "brand_short": "Puertas Brasil", "market": "Paraguay", "language": "es-PY",
            "country_code": "PY", "theme": "puertas", "logo_file": "puertas-brasil-logo-oficial.jpg",
            "accent": "#0b7654", "default_country": "Paraguay", "sales_phone": "+595 986 986215",
            "sales_email": "gerenciacomercial@puertasbrasil.com.py", "website": "puertasbrasil.com.py",
            "subject_first_contact": "Puertas Brasil Paraguay | Primer Contacto", "radar_enabled": True,
        },
        "status": "ACTIVE",
    },
    "techdoors-br": {
        "name": "Tech Doors BR",
        "settings": {
            "brand_name": "Tech Doors BR", "brand_short": "Tech Doors", "market": "Brasil", "language": "pt-BR",
            "country_code": "BR", "theme": "techdoors", "logo_file": "techdoors-logo-oficial.jpg",
            "accent": "#ff6b00", "default_country": "Brasil", "sales_phone": "(11) 99746-8678",
            "sales_email": "", "website": "techdoors.com.br",
            "subject_first_contact": "Tech Doors | Primeiro Contato", "radar_enabled": True,
        },
        "status": "ACTIVE",
    },
    "premium-portas-br": {
        "name": "Premium Portas BR",
        "settings": {
            "brand_name": "Premium Portas e Portões", "brand_short": "Premium Portas", "market": "Brasil", "language": "pt-BR",
            "country_code": "BR", "theme": "premium", "default_country": "Brasil", "sales_phone": "(47) 9 9111 5057",
            "sales_email": "contato@premiumportas.com.br", "website": "premiumportas.com.br", "radar_enabled": False,
        },
        "status": "INSTITUTIONAL",
    },
}


def ensure_group_operations():
    """Garante as operações do HG Grupo sem duplicar o motor ou os dados."""
    created = []
    for slug, spec in GROUP_OPERATIONS.items():
        tenant = Tenant.query.filter_by(slug=slug).first()
        if not tenant:
            tenant = Tenant(name=spec["name"], slug=slug, status=spec.get("status", "ACTIVE"), settings=spec["settings"].copy())
            db.session.add(tenant); db.session.flush(); seed_products(tenant); created.append(tenant)
        else:
            merged = dict(spec["settings"]); merged.update(tenant.settings or {})
            tenant.settings = merged
    db.session.commit()
    return {t.slug: t for t in Tenant.query.filter(Tenant.slug.in_(list(GROUP_OPERATIONS))).all()}
