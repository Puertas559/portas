import os
import sys
from urllib.parse import urlparse


def truthy(name, default="false"):
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main():
    production = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("ENV", "").lower() == "production"
    errors = 0
    if production:
        if not truthy("AUTH_REQUIRED", "true"):
            errors += fail("AUTH_REQUIRED deve permanecer true em produção.")
        if not truthy("SESSION_COOKIE_SECURE", "true"):
            errors += fail("SESSION_COOKIE_SECURE deve permanecer true em produção.")
        secret = os.getenv("SECRET_KEY", "")
        if secret and (len(secret) < 32 or secret.lower().startswith(("change", "cambie", "secret"))):
            errors += fail("SECRET_KEY configurada deve ter ao menos 32 caracteres aleatórios em produção.")
        elif not secret:
            print("WARNING: SECRET_KEY não configurada; será usada a chave persistida em DATA_DIR.")
        dburl = os.getenv("DATABASE_URL", "")
        if not dburl or not dburl.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            errors += fail("DATABASE_URL PostgreSQL é obrigatória em produção.")
        # If bootstrap credentials are provided, validate them; otherwise existing DB users are accepted.
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        if admin_password and len(admin_password) < 12:
            errors += fail("ADMIN_PASSWORD, quando configurada, deve ter ao menos 12 caracteres.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
