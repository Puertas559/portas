from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import AuditLog, Tenant, User
from ..tenant import current_tenant, current_user, normalize_email


auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/login")
def login_page():
    if current_user():
        return redirect(url_for("web.index"))
    return render_template("login.html", default_workspace=current_app.config["DEFAULT_TENANT_SLUG"])


def _login():
    data = request.get_json(silent=True) if request.is_json else request.form
    email = normalize_email((data or {}).get("email"))
    workspace = ((data or {}).get("workspace") or current_app.config["DEFAULT_TENANT_SLUG"]).strip().casefold()
    user = User.query.join(Tenant).filter(
        User.normalized_email == email, User.status == "ACTIVE", Tenant.slug == workspace, Tenant.status == "ACTIVE",
    ).first()
    if not user or not check_password_hash(user.password_hash, (data or {}).get("password", "")):
        return None
    session.clear()
    session["user_id"] = user.id
    user.last_login_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="LOGIN", entity_type="USER", entity_id=str(user.id)))
    db.session.commit()
    return user


@auth_bp.post("/login")
def login_form():
    user = _login()
    if not user:
        return render_template("login.html", error="Workspace, correo o contraseña inválidos", default_workspace=current_app.config["DEFAULT_TENANT_SLUG"]), 401
    return redirect(url_for("web.index"))


@auth_bp.post("/api/auth/login")
def login_api():
    user = _login()
    if not user:
        return jsonify(error="Credenciales inválidas"), 401
    return jsonify(id=user.id, name=user.name, email=user.email, role=user.role, tenantId=user.tenant_id)


@auth_bp.post("/api/auth/logout")
def logout_api():
    session.clear()
    return jsonify(status="ok")


@auth_bp.get("/api/auth/session")
def auth_session():
    user = current_user()
    tenant = current_tenant()
    return jsonify(
        authenticated=bool(user),
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role} if user else None,
        tenant={"id": tenant.id, "name": tenant.name, "slug": tenant.slug},
    )
