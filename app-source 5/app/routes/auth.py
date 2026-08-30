from datetime import datetime, timezone
import os
import threading
import time

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import AuditLog, Tenant, User
from ..tenant import current_tenant, current_user, normalize_email, require_permission


auth_bp = Blueprint("auth", __name__)
_login_attempts = {}
_login_attempts_lock = threading.Lock()
_login_window = max(60, int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", "900")))
_login_limit = max(3, int(os.getenv("LOGIN_RATE_LIMIT", "10")))


def _login_keys(email):
    return (f"ip:{request.remote_addr or 'unknown'}", f"email:{email}")


def _login_is_blocked(keys):
    cutoff = time.monotonic() - _login_window
    with _login_attempts_lock:
        for key in list(_login_attempts):
            recent = [stamp for stamp in _login_attempts[key] if stamp >= cutoff]
            if recent:
                _login_attempts[key] = recent
            else:
                _login_attempts.pop(key, None)
        return any(len(_login_attempts.get(key, ())) >= _login_limit for key in keys)


def _record_login_failure(keys):
    now = time.monotonic()
    with _login_attempts_lock:
        for key in keys:
            _login_attempts.setdefault(key, []).append(now)


def _clear_login_identity(email):
    with _login_attempts_lock:
        _login_attempts.pop(f"email:{email}", None)


def _has_any_user():
    return db.session.query(User.id).first() is not None


@auth_bp.get("/setup")
def setup_page():
    if _has_any_user():
        return redirect(url_for("auth.login_page"))
    if not current_app.config["ALLOW_WEB_SETUP"]:
        return render_template("login.html", setup_mode=False, error="La configuración web inicial está desactivada. Configure el administrador mediante las variables ADMIN_*.", default_workspace=current_app.config["DEFAULT_TENANT_SLUG"]), 503
    return render_template("login.html", setup_mode=True, default_workspace=current_app.config["DEFAULT_TENANT_SLUG"])


@auth_bp.post("/setup")
def setup_submit():
    if _has_any_user():
        return redirect(url_for("auth.login_page"))
    if not current_app.config["ALLOW_WEB_SETUP"]:
        return jsonify(error="Configuración web inicial desactivada"), 403
    data = request.form
    name = (data.get("name") or "").strip()
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""
    if len(name) < 2 or "@" not in email or len(password) < 12:
        return render_template(
            "login.html", setup_mode=True, error="Complete nombre, correo válido y una contraseña de al menos 12 caracteres.",
            default_workspace=current_app.config["DEFAULT_TENANT_SLUG"],
        ), 400
    tenant = current_tenant()
    user = User(
        tenant_id=tenant.id, name=name, email=email, normalized_email=email,
        password_hash=generate_password_hash(password), role="GROUP_ADMIN", status="ACTIVE",
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(AuditLog(tenant_id=tenant.id, user_id=user.id, action="INITIAL_ADMIN_CREATED", entity_type="USER", entity_id=str(user.id)))
    db.session.commit()
    session.clear(); session.permanent = True; session["user_id"] = user.id
    return redirect(url_for("web.group_home"))


@auth_bp.get("/login")
def login_page():
    if not _has_any_user():
        return redirect(url_for("auth.setup_page"))
    if current_user():
        return redirect(url_for("web.group_home" if current_user().role == "GROUP_ADMIN" else "web.index"))
    return render_template("login.html", setup_mode=False, default_workspace=current_app.config["DEFAULT_TENANT_SLUG"])


def _login():
    data = request.get_json(silent=True) if request.is_json else request.form
    email = normalize_email((data or {}).get("email"))
    password = (data or {}).get("password", "")
    rate_keys = _login_keys(email)
    if _login_is_blocked(rate_keys):
        return None
    candidates = User.query.join(Tenant).filter(
        User.normalized_email == email, User.status == "ACTIVE", Tenant.status == "ACTIVE",
    ).all()
    user = next((u for u in candidates if check_password_hash(u.password_hash, password)), None)
    if not user:
        _record_login_failure(rate_keys)
        return None
    _clear_login_identity(email)
    session.clear(); session.permanent = True; session["user_id"] = user.id
    if user.role == "GROUP_ADMIN":
        session["active_tenant_id"] = user.tenant_id
    user.last_login_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="LOGIN", entity_type="USER", entity_id=str(user.id)))
    db.session.commit()
    return user


@auth_bp.post("/login")
def login_form():
    user = _login()
    if not user:
        return render_template("login.html", setup_mode=False, error="Correo o contraseña inválidos", default_workspace=current_app.config["DEFAULT_TENANT_SLUG"]), 401
    return redirect(url_for("web.group_home" if user.role == "GROUP_ADMIN" else "web.index"))


@auth_bp.post("/api/auth/login")
def login_api():
    user = _login()
    if not user:
        return jsonify(error="Credenciales inválidas"), 401
    return jsonify(id=user.id, name=user.name, email=user.email, role=user.role, tenantId=user.tenant_id)


@auth_bp.post("/logout")
def logout_form():
    session.clear()
    return redirect(url_for("auth.login_page"))


@auth_bp.post("/api/auth/logout")
def logout_api():
    session.clear()
    return jsonify(status="ok")


@auth_bp.get("/api/auth/session")
def auth_session():
    user = current_user(); tenant = current_tenant()
    return jsonify(
        authenticated=bool(user),
        user={"id": user.id, "name": user.name, "email": user.email, "role": user.role} if user else None,
        tenant={"id": tenant.id, "name": tenant.name, "slug": tenant.slug},
    )


@auth_bp.get("/api/admin/users")
@require_permission("MANAGE_USERS")
def admin_users_list():
    tenant = current_tenant()
    rows = User.query.filter_by(tenant_id=tenant.id).order_by(User.status.asc(), User.name.asc()).all()
    return jsonify([{
        "id": u.id, "name": u.name, "email": u.email, "role": u.role, "status": u.status,
        "lastLoginAt": u.last_login_at.isoformat() if u.last_login_at else None,
        "createdAt": u.created_at.isoformat() if u.created_at else None,
    } for u in rows])


@auth_bp.post("/api/admin/users")
@require_permission("MANAGE_USERS")
def admin_users_create():
    tenant = current_tenant(); actor = current_user(); data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip(); email = normalize_email(data.get("email")); password = data.get("password") or ""
    role = str(data.get("role") or "SALES").upper()
    if role not in {"ADMIN", "MANAGER", "SALES", "VIEWER"}:
        return jsonify(error="Rol inválido"), 400
    if len(name) < 2 or "@" not in email or len(password) < 12:
        return jsonify(error="Nombre, correo válido y contraseña de al menos 12 caracteres son obligatorios"), 400
    if User.query.filter_by(tenant_id=tenant.id, normalized_email=email).first():
        return jsonify(error="Ya existe un usuario con ese correo"), 409
    row = User(tenant_id=tenant.id, name=name, email=email, normalized_email=email, password_hash=generate_password_hash(password), role=role, status="ACTIVE")
    db.session.add(row); db.session.flush()
    db.session.add(AuditLog(tenant_id=tenant.id, user_id=actor.id if actor else None, action="USER_CREATED", entity_type="USER", entity_id=str(row.id), details={"role": role, "email": email}))
    db.session.commit()
    return jsonify(id=row.id, name=row.name, email=row.email, role=row.role, status=row.status), 201


@auth_bp.patch("/api/admin/users/<int:user_id>")
@require_permission("MANAGE_USERS")
def admin_users_update(user_id):
    tenant = current_tenant(); actor = current_user(); data = request.get_json(silent=True) or {}
    row = User.query.filter_by(id=user_id, tenant_id=tenant.id).first_or_404()
    if "name" in data and str(data["name"]).strip(): row.name = str(data["name"]).strip()
    if "role" in data:
        role = str(data["role"]).upper()
        if role not in {"ADMIN", "MANAGER", "SALES", "VIEWER"}: return jsonify(error="Rol inválido"), 400
        if row.id == actor.id and role not in {"ADMIN", "GROUP_ADMIN"}: return jsonify(error="No puede retirar su propio acceso de administrador"), 400
        row.role = role
    if "status" in data:
        status = str(data["status"]).upper()
        if status not in {"ACTIVE", "DISABLED"}: return jsonify(error="Estado inválido"), 400
        if row.id == actor.id and status != "ACTIVE": return jsonify(error="No puede desactivar su propio usuario"), 400
        row.status = status
    if data.get("password"):
        if len(str(data["password"])) < 12: return jsonify(error="La contraseña debe tener al menos 12 caracteres"), 400
        row.password_hash = generate_password_hash(str(data["password"]))
    db.session.add(AuditLog(tenant_id=tenant.id, user_id=actor.id if actor else None, action="USER_UPDATED", entity_type="USER", entity_id=str(row.id), details={"role": row.role, "status": row.status}))
    db.session.commit()
    return jsonify(id=row.id, name=row.name, email=row.email, role=row.role, status=row.status)
