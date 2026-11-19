"""The portal robot's queue: claim, heartbeat, report, lease expiry, and a person's resolve.

What stops a supplier order being placed twice:
  • claims run one at a time under pg_advisory_xact_lock(7302001), and the basket moves
    ready → in_progress with a conditional UPDATE, so two devices never get the same basket;
  • a device only ever gets its own operator's jobs, and one piece of work at a time; and no
    fill (or Order History read) starts while another basket on the same PortalAccount is held,
    because two robots would share one supplier cart;
  • a lease that runs out sends the basket to a person (needs_person), never back to ready;
  • a basket that had a LIVE fill run since its last retry may have been ordered (the robot
    may have reached the review page, where Submit is on screen, whatever it reported after),
    unless that run ended before the cart was touched (PRE_CART). It is never retried on a
    person's say-so alone: an Order History read since it got stuck must have found nothing, or
    a holder of rpa.edit confirms nothing was ordered (confirm_none, audited). Once Submit was
    seen (submitted_seen_at), whatever account the robot thought it was on, it can only be
    linked to its order or cancelled;
  • a late "Submit seen" for any closed fill run of the device is still taken in, and pulls the
    basket back to a person whatever state it reached since (a recorded basket with the same
    order number is left as it is; with another number it keeps a reason a person must clear; a
    cancelled basket whose lines were not held has them held now, R19);
  • a basket that may have ordered is cancelled only with an explicit, reasoned confirmation, and
    its buy lines then leave the supplier (chosen_supplier cleared, a «may have ordered» note in
    `tried`): nothing orders them again until a person re-picks them;
  • an Order History read reports every order in its window; only orders not already on another
    basket and sharing a code with this basket (or with a row that cannot be read) count as found.
    It is "none" (the basket may be retried) only when SURE: the robot proved the whole window was
    read (`complete` true, R21), it was not cut at the cap (R20), and every order in it is already
    on another basket (R17). Any doubt is history_unclear: the basket stays with a person.

Fill runs live on the basket's lease. Discovery and Order History runs have no basket claim, so
they carry their own (PortalRun.lease_until). Nothing here writes SOFTECH.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.rpa.models import PortalAccount, PortalBasket, PortalJob, PortalLine, PortalRun
from apps.rpa.portal.recording import parse_qty
from config.writers import writer_allowed

logger = logging.getLogger(__name__)

FLAG = 'RPA_SUPPLIER_PORTAL_ENABLED'
LOCK_KEY = 7302001
LEASE = timedelta(minutes=10)
MAX_STEPS = 5000
MAX_FAILED_READS = 3            # discovery reads that may fail before a job stops being offered

LEASE_EXPIRED = 'lease_expired'
PERSON_OUTCOMES = ('cart_not_empty', 'wrong_account', 'cart_mismatch', 'unknown_message',
                   'login_required_timeout', 'stopped_by_operator', 'timeout', 'error')
HOLDING = ('in_progress', 'awaiting_submit')       # a device holds the basket under a lease
# outcomes the driver reports strictly before it adds a line (plan Task 9 run_plan step 1: account
# check, then empty-cart check, "nothing touched"). Any other outcome of a live fill run - including
# none (expired) and login_required_timeout, since a login page can appear mid-run with the cart
# full (spec §6.6) - may have left the robot on the review page with Submit on screen.
PRE_CART = ('cart_not_empty', 'wrong_account')
# a fill report whose own outcome was past the cart, but from the wrong account: not PRE_CART.
# The driver may also report it itself (plan driver contract, ruling R10).
WRONG_ACCOUNT_LATE = 'wrong_account_late'
CART_NOT_EMPTY_LATE = 'cart_not_empty_late'
LATE_OUTCOMES = (WRONG_ACCOUNT_LATE, CART_NOT_EMPTY_LATE)
# defense in depth (R10, R11): a "pre-cart" report stays pre-cart only when it shows nothing but the
# two pre-cart steps (plan Task 9 run_plan step 1) and no lines. Anything else is late (fail safe).
PRE_CART_STEPS = frozenset({'check_account', 'check_cart_empty'})
# R9: an Order History read starts at local midnight of (window start - 2 h), in settings.TIME_ZONE
HISTORY_MARGIN = timedelta(hours=2)
ACTIONS = ('retry', 'link_order', 'cancel', 'acknowledge')
# a needs_person reason that says an order was (or may have been) placed for this basket
ORDER_REASONS = ('history_found', 'history_unclear', 'record_failed', 'history_unmatched', 'submit_seen',
                 'need_check', 'order_ref_conflict')
MAX_HISTORY_ORDERS = 50
# an Order History read's settled outcomes. history_none ("no order, it may be retried") is given
# only when the read is SURE; any doubt is history_unclear and a person decides (rulings R17-R21)
HISTORY_OUTCOMES = ('history_found', 'history_none', 'history_unclear')
_LINE_STATUSES = {v for v, _ in PortalLine.STATUS}


class QueueError(ValueError):
    """A request the queue refuses (400)."""


class RunConflict(Exception):
    """The run is not this device's, or no longer open (409)."""


class PlacedOrderCancel(QueueError):
    """Cancelling a basket whose order was placed on the site needs an explicit, reasoned
    confirmation (409): it drops the placed order's record and reopens its items."""


# ── small helpers ────────────────────────────────────────────────────────────────────────────

def _audit(action, obj, *, user, old=None, new=None, note=''):
    AuditLog.log(action, user=user, obj=obj, old_data=old, new_data=new, note=str(note)[:255])


def _norm(text) -> str:
    return ' '.join(str(text or '').split()).casefold()


def _clean_steps(steps):
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps[:MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        out.append({'i': s.get('i') if isinstance(s.get('i'), int) else None,
                    'label': str(s.get('label', ''))[:120], 'at': str(s.get('at', ''))[:40],
                    'ok': bool(s.get('ok')), 'note': str(s.get('note', ''))[:300]})
    return out


def _clean_history(lines):
    out = []
    for ln in lines if isinstance(lines, list) else []:
        if not isinstance(ln, dict):
            continue
        raw = ln.get('qty')
        qty = parse_qty(raw)
        # an unreadable qty is kept as text: recording sends that order to a person, it never
        # reads a dropped row as "not ordered"
        out.append({'sku': str(ln.get('sku') or '')[:40], 'qty': qty if qty is not None else str(raw)[:20]})
    return out


def _ref(payload) -> str:
    return str(payload.get('order_ref') or '').strip()[:60]


def _seen_identity(payload):
    acc = payload.get('account')
    if isinstance(acc, dict) and 'identity_text' in acc:
        return acc.get('identity_text')
    return payload.get('identity')


def _save_credit(account, credit, now):
    if not isinstance(credit, dict):
        return None
    kept = {k: str(credit[k])[:40] for k in ('consumption', 'credit', 'limit') if credit.get(k) is not None}
    kept['at'] = now.isoformat()
    PortalAccount.objects.filter(pk=account.pk).update(last_credit=kept)
    return kept


def _save_answers(basket, lines):
    """The cart as handed over: each line's accepted quantity and status (Task 8 diffs the
    recorded order against these)."""
    mine = {ln.pk: ln for ln in basket.lines.all()}
    for row in lines if isinstance(lines, list) else []:
        if not isinstance(row, dict):
            continue
        ln = mine.get(row.get('line_id'))
        if ln is None:
            continue
        fields = []
        try:
            qty = int(row.get('accepted_qty'))
        except (TypeError, ValueError):
            qty = None
        if qty is not None and qty >= 0:
            ln.accepted_qty = qty
            fields.append('accepted_qty')
        if row.get('status') in _LINE_STATUSES:
            ln.status = row['status']
            fields.append('status')
        if fields:
            ln.save(update_fields=fields)


def _close(run, outcome, now, extra_steps=()):
    run.outcome = str(outcome)[:30]
    run.finished_at = now
    if extra_steps:
        run.steps = list(run.steps or []) + list(extra_steps)
    run.save(update_fields=['outcome', 'finished_at', 'steps'])


def _needs_person(basket, reason, *, user, now, read=True):
    old = {'status': basket.status, 'needs_person_reason': basket.needs_person_reason}
    basket.status = 'needs_person'
    basket.needs_person_reason = str(reason)[:255]
    basket.needs_person_at = now
    basket.lease_until = None
    basket.save(update_fields=['status', 'needs_person_reason', 'needs_person_at', 'lease_until',
                               'submitted_seen_at', 'credit_seen'])
    _audit('rpa_portal_needs_person', basket, user=user, old=old,
           new={'status': basket.status, 'needs_person_reason': basket.needs_person_reason},
           note=f'basket {basket.pk}: {basket.needs_person_reason}')
    if read and may_have_ordered(basket):      # it may have reached Submit: read Order History
        request_history(basket)


def may_have_ordered(basket) -> bool:
    """True when a live fill run since the last retry got past the empty-cart check (or never
    said), or an order was seen. Such a basket needs an Order History read (or a person's
    explicit word) before it may be filled again."""
    if basket.submitted_seen_at or basket.portal_ref or basket.filled_at:
        return True
    return _counted_fill_runs(basket).exists()


def _counted_fill_runs(basket):
    runs = PortalRun.objects.filter(basket=basket, kind='fill', mode='live')
    if basket.retried_at:
        runs = runs.filter(started_at__gte=basket.retried_at)
    return runs.exclude(outcome__in=PRE_CART, finished_at__isnull=False)


def _touched_cart(payload) -> bool:
    """R11 allow-list: False only when steps is a list of dicts labelled check_account /
    check_cart_empty (empty is fine) and lines is absent, None or an empty list. Anything else -
    another label, a non-list, a non-dict entry, any line at all - counts as the cart touched."""
    steps = payload.get('steps')
    if not isinstance(steps, list):
        return True
    for s in steps:
        if not isinstance(s, dict) or not isinstance(s.get('label'), str) or s['label'] not in PRE_CART_STEPS:
            return True
    lines = payload.get('lines')
    return not (lines is None or (isinstance(lines, list) and not lines))


def history_since(window_start):
    """R9: local midnight (settings.TIME_ZONE) of window_start - 2 h. Deterministic: the same start
    always gives the same since. The margin covers clock skew between our server and the portal and
    a portal that lists orders by date only."""
    local = timezone.localtime(window_start - HISTORY_MARGIN)
    tz = timezone.get_current_timezone()
    return datetime.combine(local.date(), time(0, 0), tzinfo=tz)


def order_window_start(basket):
    """Where an Order History read must start: the earliest fill run that may have ordered since
    the last retry (any fill run of that period when none is live, e.g. an unexpected Submit
    sighting in a dry run), or filled_at, whichever is earlier. None when there is nothing."""
    times = list(_counted_fill_runs(basket).values_list('started_at', flat=True))
    if not times:
        any_runs = PortalRun.objects.filter(basket=basket, kind='fill')
        if basket.retried_at:
            any_runs = any_runs.filter(started_at__gte=basket.retried_at)
        times = list(any_runs.values_list('started_at', flat=True))
    if basket.filled_at:
        times.append(basket.filled_at)
    return min(times) if times else None


def request_history(basket):
    """Queue an Order History read for a stuck basket (idempotent: one waiting/open read)."""
    if basket.status != 'needs_person':
        raise QueueError('السلة لا تنتظر قرار موظف')
    open_run = PortalRun.objects.filter(basket=basket, kind='history', finished_at__isnull=True).first()
    if open_run is not None:
        return open_run
    return PortalRun.objects.create(basket=basket, kind='history', device=None, mode='dry_run',
                                    started_at=timezone.now())


# ── what the staff screen shows (the rules live here, the screen only displays them) ─────────

def needs_person(basket) -> bool:
    """A person must look at this basket: it is needs_person, or it was recorded while a reason
    stayed on it (an Order History row it could not account for, a found order linked after)."""
    return basket.status == 'needs_person' or (basket.status == 'recorded' and bool(basket.needs_person_reason))


def needs_person_q(prefix=''):
    """needs_person() as a filter; prefix e.g. 'baskets__' when filtering jobs."""
    from django.db.models import Q
    return (Q(**{f'{prefix}status': 'needs_person'})
            | (Q(**{f'{prefix}status': 'recorded'}) & ~Q(**{f'{prefix}needs_person_reason': ''})))


def discovery_state(job) -> dict:
    """How a job's code discovery stands. The queue stops offering a job's discovery once
    MAX_FAILED_READS reads failed (_claim_discovery): from then on a person must act (confirm the
    codes by hand, mark «none», or cancel), so needs_person is True while codes are still missing."""
    runs = PortalRun.objects.filter(kind='discovery', discovery_job=job)
    ok = runs.filter(outcome='discovery_ok').exists()
    failed = runs.filter(finished_at__isnull=False).exclude(outcome='discovery_ok').count()
    missing = PortalLine.objects.filter(basket__job=job, basket__status='pending', supplier_key='',
                                        status='pending').count()
    return {'failed_reads': failed, 'max_failed_reads': MAX_FAILED_READS, 'read_ok': ok,
            'reading': runs.filter(finished_at__isnull=True).exists(), 'missing_codes': missing,
            'needs_person': bool(missing) and not ok and failed >= MAX_FAILED_READS}


# a settled read is not asked for again daily (an unclear one waits for a person, who may ask for a
# fresh read with «افحص سجل الطلبات»). Settled is NOT "cleared": only _history_clears allows a retry.
HISTORY_SETTLED = HISTORY_OUTCOMES


def daily_history_check() -> int:
    """Scheduler (daily): queue an Order History read for every needs_person basket that may have
    ordered and has no read since it got stuck, or whose last read failed (timeout / error...).
    Rows another worker holds are skipped; request_history is itself one-open-read-per-basket.

    awaiting_submit baskets are not read here: a device holds them under a lease (the person is
    at the Submit screen), and expire_leases sends a lapsed one to needs_person, which queues its
    read at once. Returns how many reads were queued."""
    count = 0
    with transaction.atomic():
        for basket in (PortalBasket.objects.select_for_update(skip_locked=True)
                       .filter(status='needs_person').order_by('pk')):
            if not may_have_ordered(basket):
                continue
            reads = PortalRun.objects.filter(basket=basket, kind='history')
            if reads.filter(finished_at__isnull=True).exists():
                continue
            if basket.needs_person_at is not None:
                reads = reads.filter(started_at__gte=basket.needs_person_at)
            if reads.filter(outcome__in=HISTORY_SETTLED).exists():
                continue
            request_history(basket)
            count += 1
    return count


# ── claim ────────────────────────────────────────────────────────────────────────────────────

def _jobs_for(device):
    return PortalJob.objects.filter(status='approved', created_by_id=device.staff_id,
                                    portal__enabled=True, account__active=True)


def _busy(device, now):
    return (PortalBasket.objects.filter(claimed_by=device, status__in=HOLDING).exists()
            or PortalRun.objects.filter(device=device, kind__in=('discovery', 'history'),
                                        finished_at__isnull=True, lease_until__gte=now).exists())


def _held_accounts():
    return PortalBasket.objects.filter(status__in=HOLDING).values('job__account_id')


def claim_next(device):
    """The next piece of work for this device's operator, or None.

    Order: an Order History read a stuck basket is waiting for, then a job's code discovery, then
    the oldest ready basket. Returns {"run_id", "plan"}."""
    if not writer_allowed(FLAG):
        return None
    from apps.rpa.portal import plans
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK_KEY])
        now = timezone.now()
        if _busy(device, now):
            return None
        jobs = _jobs_for(device)
        return (_claim_history(device, jobs, now, plans) or _claim_discovery(device, jobs, now, plans)
                or _claim_fill(device, jobs, now, plans))


def _history_jobs(device):
    """A stuck basket's Order History read is still wanted when its job is already done: a late
    Submit sighting can pull a basket of a finished job back to a person."""
    return PortalJob.objects.filter(status__in=('approved', 'done'), created_by_id=device.staff_id,
                                    portal__enabled=True, account__active=True)


def _claim_history(device, jobs, now, plans):
    run = (PortalRun.objects.select_related('basket')
           .filter(kind='history', device__isnull=True, finished_at__isnull=True,
                   basket__status='needs_person', basket__job__in=_history_jobs(device))
           .exclude(basket__job__account_id__in=_held_accounts())
           .order_by('started_at', 'pk').first())
    if run is None:
        return None
    try:
        start = order_window_start(run.basket)
        plan = plans.history_plan(run.basket, since=history_since(start) if start else None)
    except plans.PlanError:          # no window: a read could not prove anything - a person decides
        _close(run, 'error', now, [{'i': None, 'label': 'order_history', 'at': now.isoformat(),
                                    'ok': False, 'note': 'no order window'}])
        return None
    if not PortalRun.objects.filter(pk=run.pk, device__isnull=True).update(
            device=device, started_at=now, lease_until=now + LEASE):
        return None
    _audit('rpa_portal_basket_claimed', run.basket, user=device.staff,
           new={'kind': 'history', 'run_id': run.pk, 'device_id': device.pk},
           note=f'basket {run.basket_id}: Order History')
    return {'run_id': run.pk, 'plan': plan}


def _claim_discovery(device, jobs, now, plans):
    for job in (jobs.filter(baskets__status='pending').distinct()
                .select_related('portal', 'account').order_by('created_at', 'pk')):
        runs = PortalRun.objects.filter(kind='discovery', discovery_job=job)
        if runs.filter(finished_at__isnull=True).exists() or runs.filter(outcome='discovery_ok').exists():
            continue
        if runs.exclude(outcome='discovery_ok').count() >= MAX_FAILED_READS:
            continue
        plan = plans.discovery_plan(job)
        if not plan['searches']:
            continue
        run = PortalRun.objects.create(kind='discovery', discovery_job=job, device=device, mode='dry_run',
                                       started_at=now, lease_until=now + LEASE)
        _audit('rpa_portal_basket_claimed', job, user=device.staff,
               new={'kind': 'discovery', 'run_id': run.pk, 'device_id': device.pk,
                    'searches': len(plan['searches'])},
               note=f'job {job.pk}: discovery')
        return {'run_id': run.pk, 'plan': plan}
    return None


def _claim_fill(device, jobs, now, plans):
    basket = (PortalBasket.objects.select_related('job__portal', 'job__account')
              .filter(status='ready', job__in=jobs)
              .exclude(job__account_id__in=_held_accounts())      # one robot per supplier cart
              .order_by('job__created_at', 'job_id', 'seq', 'pk').first())
    if basket is None:
        return None
    plan = plans.fill_plan(basket)
    lease = now + LEASE
    if not PortalBasket.objects.filter(pk=basket.pk, status='ready').update(
            status='in_progress', claimed_by=device, claimed_at=now, lease_until=lease,
            needs_person_reason=''):
        return None
    run = PortalRun.objects.create(basket=basket, kind='fill', device=device, mode=plan['mode'],
                                   started_at=now)
    _audit('rpa_portal_basket_claimed', basket, user=device.staff, old={'status': 'ready'},
           new={'status': 'in_progress', 'run_id': run.pk, 'device_id': device.pk,
                'mode': plan['mode'], 'lease_until': lease.isoformat()},
           note=f'basket {basket.pk}: claimed by {device.label}')
    return {'run_id': run.pk, 'plan': plan}


# ── heartbeat ────────────────────────────────────────────────────────────────────────────────

def heartbeat(run, device):
    """Another 10 minutes, only while this device still holds the work under a live lease."""
    now = timezone.now()
    with transaction.atomic():
        basket = (PortalBasket.objects.select_for_update().get(pk=run.basket_id)
                  if run.kind == 'fill' and run.basket_id else None)
        run = PortalRun.objects.select_for_update().get(pk=run.pk)
        if run.device_id != device.pk or run.finished_at is not None:
            raise RunConflict()
        if basket is not None:
            if (basket.status not in HOLDING or basket.claimed_by_id != device.pk
                    or basket.lease_until is None or basket.lease_until < now):
                raise RunConflict()
            basket.lease_until = now + LEASE
            basket.save(update_fields=['lease_until'])
            return basket.lease_until
        if run.lease_until is None or run.lease_until < now:
            raise RunConflict()
        run.lease_until = now + LEASE
        run.save(update_fields=['lease_until'])
        return run.lease_until


# ── report ───────────────────────────────────────────────────────────────────────────────────

def report(run, device, payload):
    """Close (or, for a handover, advance) the run and move its basket or job on.

    Payload: {"outcome", "steps", "lines", "credit", "discovery", "order_ref", "history_lines",
    "account": {"identity_text"}}. A run that is not this device's, or not open, is a RunConflict
    - except a late "submit_seen" on any closed fill run of this device (lease expiry, a person,
    a refused retried handover, the operator's stop, an error...), which is always taken in.
    Order History reports carry `orders` (every order in the window; _report_history decides
    which may be this basket's), `complete` (true only with the robot's proof that no further page
    exists) and `truncated` (the read was cut at the cap)."""
    if not isinstance(payload, dict):
        raise QueueError('طلب غير صالح')
    now = timezone.now()
    with transaction.atomic():
        basket = (PortalBasket.objects.select_for_update().select_related('job__account', 'job__portal')
                  .get(pk=run.basket_id) if run.basket_id else None)
        run = PortalRun.objects.select_for_update().get(pk=run.pk)
        if run.device_id != device.pk:
            raise RunConflict()
        outcome = str(payload.get('outcome') or '')
        # a Submit sighting is never thrown away: any closed fill run of this device takes it
        late_sighting = run.kind == 'fill' and run.finished_at is not None and outcome == 'submit_seen'
        # nor is an Order History result whose read a person's decision closed meanwhile (resolve
        # closes open runs as 'resolved'): an order it finds pulls the basket back to a person
        late_history = (run.kind == 'history' and run.finished_at is not None and run.outcome == 'resolved'
                        and outcome in HISTORY_OUTCOMES)
        if run.finished_at is not None and not (late_sighting or late_history):
            raise RunConflict()
        job = basket.job if basket is not None else run.discovery_job
        account = job.account
        seen = _seen_identity(payload)
        wrong_identity = seen is not None and _norm(seen) != _norm(account.identity_text)
        if wrong_identity and outcome != 'submit_seen':     # a Submit sighting is never thrown away
            outcome = ('wrong_account' if run.kind != 'fill' or outcome in PRE_CART
                       else WRONG_ACCOUNT_LATE)
        if run.kind == 'fill' and outcome in PRE_CART and _touched_cart(payload):
            outcome = WRONG_ACCOUNT_LATE if outcome == 'wrong_account' else CART_NOT_EMPTY_LATE
        credit = _save_credit(account, payload.get('credit'), now)
        steps = _clean_steps(payload.get('steps'))
        if late_sighting:
            run.steps = list(run.steps or []) + steps + [_history_step(payload)]
            run.save(update_fields=['steps'])
            return _submit_seen_late(basket, run, payload, device, now)
        run.steps = list(run.steps or []) + steps
        if run.kind == 'discovery':
            return _report_discovery(job, run, outcome, payload, now)
        if run.kind == 'history':
            return _report_history(basket, run, outcome, payload, device, now, late=late_history)
        if credit is not None:
            basket.credit_seen = credit
        return _report_fill(basket, run, outcome, payload, device, now, wrong_identity=wrong_identity)


def _history_step(payload):
    return {'i': None, 'label': 'order_history', 'at': timezone.now().isoformat(), 'ok': True,
            'note': '', 'order_ref': _ref(payload), 'history_lines': _clean_history(payload.get('history_lines'))}


def _report_discovery(job, run, outcome, payload, now):
    from apps.rpa.portal import skus
    if outcome == 'discovery_ok':
        found = payload.get('discovery')
        try:
            with transaction.atomic():
                skus.record_discovery(job, found if isinstance(found, list) else [], run=run)
        except Exception as exc:                     # the read is closed as an error
            logger.warning('portal discovery: recording failed for job %s (%s)', job.pk, type(exc).__name__)
            outcome = 'error'
    elif outcome not in PERSON_OUTCOMES:
        outcome = 'error'
    _close(run, outcome, now)
    return job


def _history_orders(payload):
    """Every order the robot read in the window: [{order_ref, date, lines}]. A robot that still
    reports one order (order_ref + history_lines, no `orders`) is read as a list of one."""
    orders = payload.get('orders')
    if not isinstance(orders, list):
        ref = _ref(payload)
        return [{'order_ref': ref, 'date': '', 'lines': _clean_history(payload.get('history_lines'))}] if ref else []
    out = []
    for o in orders[:MAX_HISTORY_ORDERS]:
        if not isinstance(o, dict):
            continue
        ref = str(o.get('order_ref') or '').strip()[:60]
        if ref:
            out.append({'order_ref': ref, 'date': str(o.get('date') or '')[:20],
                        'lines': _clean_history(o.get('lines'))})
    return out


def _may_be_ours(lines, mine) -> bool:
    """An order may be this basket's when it shares a supplier code with it, or when any row (or
    the whole order) cannot be read - a row we cannot read is never taken as "not ours"."""
    from apps.rpa.portal.skus import canonical_sku
    if not lines:
        return True
    for row in lines:
        sku = canonical_sku(row.get('sku'))
        if not sku or not isinstance(row.get('qty'), int) or sku in mine:
            return True
    return False


def _orders_for(basket, orders):
    """(found, unclear): the orders in the window that may be this basket's - its own order number
    when it has one, else those not already recorded on another basket (portal_key) that share a
    code with it (or have a row that cannot be read) - and the other orders no basket owns (R17:
    nothing proves they are not this basket's, so a person confirms)."""
    if basket.portal_ref:
        own = [o for o in orders if o['order_ref'] == basket.portal_ref]
        if own:
            return own, []
    key = basket.job.portal.key
    taken = set(PortalBasket.objects.filter(portal_key__in=[f'{key}:{o["order_ref"]}' for o in orders])
                .exclude(pk=basket.pk).values_list('portal_key', flat=True))
    mine = set(basket.lines.exclude(supplier_key='').values_list('supplier_key', flat=True))
    free = [o for o in orders if f'{key}:{o["order_ref"]}' not in taken]
    found = [o for o in free if _may_be_ours(o['lines'], mine)]
    return found, [o for o in free if o not in found]


def _unreadable_orders(payload) -> int:
    """Entries of the robot's `orders` list that _history_orders drops (not an object, or no order
    number): an order row we could not read is never taken as "no order"."""
    raw = payload.get('orders')
    if not isinstance(raw, list):
        return 0
    return sum(1 for o in raw if not (isinstance(o, dict) and str(o.get('order_ref') or '').strip()))


def _history_doubts(outcome, payload, unclear) -> list:
    """Why a read that found none of this basket's orders still cannot say "none" (any one is
    enough): the robot itself was unsure; no positive proof that the whole window was read (R21:
    `complete` must be exactly true - the robot sends it only once the recipe's paging locators
    were confirmed on the site); the read hit the cap (R20); order rows whose number could not be
    read; orders no basket owns (R17). Kept on found reads too, for the audit."""
    doubts = []
    if outcome == 'history_unclear':
        doubts.append('robot_unclear')
    if payload.get('complete') is not True:
        doubts.append('not_complete')
    raw = payload.get('orders')
    # any truthy `truncated` counts (fail safe); cap-many orders count even when the robot says not
    if payload.get('truncated') or (isinstance(raw, list) and len(raw) >= MAX_HISTORY_ORDERS):
        doubts.append('truncated')
    if _unreadable_orders(payload):
        doubts.append('unreadable_orders')
    if unclear:
        doubts.append('other_orders')
    return doubts


# a basket a found / unclear read pulls back to a person: it left needs_person (a person's decision,
# a retry, a claim...) but its order was not recorded (recorded / submitted / dry_run_ok stay)
PULL_BACK = ('pending', 'ready', 'in_progress', 'awaiting_submit', 'cancelled')


def _report_history(basket, run, outcome, payload, device, now, *, late=False):
    """Settle an Order History read. `late`: the run was closed by a person's decision while the
    robot read; its result is still taken in when it finds (or cannot rule out) an order."""
    reading = outcome in HISTORY_OUTCOMES
    orders = _history_orders(payload) if reading else []
    if outcome == 'history_found' and not orders and not (reading and _unreadable_orders(payload)):
        outcome = 'error'                    # "found" with nothing readable proves nothing
    if outcome not in HISTORY_OUTCOMES:
        if late:                             # e.g. the wrong account: the closed run keeps its outcome
            run.save(update_fields=['steps'])
        else:
            _close(run, outcome if outcome in PERSON_OUTCOMES else 'error', now)
        return basket
    found, unclear = _orders_for(basket, orders)
    doubts = _history_doubts(outcome, payload, unclear)
    step = {'i': None, 'label': 'order_history', 'at': now.isoformat(), 'ok': True, 'note': '',
            'order_ref': found[0]['order_ref'] if len(found) == 1 else '',
            'history_lines': found[0]['lines'] if len(found) == 1 else [],
            'orders': orders, 'matched': [o['order_ref'] for o in found],
            'unclear': [o['order_ref'] for o in unclear],
            'complete': payload.get('complete') is True, 'truncated': bool(payload.get('truncated')),
            'doubts': doubts}
    if found:
        refs = ','.join(o['order_ref'] for o in found)
        settled, reason, note = 'history_found', f'history_found:{refs}', f'Order History found {refs}'
    elif doubts:
        # no colon: _reason_refs must not read the doubts as order numbers to link
        settled = 'history_unclear'
        reason = f'history_unclear ({", ".join(doubts)})'
        note = f'Order History unclear: {", ".join(doubts)}'
        step['note'] = f'{len(orders)} order(s) in the window; unclear: {", ".join(doubts)}'
    else:
        settled, reason, note = 'history_none', '', ''
        step['note'] = f'{len(orders)} order(s) in the window, all on other baskets'
    pull_back = settled != 'history_none' and basket.status in PULL_BACK
    if late and not (pull_back or (settled != 'history_none' and basket.status == 'needs_person')):
        # nothing to act on (no order, or the order is recorded): kept for the record only
        step['note'] = f'{step["note"]} (read closed by a person before it came)'.strip()
        run.steps = list(run.steps or []) + [step]
        run.save(update_fields=['steps'])
        return basket
    _close(run, settled, now, [step])
    if settled == 'history_none':
        return basket
    detail = {'run_id': run.pk, 'orders_read': [o['order_ref'] for o in orders], 'doubts': doubts,
              'unclear_orders': step['unclear']}
    if basket.status == 'needs_person':
        old = {'needs_person_reason': basket.needs_person_reason}
        basket.needs_person_reason = reason[:255]
        basket.save(update_fields=['needs_person_reason'])
        _audit('rpa_portal_needs_person', basket, user=device.staff, old=old,
               new={'needs_person_reason': basket.needs_person_reason, **detail},
               note=f'basket {basket.pk}: {note}')
    elif pull_back:
        _pull_back(basket, reason, device, now, detail, note)
    return basket


def _pull_back(basket, reason, device, now, detail, note):
    """A found / unclear read came for a basket that left needs_person without its order being
    recorded: back to a person; a fill it is in stops at its next heartbeat; a cancelled one has
    its lines held and newer baskets of the same lines pulled too (as a late Submit would)."""
    old = {'status': basket.status, 'needs_person_reason': basket.needs_person_reason}
    was_cancelled = basket.status == 'cancelled'
    PortalRun.objects.filter(basket=basket, finished_at__isnull=True).update(outcome='resolved', finished_at=now)
    basket.claimed_by = None
    basket.save(update_fields=['claimed_by'])
    _needs_person(basket, reason, user=device.staff, now=now, read=False)   # this read is the read
    _audit('rpa_portal_needs_person', basket, user=device.staff, old=old,
           new={'needs_person_reason': basket.needs_person_reason, 'pulled_back': True, **detail},
           note=f'basket {basket.pk}: {note} after it moved on')
    if was_cancelled:
        _cancelled_may_have_ordered(basket, '', device, now)


def _submit_seen_late(basket, run, payload, device, now):
    """Submit was seen after the basket left this device. Whatever it is doing now (waiting for a
    person, retried, even claimed again or cancelled), a person must look at it first."""
    ref = _ref(payload)
    basket.submitted_seen_at = basket.submitted_seen_at or now
    _audit('rpa_portal_submit_seen', basket, user=device.staff,
           new={'order_ref': ref, 'run_id': run.pk, 'late': True, 'run_outcome': run.outcome},
           note=f'basket {basket.pk}: late {ref}')
    if basket.status == 'recorded':
        if ref and ref == basket.portal_ref:         # the same order, sent again: nothing new
            basket.save(update_fields=['submitted_seen_at'])
            return basket
        # another (or an unread) order number on a recorded basket: a second order may exist
        old = {'needs_person_reason': basket.needs_person_reason}
        reason = f'submit_seen:{ref or "?"}'
        basket.needs_person_reason = (f'{basket.needs_person_reason}; {reason}' if basket.needs_person_reason
                                      else reason)[:255]
        basket.save(update_fields=['submitted_seen_at', 'needs_person_reason'])
        _audit('rpa_portal_needs_person', basket, user=device.staff, old=old,
               new={'needs_person_reason': basket.needs_person_reason, 'run_id': run.pk},
               note=f'basket {basket.pk}: recorded {basket.portal_ref}, late Submit {ref or "?"}')
        return basket
    if basket.status == 'submitted':
        basket.save(update_fields=['submitted_seen_at'])
        return basket
    if basket.status == 'needs_person' and ref and (ref == basket.portal_ref
                                                    or ref in _reason_refs(basket.needs_person_reason)):
        basket.save(update_fields=['submitted_seen_at'])   # a person already has this order number
        return basket
    reason = f'submit_seen:{ref or "?"}'
    if basket.status == 'needs_person' and basket.needs_person_reason:
        reason = f'{basket.needs_person_reason}; {reason}'
    was_cancelled = basket.status == 'cancelled'
    PortalRun.objects.filter(basket=basket, finished_at__isnull=True).exclude(kind='history').update(
        outcome='resolved', finished_at=now)          # a re-claimed fill stops at its next heartbeat
    basket.claimed_by = None
    basket.save(update_fields=['claimed_by'])
    _needs_person(basket, reason, user=device.staff, now=now)
    if was_cancelled:
        _cancelled_may_have_ordered(basket, ref, device, now)
    return basket


# a basket that may still be filled and sent from its buy lines (it holds no order of its own yet)
LIVE_BASKETS = ('pending', 'ready', 'in_progress', 'awaiting_submit')


def _cancelled_may_have_ordered(basket, ref, device, now):
    """A cancelled basket turned out to have (maybe) ordered: hold its lines (R19) and pull every
    newer live basket of the same lines to a person, in this same transaction."""
    _hold_after_late_sighting(basket, ref, device, now)
    _pull_other_baskets(basket, device, now)


def _pull_other_baskets(basket, device, now):
    """R19: after this cancelled basket was let go, its buy lines may have been re-picked into a
    newer job at the same portal. That basket would order the same items again, so it goes to a
    person (submit_seen_other:<this basket's id>), whatever it is doing; a fill it is in is closed
    and stops at its next heartbeat. Audited on this basket with every basket pulled."""
    ids = list(basket.lines.values_list('buyline_id', flat=True))
    pks = list(PortalBasket.objects.filter(job__portal_id=basket.job.portal_id, status__in=LIVE_BASKETS,
                                           lines__buyline_id__in=ids)
               .exclude(pk=basket.pk).values_list('pk', flat=True).distinct())
    if not pks:
        return []
    reason = f'submit_seen_other:{basket.pk}'
    pulled = []
    for other in (PortalBasket.objects.select_for_update().filter(pk__in=pks, status__in=LIVE_BASKETS)
                  .order_by('pk')):
        PortalRun.objects.filter(basket=other, finished_at__isnull=True).exclude(kind='history').update(
            outcome='resolved', finished_at=now)
        other.claimed_by = None
        other.save(update_fields=['claimed_by'])
        _needs_person(other, reason, user=device.staff, now=now)
        pulled.append(other.pk)
    _audit('rpa_portal_needs_person', basket, user=device.staff,
           new={'late_sighting_basket': basket.pk, 'baskets': pulled, 'shared_buylines': ids},
           note=f'basket {basket.pk}: may have ordered after its cancel - newer baskets {pulled} to a person')
    return pulled


def _hold_after_late_sighting(basket, ref, device, now):
    """R19: a basket cancelled without holding its lines (a plain cancel: nothing said it had
    ordered), its job maybe finished, turns out to have reached Submit. Its buy lines are held
    now as a confirmed cancel of a may-have-placed basket would have held them (R18: off the
    portal's own supplier code, a «may have ordered» note), so neither the buy list nor the
    Remainders offers them again until a person decides. A basket whose lines were already held
    (a confirmed cancel) is left as the person set it. Audited with each line's supplier before."""
    from apps.rpa.models import BuyListLine
    ids = list(basket.lines.values_list('buyline_id', flat=True))
    if any(_held_for(bl, basket.pk) for bl in BuyListLine.objects.filter(pk__in=ids)):
        return []
    before = {}
    held = _hold_lines(basket, now=now, ref=ref or None, before=before)
    _audit('rpa_portal_needs_person', basket, user=device.staff,
           old={'status': 'cancelled', 'chosen_supplier': before},
           new={'held_buylines': held, 'order_ref': ref, 'late': True},
           note=f'basket {basket.pk}: late Submit on a cancelled basket - lines held')
    return held


def _report_fill(basket, run, outcome, payload, device, now, *, wrong_identity=False):
    from apps.rpa.portal import recording
    user = device.staff
    if basket.status not in HOLDING or basket.claimed_by_id != device.pk:
        raise RunConflict()
    if outcome == 'handover':
        if basket.status != 'in_progress' or run.mode != 'live':
            _close(run, 'error', now)
            _needs_person(basket, 'handover_in_dry_run' if run.mode != 'live' else 'handover_twice',
                          user=user, now=now)
            return basket
        _save_answers(basket, payload.get('lines'))
        run.outcome = 'handover'
        run.save(update_fields=['outcome', 'steps'])  # stays open: the person decides on Submit
        old = {'status': basket.status}
        basket.status = 'awaiting_submit'
        basket.filled_at = now
        basket.lease_until = now + LEASE
        basket.save(update_fields=['status', 'filled_at', 'lease_until', 'credit_seen'])
        _audit('rpa_portal_basket_filled', basket, user=user, old=old,
               new={'status': basket.status, 'run_id': run.pk, 'mode': run.mode},
               note=f'basket {basket.pk}: handed over for Submit')
        return basket
    if outcome == 'submit_seen':
        ref = _ref(payload)
        basket.submitted_seen_at = now
        history = _clean_history(payload.get('history_lines'))
        _close(run, outcome, now, [_history_step(payload)])
        _audit('rpa_portal_submit_seen', basket, user=user, old={'status': basket.status},
               new={'order_ref': ref, 'run_id': run.pk}, note=f'basket {basket.pk}: {ref}')
        if wrong_identity:            # an order was placed - on which account, a person decides
            _needs_person(basket, f'submit_seen_wrong_account:{ref or "?"}', user=user, now=now)
            return basket
        if basket.status != 'awaiting_submit' or run.mode != 'live' or not ref:
            _needs_person(basket, f'submit_seen_unexpected:{ref}' if ref else 'submit_seen_no_ref',
                          user=user, now=now)
            return basket
        basket.status = 'submitted'
        basket.lease_until = None
        basket.save(update_fields=['status', 'lease_until', 'submitted_seen_at', 'credit_seen'])
        try:
            with transaction.atomic():
                return recording.record_order(basket, order_ref=ref, history_lines=history, staff=user)
        except Exception as exc:                     # the order WAS placed: a person records it
            logger.warning('portal report: record_order failed for basket %s (%s)', basket.pk, type(exc).__name__)
            basket.refresh_from_db()
            _needs_person(basket, f'record_failed:{ref}', user=user, now=now)
            return basket
    if outcome == 'dry_run_ok':
        if basket.status != 'in_progress' or run.mode != 'dry_run':
            _close(run, 'error', now)
            _needs_person(basket, 'dry_run_ok_in_live_run', user=user, now=now)
            return basket
        _close(run, outcome, now)
        old = {'status': basket.status}
        basket.lease_until = None
        basket.save(update_fields=['lease_until', 'credit_seen'])
        _audit('rpa_portal_basket_filled', basket, user=user, old=old,
               new={'status': 'dry_run_ok', 'run_id': run.pk, 'mode': run.mode},
               note=f'basket {basket.pk}: dry run clean')
        try:
            with transaction.atomic():
                recording.record_check(basket, payload.get('lines') if isinstance(payload.get('lines'), list) else [])
        except Exception as exc:                     # a person looks at the answers
            logger.warning('portal report: record_check failed for basket %s (%s)', basket.pk, type(exc).__name__)
            basket.refresh_from_db()
            _needs_person(basket, 'record_failed', user=user, now=now)
        basket.refresh_from_db()
        return basket
    outcome = outcome if outcome in PERSON_OUTCOMES + LATE_OUTCOMES else 'error'
    _close(run, outcome, now)
    _needs_person(basket, outcome, user=user, now=now)
    return basket


# ── lease expiry (scheduler, every 5 minutes) ────────────────────────────────────────────────

def expire_leases(now=None) -> int:
    """A basket held past its lease goes to a person (lease_expired), never back to ready; its
    fill run is closed. A discovery / history read past its lease is closed as a timeout.
    Rows another worker holds are skipped (they are decided there). Returns how many changed."""
    now = now or timezone.now()
    count = 0
    with transaction.atomic():
        for basket in (PortalBasket.objects.select_for_update(skip_locked=True)
                       .filter(status__in=HOLDING, lease_until__lt=now)):
            PortalRun.objects.filter(basket=basket, kind='fill', finished_at__isnull=True).update(
                outcome=LEASE_EXPIRED, finished_at=now)
            _needs_person(basket, LEASE_EXPIRED, user=None, now=now)
            count += 1
        for run in (PortalRun.objects.select_for_update(skip_locked=True)
                    .filter(kind__in=('discovery', 'history'), device__isnull=False,
                            finished_at__isnull=True, lease_until__lt=now)):
            _close(run, 'timeout', now)
            count += 1
    return count


# ── resolve (a person decides on a needs_person basket) ──────────────────────────────────────

def _history_clears(basket):
    """An Order History read since the basket got stuck was SURE it found nothing (history_none),
    none found an order, and no unclear read came after the last sure one. A history_unclear read
    is never permission to retry (R17-R21); a later sure read of the same window settles it."""
    if basket.needs_person_at is None:
        return False
    since = PortalRun.objects.filter(basket=basket, kind='history', finished_at__isnull=False,
                                     started_at__gte=basket.needs_person_at)
    if since.filter(outcome='history_found').exists():
        return False
    last = since.filter(outcome__in=('history_none', 'history_unclear')).order_by('-pk').first()
    return last is not None and last.outcome == 'history_none'


def _history_found_stands(basket) -> bool:
    """An Order History read since the basket got stuck found an order that may be this basket's,
    or could not rule one out (history_unclear), or its reason still says so. A person's
    "nothing was ordered" over it needs a written reason."""
    if any(m in (basket.needs_person_reason or '') for m in ('history_found', 'history_unclear')):
        return True
    return basket.needs_person_at is not None and PortalRun.objects.filter(
        basket=basket, kind='history', outcome__in=('history_found', 'history_unclear'),
        started_at__gte=basket.needs_person_at).exists()


def _reason_refs(reason) -> set:
    """The order numbers a needs_person reason names ('record_failed:PO1; submit_seen:PO2', a
    history_found list 'a,b', an order_ref_conflict 'a/b')."""
    refs = set()
    for part in str(reason or '').split(';'):
        if ':' not in part:
            continue
        key, value = part.split(':', 1)
        if key.strip() == 'submit_seen_other':      # another basket's id, not an order number
            continue
        for ref in value.replace('/', ',').split(','):
            ref = ref.strip()
            if ref and ref != '?':
                refs.add(ref)
    return refs


def may_have_placed(basket) -> bool:
    """The basket's order was, or may have been, placed on the site: an order number or Submit was
    seen, its reason names an order, or a live fill run may have reached Submit and no Order History
    read since it got stuck cleared it. Cancelling such a basket needs an explicit, reasoned
    confirmation, and its lines are then held for a person (never reordered silently)."""
    if basket.submitted_seen_at or basket.portal_ref:
        return True
    if any(m in (basket.needs_person_reason or '') for m in ORDER_REASONS):
        return True
    return may_have_ordered(basket) and not _history_clears(basket)


def suggested_order_ref(basket) -> str:
    """The order number to link to, when one is known for sure: the basket's own, or the only one
    its reason names. '' when there is none or several (a person picks)."""
    if basket.portal_ref:
        return basket.portal_ref
    refs = _reason_refs(basket.needs_person_reason)
    return refs.pop() if len(refs) == 1 else ''


def _history_lines_for(basket, ref):
    for run in PortalRun.objects.filter(basket=basket).order_by('-pk'):
        for step in reversed(run.steps or []):
            if not isinstance(step, dict) or step.get('label') != 'order_history':
                continue
            if step.get('order_ref') == ref:
                return step.get('history_lines') or []
            for o in step.get('orders') or []:
                if isinstance(o, dict) and o.get('order_ref') == ref:
                    return o.get('lines') or []
    return []


def history_orders(basket) -> list:
    """The orders the robot read for this basket, latest read first, one per order number:
    [{order_ref, lines, matched}] (matched: the read counted it as possibly this basket's)."""
    out, seen = [], set()
    for run in PortalRun.objects.filter(basket=basket).order_by('-pk'):
        for step in reversed(run.steps or []):
            if not isinstance(step, dict) or step.get('label') != 'order_history':
                continue
            matched = set(step.get('matched') or ([step['order_ref']] if step.get('order_ref') else []))
            orders = step.get('orders')
            if not isinstance(orders, list):
                orders = [{'order_ref': step.get('order_ref'), 'lines': step.get('history_lines') or []}]
            for o in orders:
                ref = o.get('order_ref') if isinstance(o, dict) else None
                if ref and ref not in seen:
                    seen.add(ref)
                    out.append({'order_ref': ref, 'lines': o.get('lines') or [], 'matched': ref in matched})
    return out


def _person_history_lines(lines):
    """Lines a person typed to link an order: each a supplier code and a whole number of packs."""
    from apps.rpa.portal.skus import canonical_sku
    if not isinstance(lines, list) or not lines:
        raise QueueError('اكتب أسطر الطلب كما في سجل الطلبات')
    out = []
    for row in lines:
        qty = parse_qty(row.get('qty')) if isinstance(row, dict) else None
        sku = canonical_sku(row.get('sku')) if isinstance(row, dict) else ''
        if not sku or qty is None:
            raise QueueError('كل سطر يحتاج كود المورد وكمية بعبوات كاملة')
        out.append({'sku': sku, 'qty': qty})
    return out


def _held_for(bl, basket_id) -> bool:
    return any(isinstance(t, dict) and t.get('basket') == basket_id and t.get('may_have_ordered')
               for t in bl.tried or [])


def _hold_lines(b, *, now, ref=None, before=None):
    """A basket that may have ordered was cancelled: its buy lines leave this supplier (so no job
    or order list takes them again) and carry a note in `tried`, until a person re-picks them.
    The remaining quantity is not touched. A line already held for this basket is not noted
    again. `before`, when given, collects each line's chosen_supplier before (for the audit).
    Returns the buy-line ids held."""
    from apps.rpa.models import BuyListLine
    code = str(b.job.portal.supplier_code)
    ref = ref or b.portal_ref or suggested_order_ref(b)
    held = []
    for bl in (BuyListLine.objects.select_for_update()
               .filter(pk__in=b.lines.values_list('buyline_id', flat=True)).order_by('pk')):
        if before is not None:
            before[str(bl.pk)] = bl.chosen_supplier
        if not _held_for(bl, b.pk):
            bl.tried = list(bl.tried or []) + [{
                'supplier': code, 'accepted': 0, 'at': now.isoformat(), 'basket': b.pk, 'cancelled': True,
                'may_have_ordered': True, 'portal_ref': ref}]
        if bl.chosen_supplier == code:
            bl.chosen_supplier = ''
        bl.save(update_fields=['tried', 'chosen_supplier'])
        held.append(bl.pk)
    return held


def resolve(basket, *, staff, action, order_ref='', confirm_none=False, history_lines=None,
            confirm_placed_order_cancel=False, reason=''):
    """retry → ready (only when no order can have been placed, see the module docstring);
    link_order → submitted + record_order; cancel → cancelled; acknowledge → clears the reason on a
    recorded basket. Needs rpa.edit.

    A basket whose order was or may have been placed (may_have_placed) is cancelled only with
    confirm_placed_order_cancel True AND a written reason (else PlacedOrderCancel, 409); its buy
    lines are then held for a person (_hold_lines). Both go in the audit row. A retry with
    confirm_none while an Order History read found an order needs a written reason too."""
    from apps.rpa.portal import recording
    if not staff.can_do('rpa', 'edit'):
        raise PermissionDenied('لا تملك صلاحية حل سلال الروبوت')
    if action not in ACTIONS:
        raise QueueError('إجراء غير معروف')
    now = timezone.now()
    with transaction.atomic():
        b = PortalBasket.objects.select_for_update().select_related('job__portal').get(pk=basket.pk)
        reason = str(reason or '').strip()[:255]
        if action == 'acknowledge':
            return _acknowledge(b, staff=staff, reason=reason)
        if b.status != 'needs_person':
            raise QueueError('السلة لا تنتظر قرار موظف')
        old = {'status': b.status, 'needs_person_reason': b.needs_person_reason, 'portal_ref': b.portal_ref}
        new = {'action': action, 'confirm_none': bool(confirm_none)}
        if reason:
            new['reason'] = reason
        if action == 'retry':
            # a read the robot is doing now may still find this basket's order: wait for it (a read
            # only queued, which no robot holds yet, is closed below and proves nothing either way)
            if PortalRun.objects.filter(basket=b, kind='history', finished_at__isnull=True,
                                        device__isnull=False).exists():
                raise QueueError('الروبوت يقرأ سجل الطلبات لهذه السلة الآن — انتظر نتيجة القراءة ثم أعد المحاولة')
            if b.submitted_seen_at or b.portal_ref:
                raise QueueError('ظهر رقم طلب لهذه السلة — اربطها بالطلب أو ألغها، لا تُعاد')
            if may_have_ordered(b) and not _history_clears(b):
                if not confirm_none:
                    raise QueueError('ربما أُرسل الطلب — راجع سجل الطلبات أولاً أو أكّد أنه لم يُرسل')
                if _history_found_stands(b) and not reason:
                    raise QueueError('سجل الطلبات وجد طلباً قد يكون لهذه السلة، أو لم يستطع التأكد — اربطها به، '
                                     'أو اكتب سبب تأكيدك أنه لم يُرسل طلب لها')
                new['confirmed_no_order'] = True
            b.status = 'ready'
            b.claimed_by = None
            b.claimed_at = None
            b.lease_until = None
            b.needs_person_reason = ''
            b.filled_at = None            # cleared by the history read / confirm_none above
            b.retried_at = now
            b.save(update_fields=['status', 'claimed_by', 'claimed_at', 'lease_until', 'needs_person_reason',
                                  'filled_at', 'retried_at'])
        elif action == 'link_order':
            ref = str(order_ref or '').strip()[:60]
            if not ref:
                raise QueueError('اكتب رقم الطلب')
            if history_lines is not None:
                lines = _person_history_lines(history_lines)
                new['history_lines'] = lines
            else:
                lines = _clean_history(_history_lines_for(b, ref))
            b.status = 'submitted'
            b.lease_until = None
            b.save(update_fields=['status', 'lease_until'])
            new['order_ref'] = ref
            b = recording.record_order(b, order_ref=ref, history_lines=lines, staff=staff)
            if b.status == 'recorded' and b.needs_person_reason:
                # the person reconciled it: the reason is answered (kept in this audit row's old)
                b.needs_person_reason = ''
                b.save(update_fields=['needs_person_reason'])
            new['needs_person_reason'] = b.needs_person_reason
        else:
            if may_have_placed(b):
                ref = b.portal_ref or suggested_order_ref(b)
                if not (confirm_placed_order_cancel is True and reason):
                    raise PlacedOrderCancel(
                        (f'هذه السلة طُلبت فعلاً من الموقع (رقم الطلب {ref})' if ref else
                         'ربما طُلبت هذه السلة من الموقع')
                        + ' — اربطها بالطلب، أو أكّد الإلغاء واكتب السبب. بعد الإلغاء لا تُطلب أصنافها '
                        'مرة ثانية حتى يختار لها شخص مورداً من جديد')
                new['confirmed_placed_order_cancel'] = True
                new['cancelled_portal_ref'] = ref
                new['held_buylines'] = _hold_lines(b, now=now)
            b.status = 'cancelled'
            b.lease_until = None
            b.save(update_fields=['status', 'lease_until'])
        PortalRun.objects.filter(basket=b, finished_at__isnull=True).update(outcome='resolved', finished_at=now)
        new['status'] = b.status
        _audit('rpa_portal_resolved', b, user=staff, old=old, new=new,
               note=f'basket {b.pk}: {action}')
        if b.status == 'cancelled':          # the job may now be finished
            recording.finish_job_if_done(b.job_id, staff=staff)
    return b


def _acknowledge(b, *, staff, reason):
    """A recorded basket that kept a reason (e.g. a late Submit sighting): a person who checked it
    clears the reason, with a written why. Audited with the reason before and after."""
    if b.status != 'recorded' or not b.needs_person_reason:
        raise QueueError('لا يوجد تنبيه على هذه السلة لإزالته')
    if not reason:
        raise QueueError('اكتب ما راجعته قبل إزالة التنبيه')
    old = {'status': b.status, 'needs_person_reason': b.needs_person_reason}
    b.needs_person_reason = ''
    b.save(update_fields=['needs_person_reason'])
    _audit('rpa_portal_resolved', b, user=staff, old=old,
           new={'action': 'acknowledge', 'reason': reason, 'status': b.status, 'needs_person_reason': ''},
           note=f'basket {b.pk}: acknowledge')
    return b
