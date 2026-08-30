"""Fail fast when a production container has unsafe or incomplete settings."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse


TRUE_VALUES = {"1", "true", "yes", "on"}
PLACEHOLDERS = {"password", "postgres", "changeme", "change-me", "cambie-por-una-clave-segura"}


def enabled(name, default="false"):
    return os.getenv(name, default).strip().lower() in TRUE_VALUES


def looks_like_placeholder(value):
    normalized = value.strip().casefold()
    return normalized in PLACEHOLDERS or any(token in normalized for token in ("cambie", "defina-", "gere-uma-chave", "example"))


def main():
    errors = []
    warnings = []
    database_url = os.getenv("DATABASE_URL", "").strip()
    secret_key = os.getenv("SECRET_KEY", "").strip()
    data_dir = os.getenv("DATA_DIR", "/data").strip()
    admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    try:
        parsed = urlparse(database_url)
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"} or not parsed.hostname or not parsed.path.strip("/"):
        errors.append("DATABASE_URL debe apuntar a una base PostgreSQL completa.")
    elif looks_like_placeholder(parsed.password or ""):
        errors.append("DATABASE_URL contiene una contraseña de ejemplo.")

    if len(secret_key) < 32 or looks_like_placeholder(secret_key):
        errors.append("SECRET_KEY debe ser aleatoria y tener al menos 32 caracteres.")
    if not enabled("AUTH_REQUIRED", "true"):
        errors.append("AUTH_REQUIRED debe permanecer true en producción.")
    if not enabled("SESSION_COOKIE_SECURE", "true"):
        errors.append("SESSION_COOKIE_SECURE debe permanecer true en producción.")
    if enabled("ALLOW_WEB_SETUP"):
        errors.append("ALLOW_WEB_SETUP debe ser false en producción.")
    if not enabled("TRUST_PROXY"):
        warnings.append("TRUST_PROXY no está activo; habilítelo en Railway para reconocer HTTPS correctamente.")

    if not enabled("BOOTSTRAP_ADMIN_COMPLETE"):
        if "@" not in admin_email:
            errors.append("ADMIN_EMAIL es obligatorio para crear el administrador inicial sin exponer /setup.")
        if len(admin_password) < 12 or looks_like_placeholder(admin_password):
            errors.append("ADMIN_PASSWORD debe tener al menos 12 caracteres y no ser un valor de ejemplo.")
    elif admin_password:
        warnings.append("ADMIN_PASSWORD todavía está configurada; puede eliminarla después de confirmar el acceso inicial.")
    if not Path(data_dir).is_absolute():
        errors.append("DATA_DIR debe ser una ruta absoluta.")

    try:
        interval = int(os.getenv("COLLECTOR_INTERVAL_MINUTES", "60"))
        if interval < 15:
            warnings.append("COLLECTOR_INTERVAL_MINUTES será limitado a 15 minutos por la aplicación.")
    except ValueError:
        errors.append("COLLECTOR_INTERVAL_MINUTES debe ser un número entero.")
    for name, minimum in (("LOGIN_RATE_LIMIT", 3), ("LOGIN_RATE_WINDOW_SECONDS", 60), ("SESSION_LIFETIME_SECONDS", 300), ("GUNICORN_THREADS", 1), ("GUNICORN_TIMEOUT", 30), ("GUNICORN_MAX_REQUESTS", 100)):
        try:
            if int(os.getenv(name, str(minimum))) < minimum:
                errors.append(f"{name} debe ser un entero igual o superior a {minimum}.")
        except ValueError:
            errors.append(f"{name} debe ser un número entero.")

    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Configuración de producción validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
