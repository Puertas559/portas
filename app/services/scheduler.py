import os
import threading
import time
from datetime import datetime, timedelta, timezone

from ..models import CollectorRun
from .collector import run_collector

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler(app):
    global _scheduler_started
    if os.getenv("COLLECTOR_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    interval = max(5, int(os.getenv("COLLECTOR_INTERVAL_MINUTES", "5")))

    def loop():
        time.sleep(20)
        while True:
            try:
                with app.app_context():
                    last = CollectorRun.query.filter_by(status="COMPLETED").order_by(CollectorRun.finished_at.desc()).first()
                    due = not last or not last.finished_at or last.finished_at < datetime.now(timezone.utc) - timedelta(minutes=interval)
                    if due:
                        run_collector()
            except Exception:
                app.logger.exception("Error en el programador de captación automática")
            time.sleep(60)

    threading.Thread(target=loop, name="prospecting-collector", daemon=True).start()
