import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..extensions import db
from ..models import CollectorRun
from .collector import run_collector

_scheduler_started = False
_scheduler_lock = threading.Lock()
ADVISORY_LOCK_ID = 781245902


def _acquire_database_lease():
    """Avoid duplicate collector executions when Gunicorn runs multiple workers."""
    try:
        if db.engine.dialect.name == "postgresql":
            return bool(db.session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_ID}).scalar())
    except Exception:
        db.session.rollback()
        return False
    return True


def _release_database_lease():
    try:
        if db.engine.dialect.name == "postgresql":
            db.session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_ID})
            db.session.commit()
    except Exception:
        db.session.rollback()


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
    last_hub_scan = [None]

    def loop():
        time.sleep(20)
        while True:
            acquired = False
            try:
                with app.app_context():
                    acquired = _acquire_database_lease()
                    if acquired:
                        last = CollectorRun.query.order_by(CollectorRun.finished_at.desc()).first()
                        due = not last or not last.finished_at or last.finished_at < datetime.now(timezone.utc) - timedelta(minutes=interval)
                        running = CollectorRun.query.filter_by(status="RUNNING").filter(
                            CollectorRun.started_at > datetime.now(timezone.utc) - timedelta(minutes=max(interval, 30))
                        ).first()
                        if collector_enabled and due and not running:
                            run_collector()
                        if hub_enabled:
                            hub_due = not last_hub_scan[0] or last_hub_scan[0] < datetime.now(timezone.utc) - timedelta(hours=hub_interval_hours)
                            if hub_due:
                                from .hub_events import run_hub_event_scan
                                run_hub_event_scan()
                                last_hub_scan[0] = datetime.now(timezone.utc)
            except Exception:
                app.logger.exception("Error en el programador de captación automática")
            finally:
                if acquired:
                    with app.app_context():
                        _release_database_lease()
            time.sleep(60)

    threading.Thread(target=loop, name="prospecting-collector-fallback", daemon=True).start()
