"""
apps/delivery/stuck_close.py — C21 (audit doc 08, part of P-48): close delivery orders that are stuck
open on our board although SOFTECH already finished them.

Why orders get stuck: the CRM sync (sync_crm_orders) reads piccrmorders changes from the last few
minutes only. When a status change lands while the sync is down or a branch is offline, our mirror
never hears about it, and the order stays «جاهز» / «في الطريق» here for ever. A read-only probe on
2026-11-20 found 800 orders open for more than a day; SOFTECH itself said 257 of them were delivered
(orderstatus 90) and 35 cancelled (100).

The rule is deterministic — SOFTECH's own status decides, nothing is guessed:

    an order is a candidate when      it is not in a final state here
                                       and it was ordered more than `min_age_hours` ago
                                       and it carries a SOFTECH key (crm branch + crm order no)
    SOFTECH orderstatus 90 (delivered) → our status becomes «مغلق» (closed)
    SOFTECH orderstatus 100 (cancelled)→ our status becomes «ملغى» (cancelled)
    anything else / not found / node down → left open: a real exception for a person to look at
    an order with a cash-collection row → never touched (the cash is reconciled by a person)

Safety:
  * SOFTECH is only READ (config/sybase.py read-only connections, keyed (crmbranchcode, crmorderno)).
  * The switch `delivery_stuck_autoclose_enabled` is OFF by default; while it is off every run is a
    dry run that only stores the list of what it WOULD close (shown on /delivery, and by
    `manage.py delivery_stuck_autoclose`).
  * Each close is a conditional UPDATE (`filter(pk=…, status=<status we saw>)`), so a person moving
    the order at the same moment wins and a second, concurrent run closes nothing twice.
  * Each close writes a DeliveryStatusLog row (source «نظام», who = system, why = the SOFTECH status).
  * Cash-collection rows and amounts are never read for writing, never changed.

Owner questions (PR body): the age threshold, whether 90 should become «مُسلَّم» instead of «مغلق»,
and the SLA minutes used to fill sla_due_at.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.delivery')

SWITCH_KEY = 'delivery_stuck_autoclose_enabled'
AGE_KEY = 'delivery_stuck_autoclose_min_age_hours'
SLA_KEY = 'delivery_sla_minutes'
LAST_RUN_KEY = 'delivery_stuck_autoclose_last_run'

DEFAULT_MIN_AGE_HOURS = 24
DEFAULT_SLA_MINUTES = 0        # 0 = do not fill sla_due_at until the owner picks a number
SOFTECH_DELIVERED = 90
SOFTECH_CANCELLED = 100
CHUNK = 200
MAX_STORED = 2000              # rows kept in the last-run record (the board shows them)

VERDICT_CLOSE = 'close'
VERDICT_CANCEL = 'cancel'
VERDICT_OPEN = 'still_open'     # SOFTECH says it is still running → a real exception
VERDICT_NOT_FOUND = 'not_found'
VERDICT_CASH = 'cash_hold'      # has a cash-collection row → a person closes it
VERDICT_NO_KEY = 'no_key'       # created here, no SOFTECH order number to check


def _setting(key, default):
    try:
        from apps.config.models import SystemSetting
        return SystemSetting.get(key, default)
    except Exception:   # a missing settings table must not stop the board
        return default


def is_enabled() -> bool:
    val = _setting(SWITCH_KEY, False)
    if isinstance(val, str):
        return val.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(val)


def min_age_hours() -> int:
    try:
        return max(1, int(_setting(AGE_KEY, DEFAULT_MIN_AGE_HOURS)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_AGE_HOURS


def sla_minutes() -> int:
    try:
        return max(0, int(_setting(SLA_KEY, DEFAULT_SLA_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_SLA_MINUTES


def open_statuses():
    from apps.delivery.models import DeliveryOrder
    terminal = DeliveryOrder.TERMINAL_STATUSES | {DeliveryOrder.STATUS_RETURNED, DeliveryOrder.STATUS_FAILED,
                                                  DeliveryOrder.STATUS_PARTIAL}
    return [s for s, _ in DeliveryOrder.STATUS_CHOICES if s not in terminal]


def stuck_queryset(hours=None, now=None):
    """Open orders older than `hours` (the board's «عالقة» list), oldest first."""
    from apps.delivery.models import DeliveryOrder
    now = now or timezone.now()
    cutoff = now - timedelta(hours=hours if hours is not None else min_age_hours())
    return DeliveryOrder.objects.filter(status__in=open_statuses(), ordered_at__lt=cutoff).order_by('ordered_at')


# ── SOFTECH read (read-only) ────────────────────────────────────────────────────────────────────

_SQL = ('SELECT crmorderno, orderstatus FROM piccrmorders '
        'WHERE crmbranchcode = ? AND crmorderno IN ({marks})')


def _read_statuses(cursor, crm_branch, numbers, out):
    for i in range(0, len(numbers), CHUNK):
        chunk = numbers[i:i + CHUNK]
        cursor.execute(_SQL.format(marks=','.join('?' * len(chunk))), [crm_branch] + chunk)
        for no, st in cursor.fetchall():
            out[(crm_branch, int(no))] = None if st is None else int(st)


def fetch_softech_statuses(keys):
    """{(crm_branch, crm_order_no): orderstatus} for the keys SOFTECH knows. HQ first (it holds the
    call-centre orders and most branch ones); a branch order HQ does not hold is asked of its own
    branch server. A node that does not answer leaves its keys out (they stay open)."""
    from config.sybase import get_branch_connection, get_sybase_connection
    from apps.branches.models import Branch

    by_branch = {}
    for br, no in keys:
        by_branch.setdefault(br, []).append(int(no))
    found = {}
    try:
        conn = get_sybase_connection()
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 0')
            for br, nos in by_branch.items():
                _read_statuses(cur, br, sorted(set(nos)), found)
        finally:
            conn.close()
    except Exception as exc:   # HQ down: nothing is closed this run
        logger.warning('[stuck-close] HQ read failed: %s', exc)

    missing = {}
    for br, nos in by_branch.items():
        if br == '100':
            continue
        left = sorted({n for n in nos if (br, n) not in found})
        if left:
            missing[br] = left
    if missing:
        nodes = {str(b.softech_branch_id): b for b in Branch.objects.live().filter(
            softech_branch_id__in=list(missing), db_host__gt='', is_active=True)}
        for br, nos in missing.items():
            node = nodes.get(br)
            if node is None:
                continue
            try:
                conn = get_branch_connection(node.db_host, node.db_port, node.db_name)
                try:
                    cur = conn.cursor()
                    cur.execute('SET ROWCOUNT 0')
                    _read_statuses(cur, br, nos, found)
                finally:
                    conn.close()
            except Exception as exc:   # offline branch: its orders stay open
                logger.warning('[stuck-close] branch %s read failed: %s', br, exc)
    return found


# ── the rule ────────────────────────────────────────────────────────────────────────────────────

def verdict(order_row, softech_status, has_cash) -> str:
    """Pure rule (tested on its own): what to do with one stuck order."""
    if has_cash:
        return VERDICT_CASH
    if not order_row.get('softech_crm_order_no'):
        return VERDICT_NO_KEY
    if softech_status is _MISSING:
        return VERDICT_NOT_FOUND
    if softech_status == SOFTECH_DELIVERED:
        return VERDICT_CLOSE
    if softech_status == SOFTECH_CANCELLED:
        return VERDICT_CANCEL
    return VERDICT_OPEN


_MISSING = object()


def _close_one(order_id, seen_status, target, softech_status, now):
    """Conditional close + audit row in one transaction. True when this run closed it."""
    from apps.delivery.models import DeliveryOrder, DeliveryStatusLog
    fields = {'status': target, 'updated_at': now, 'softech_order_status': softech_status}
    if target == DeliveryOrder.STATUS_CLOSED:
        fields['closed_at'] = now
    with transaction.atomic():
        n = (DeliveryOrder.objects.filter(pk=order_id, status=seen_status, cash_collection__isnull=True)
             .update(**fields))
        if not n:
            return False
        label = 'مُسلَّم في SOFTECH' if softech_status == SOFTECH_DELIVERED else 'ملغى في SOFTECH'
        DeliveryStatusLog.objects.create(
            order_id=order_id, from_status=seen_status, to_status=target, source='system',
            notes=(f'إغلاق تلقائي (C21): {label} — SOFTECH orderstatus={softech_status}. '
                   f'Auto-close: SOFTECH orderstatus={softech_status}.'),
        )
    return True


def run(apply=None, fetch=None, now=None) -> dict:
    """One pass. `apply=None` follows the switch (off → dry run). `fetch` is injectable for tests.
    Returns the run record, which is also stored for the board."""
    from apps.delivery.models import DeliveryOrder

    now = now or timezone.now()
    enabled = is_enabled()
    do_apply = enabled if apply is None else bool(apply)
    hours = min_age_hours()
    rows = list(stuck_queryset(hours, now).values(
        'id', 'status', 'ordered_at', 'softech_crm_branch', 'softech_crm_order_no', 'branch_id',
        'customer_name', 'source_type', 'total_value', 'softech_branch_code'))
    cash_ids = set(DeliveryOrder.objects.filter(id__in=[r['id'] for r in rows], cash_collection__isnull=False)
                   .values_list('id', flat=True))
    keys = [(r['softech_crm_branch'] or '', int(r['softech_crm_order_no']))
            for r in rows if r['softech_crm_order_no'] and r['id'] not in cash_ids]
    statuses = (fetch or fetch_softech_statuses)(keys) if keys else {}

    out_rows, counts = [], {}
    closed = cancelled = 0
    for r in rows:
        key = (r['softech_crm_branch'] or '', int(r['softech_crm_order_no'] or 0))
        st = statuses.get(key, _MISSING)
        v = verdict(r, st, r['id'] in cash_ids)
        done = False
        if do_apply and v in (VERDICT_CLOSE, VERDICT_CANCEL):
            target = DeliveryOrder.STATUS_CLOSED if v == VERDICT_CLOSE else DeliveryOrder.STATUS_CANCELLED
            done = _close_one(r['id'], r['status'], target, st, now)
            if done and v == VERDICT_CLOSE:
                closed += 1
            elif done:
                cancelled += 1
        counts[v] = counts.get(v, 0) + 1
        out_rows.append({'id': r['id'], 'verdict': v, 'done': done,
                         'softech_status': None if st is _MISSING else st})

    sla_filled = _fill_sla(now) if do_apply else 0
    record = {
        'at': now.isoformat(timespec='seconds'), 'mode': 'apply' if do_apply else 'dry_run',
        'enabled': enabled, 'min_age_hours': hours, 'checked': len(rows), 'counts': counts,
        'closed': closed, 'cancelled': cancelled, 'sla_filled': sla_filled,
        'rows': out_rows[:MAX_STORED],
    }
    _store(record)
    logger.info('[stuck-close] %s checked=%s counts=%s closed=%s cancelled=%s',
                record['mode'], len(rows), counts, closed, cancelled)
    return record


def _fill_sla(now):
    """sla_due_at = ordered_at + SLA minutes on open orders that have none (only when the owner set a
    number; 0 = off). Never overwrites a value someone set."""
    from django.db.models import DateTimeField, ExpressionWrapper, F, Value
    from apps.delivery.models import DeliveryOrder
    minutes = sla_minutes()
    if not minutes:
        return 0
    due = ExpressionWrapper(F('ordered_at') + Value(timedelta(minutes=minutes)), output_field=DateTimeField())
    return (DeliveryOrder.objects.filter(status__in=open_statuses(), sla_due_at__isnull=True)
            .update(sla_due_at=due))


def _store(record):
    import json
    try:
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key=LAST_RUN_KEY, defaults={
            'value': json.dumps(record, ensure_ascii=False, default=str), 'value_type': 'json',
            'label': 'آخر فحص للطلبات العالقة', 'category': 'general',
            'description': 'C21 — نتيجة آخر فحص لطلبات التوصيل العالقة (تجربة أو تنفيذ)',
        })
    except Exception as exc:   # the board just shows «no run yet»
        logger.warning('[stuck-close] store failed: %s', exc)


def last_run() -> dict:
    val = _setting(LAST_RUN_KEY, None)
    return val if isinstance(val, dict) else {}
