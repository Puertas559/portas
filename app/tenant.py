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
        db.session.add(User(
            tenant_id=tenant.id,
            name=os.getenv("ADMIN_NAME", "Administrador"),
            email=email,
            normalized_email=email,
            password_hash=generate_password_hash(password),
            role="ADMIN",
        ))
    db.session.commit()
    return tenant


def current_user():
    if hasattr(g, "radar_user"):
        return g.radar_user
    user_id = session.get("user_id") if has_request_context() else None
    g.radar_user = db.session.get(User, user_id) if user_id else None
    return g.radar_user


def current_tenant():
    if hasattr(g, "radar_tenant"):
        return g.radar_tenant
    user = current_user()
    g.radar_tenant = user.tenant if user else ensure_default_tenant()
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
