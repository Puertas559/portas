import os
from pathlib import Path

from flask import Flask
from .extensions import db, migrate


def _database_url():
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url or "sqlite:////tmp/puertas-radar-dev.db"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "development-only-change-me"),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        DATA_DIR=os.getenv("DATA_DIR", "/data"),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)

    from .routes.api import api_bp
    from .routes.web import web_bp
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    return app
