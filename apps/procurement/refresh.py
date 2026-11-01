"""
apps/procurement/refresh.py — keep the saved purchases (PurchaseLine) current.

Owner 2026-10-24: purchases stopped at 18-10. The refresh was ONE cron at 06:45 with a
30-minute grace, and the machine running the scheduler is often asleep / off then (no log
lines at all 05:00–10:00 on most days) — so the day was simply skipped; the 18-10 manual run
"took 5.5 h" only because the machine slept in the middle of it.

Now:
  • catch-up: the scheduler checks every 30 minutes and refreshes when the last successful
    run is older than DUE_AFTER_HOURS, pulling every day since that run (+ a margin);
  • an on-demand refresh (the «⟳ المشتريات» button on /supply) — same function, background
    thread, never two at once; a 'running' row older than STALE_RUNNING_HOURS is a dead
    process, not a running one.

SOFTECH: SELECT only (the engine's absolute rule). Writes PG only.
"""
import logging
import threading
from datetime import timedelta

from django.db import connections
from django.utils import timezone

logger = logging.getLogger(__name__)

DUE_AFTER_HOURS = 20          # a day's refresh is due once the last success is this old
STALE_RUNNING_HOURS = 3       # an older 'running' row is a dead process (machine slept / killed)
MARGIN_DAYS = 2               # re-pull this many days before the last success (late entries)
MIN_DAYS, MAX_DAYS = 3, 60
FIRST_DAYS = 14               # no successful run yet

_lock = threading.Lock()


def last_success():
    from .models import ProcurementEngineRun
    return ProcurementEngineRun.objects.filter(status='success').order_by('-finished_at').first()


def running_run():
    from .models import ProcurementEngineRun
    since = timezone.now() - timedelta(hours=STALE_RUNNING_HOURS)
    return ProcurementEngineRun.objects.filter(status='running', started_at__gte=since).order_by('-started_at').first()


def catchup_days(now=None) -> int:
    """Days to pull so nothing between the last success and now is missed."""
    last = last_success()
    if last is None:
        return FIRST_DAYS
    now = now or timezone.now()
    gap = (timezone.localdate(now) - timezone.localdate(last.started_at)).days
    return max(MIN_DAYS, min(MAX_DAYS, gap + MARGIN_DAYS))


def is_due(now=None) -> bool:
    last = last_success()
    if last is None or last.finished_at is None:
        return True
    return (now or timezone.now()) - last.finished_at > timedelta(hours=DUE_AFTER_HOURS)


def run_now(triggered_by: str, days: int | None = None):
    """Run the engine in THIS thread (scheduler / command). None if one is already running."""
    from .engine import run_procurement_engine
    if not _lock.acquire(blocking=False):
        return None
    try:
        if running_run() is not None:
            return None
        days = days or catchup_days()
        logger.info('[procurement refresh] %s — pulling the last %s days', triggered_by, days)
        run = run_procurement_engine(lookback_days=days, triggered_by=triggered_by[:50])
        if getattr(run, 'status', '') == 'success':
            try:                                    # P-31: check the new receipts against the sent need sheets
                from .receipt_check import run_check
                run_check()
            except Exception:
                logger.exception('[procurement refresh] receipt check failed')
        return run
    finally:
        _lock.release()


def start_background(triggered_by: str) -> bool:
    """The screen's button: start a catch-up run in a background thread. False if busy."""
    if running_run() is not None or _lock.locked():
        return False

    def _worker():
        try:
            run_now(triggered_by)
        except Exception:
            logger.exception('[procurement refresh] on-demand run failed')
        finally:
            connections.close_all()

    threading.Thread(target=_worker, name='procurement-refresh', daemon=True).start()
    return True


def scheduled_tick():
    """Every 30 min from the scheduler: refresh only when due (catch-up after sleep/off)."""
    if not is_due():
        return None
    return run_now('scheduler')


def freshness() -> dict:
    """For the freshness strip: when purchases were last refreshed and up to which date."""
    from django.db.models import Max
    from .models import PurchaseLine
    last = last_success()
    at = last.finished_at if last else None
    run = running_run()
    through = PurchaseLine.objects.aggregate(m=Max('doc_date'))['m']
    return {'at': at, 'data_through': through, 'running': run is not None,
            'progress': (run.progress or {}) if run else None,
            'started_at': run.started_at if run else None}
