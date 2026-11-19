"""
apps/followups/nightly.py — the scheduled follow-up pipeline (Top-10 C09). Before this, generation and
auto-close only ran when someone pressed a button or ran generate_followup_tasks by hand, so the queue
went stale (May 2026; again after the 2026-11-01 catch-up batch).

Daily, in this order (local DB only — reads synced PurchaseHistory, never SOFTECH, sends nothing):
  1. ERP auto-close: an open task whose PIC bought the same item after the task's sale → auto_closed
     (services.auto_close_followup_tasks_from_erp, looking back AUTOCLOSE_LOOKBACK_DAYS).
  2. Stale rule: open generated refill / chronic tasks more than STALE_AFTER_DAYS past due and open at
     least that long → missed (services.escalate_overdue_tasks; call-list and pinned tasks excluded).
  3. Generate the newly due refill tasks (services.generate_followup_tasks_bulk; a sale never makes a
     second task, so a re-run adds nothing).
One AuditLog row per run with the counts. Guard: a non-blocking Postgres advisory lock, so a second
scheduler process or a hand run at the same moment skips instead of doubling the work.

Settings (getattr defaults): FOLLOWUPS_NIGHTLY_ENABLED (True), FOLLOWUPS_STALE_AFTER_DAYS (3 — the rule
the help already documents), FOLLOWUPS_AUTOCLOSE_LOOKBACK_DAYS (45), FOLLOWUPS_GENERATE_GRACE_DAYS (14).
"""
import logging

from django.conf import settings

logger = logging.getLogger('elrezeiky.followups')

_LOCK_KEY = 7_301_102          # refill_reminders uses 7_301_101


def _cfg(name, default):
    return getattr(settings, f'FOLLOWUPS_{name}', default)


def enabled() -> bool:
    return bool(_cfg('NIGHTLY_ENABLED', True))


def run(*, dry_run=False, force=False) -> dict:
    """The daily pipeline. dry_run counts without saving. force runs even when the switch is off."""
    from apps.vouchers.coupon_dashboard import pg_lock      # shared non-blocking advisory lock
    from . import services

    out = {'enabled': enabled(), 'dry_run': dry_run}
    if not (out['enabled'] or force):
        return out
    with pg_lock(_LOCK_KEY) as got:
        if not got:
            out['busy'] = True
            return out
        lookback = int(_cfg('AUTOCLOSE_LOOKBACK_DAYS', 45))
        stale = int(_cfg('STALE_AFTER_DAYS', 3))
        out['auto_closed'] = services.auto_close_followup_tasks_from_erp(
            since_minutes=lookback * 24 * 60, dry_run=dry_run)
        out['missed'] = services.escalate_overdue_tasks(overdue_days=stale, dry_run=dry_run)['escalated']
        out['created'] = services.generate_followup_tasks_bulk(
            dry_run=dry_run, grace_days=int(_cfg('GENERATE_GRACE_DAYS', 14)))
    if not dry_run and (out['auto_closed'] or out['missed'] or out['created']):
        from apps.audit.models import AuditLog
        AuditLog.log('followup_nightly', new_data=out,
                     note=(f'متابعة يومية: {out["created"]} جديدة · {out["auto_closed"]} أُغلقت بالبيع · '
                           f'{out["missed"]} فائتة'))
    logger.info('[followups_nightly] %s', out)
    return out
