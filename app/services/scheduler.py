import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..extensions import db
from ..models import CollectorRun, Tenant
from .collector import run_collector

_scheduler_started = False
_scheduler_lock = threading.Lock()
ADVISORY_LOCK_ID = 781245902


def _acquire_database_lease():
    """Avoid duplicate collector executions when Gunicorn runs multiple workers."""
    connection = None
    try:
        if db.engine.dialect.name == "postgresql":
            connection = db.engine.connect()
            acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_ID}).scalar())
            if acquired:
                return connection
            connection.close()
            return None
    except Exception:
        if connection is not None:
            connection.close()
        db.session.rollback()
        return False
    return True


def _release_database_lease(lease):
    try:
        if db.engine.dialect.name == "postgresql" and lease is not True:
            lease.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_ID})
    except Exception:
        db.session.rollback()
    finally:
        if lease is not True:
            lease.close()


def start_scheduler(app):
    global _scheduler_started
    collector_enabled = os.getenv("COLLECTOR_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    hub_enabled = os.getenv("HUB_EVENTS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    if not collector_enabled and not hub_enabled:
        return
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    # Five-minute polling creates noise for industrial projects. Default is now 60 minutes;
    # a separate process/cron can call /api/collector/run or run_collector for production scheduling.
    interval = max(15, int(os.getenv("COLLECTOR_INTERVAL_MINUTES", "60")))
    hub_interval_hours = max(1, int(os.getenv("HUB_EVENTS_INTERVAL_HOURS", "12")))
    last_hub_scan = {}

    def loop():
        time.sleep(20)
        while True:
            lease = None
            try:
                with app.app_context():
                    lease = _acquire_database_lease()
                    if lease:
                        now = datetime.now(timezone.utc)
                        tenants = Tenant.query.filter_by(status="ACTIVE").all()
                        for tenant in tenants:
                            if not (tenant.settings or {}).get("radar_enabled", True):
                                continue
                            last = CollectorRun.query.filter_by(tenant_id=tenant.id).order_by(CollectorRun.finished_at.desc()).first()
                            due = not last or not last.finished_at or last.finished_at < now - timedelta(minutes=interval)
                            running = CollectorRun.query.filter_by(tenant_id=tenant.id, status="RUNNING").filter(
                                CollectorRun.started_at > now - timedelta(minutes=max(interval, 30))
                            ).first()
                            if collector_enabled and due and not running:
                                run_collector(tenant.id)
                            hub_due = not last_hub_scan.get(tenant.id) or last_hub_scan[tenant.id] < now - timedelta(hours=hub_interval_hours)
                            if hub_enabled and hub_due:
                                from .hub_events import run_hub_event_scan
                                run_hub_event_scan(tenant.id)
                                last_hub_scan[tenant.id] = now
            except Exception:
                app.logger.exception("Error en el programador de captación automática")
            finally:
                if lease:
                    with app.app_context():
                        _release_database_lease(lease)
            time.sleep(60)

    threading.Thread(target=loop, name="prospecting-collector-fallback", daemon=True).start()
