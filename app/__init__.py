import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import click
from flask import Flask, g, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from .extensions import db, migrate


def _database_url():
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url or "sqlite:////tmp/puertas-radar-dev.db"



def _secret_key(data_dir=None):
    configured=os.getenv("SECRET_KEY")
    if configured:
        return configured
    data_dir=Path(data_dir or os.getenv("DATA_DIR","/data"))
    try:
        data_dir.mkdir(parents=True,exist_ok=True)
        secret_file=data_dir / ".radar_secret"
        if secret_file.exists():
            value=secret_file.read_text().strip()
            if value: return value
        value=secrets.token_urlsafe(64)
        secret_file.write_text(value)
        return value
    except Exception:
        return secrets.token_urlsafe(64)


def create_app(test_config=None):
    app = Flask(__name__)
    initial_data_dir = (test_config or {}).get("DATA_DIR", os.getenv("DATA_DIR", "/data"))
    initial_secret = (test_config or {}).get("SECRET_KEY")
    if not initial_secret:
        initial_secret = "test-only-secret-key-not-for-production" if (test_config or {}).get("TESTING") else _secret_key(initial_data_dir)
    app.config.update(
        SECRET_KEY=initial_secret,
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        DATA_DIR=initial_data_dir,
        AUTH_REQUIRED=os.getenv("AUTH_REQUIRED", "true").lower() in {"1", "true", "yes"},
        DEFAULT_TENANT_NAME=os.getenv("DEFAULT_TENANT_NAME", "Puertas Brasil PY"),
        DEFAULT_TENANT_SLUG=os.getenv("DEFAULT_TENANT_SLUG", "puertas-brasil-py"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"},
        PERMANENT_SESSION_LIFETIME=int(os.getenv("SESSION_LIFETIME_SECONDS", "43200")),
        SESSION_REFRESH_EACH_REQUEST=True,
        ALLOW_WEB_SETUP=os.getenv("ALLOW_WEB_SETUP", "false").lower() in {"1", "true", "yes"},
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024))),
    )
    if test_config:
        app.config.update(test_config)
    if app.config.get("TESTING") and (not test_config or "AUTH_REQUIRED" not in test_config):
        app.config["AUTH_REQUIRED"] = False
    if os.getenv("TRUST_PROXY", "false").lower() in {"1", "true", "yes"}:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)

    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.web import web_bp
    from .routes.hub import hub_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(hub_bp)

    @app.before_request
    def prepare_security_context():
        g.csp_nonce = secrets.token_urlsafe(18)

    @app.context_processor
    def security_template_context():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.before_request
    def enforce_authentication():
        if not app.config["AUTH_REQUIRED"]:
            return None
        if request.endpoint in {"auth.login_page", "auth.login_form", "auth.login_api", "auth.auth_session", "auth.setup_page", "auth.setup_submit", "api.health", "health", "static", "web.service_worker"}:
            return None
        from .tenant import current_user
        if current_user():
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("Origin")
                if origin and urlparse(origin).netloc != request.host:
                    return jsonify(error="Origen de solicitud inválido"), 403
                fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
                if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
                    return jsonify(error="Contexto de solicitud inválido"), 403
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Autenticación requerida"), 401
        return redirect(url_for("auth.login_page"))

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        nonce = getattr(g, "csp_nonce", "")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "img-src 'self' data: https:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith(("/api/", "/login", "/setup", "/group", "/hub")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.cli.command("collect")
    def collect_command():
        """Ejecuta una captación automática una sola vez."""
        from .services.collector import run_collector
        run = run_collector()
        click.echo(f"Captación finalizada: {run.items_scanned} elementos, {run.signals_created} señales nuevas")

    @app.cli.command("scan-hub-events")
    def scan_hub_events_command():
        """Busca eventos nas fontes HUB ativas e envia candidatos à triagem."""
        from .services.hub_events import run_hub_event_scan
        stats = run_hub_event_scan()
        click.echo(f"HUB Eventos: {stats['sources']} fontes, {stats['found']} links, {stats['created']} novos candidatos")

    @app.cli.command("bootstrap-tenant")
    def bootstrap_tenant_command():
        """Crea el tenant inicial, catálogo y administrador configurado."""
        from .tenant import bootstrap_tenant
        tenant = bootstrap_tenant()
        click.echo(f"Tenant preparado: {tenant.slug}")

    if not app.config.get("TESTING"):
        from .services.scheduler import start_scheduler
        start_scheduler(app)
    return app
