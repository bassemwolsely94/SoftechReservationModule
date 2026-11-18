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
  • a late "Submit seen" for a run that was already closed is still taken in, and pulls the
    basket back to a person whatever state it reached since.

Fill runs live on the basket's lease. Discovery and Order History runs have no basket claim, so
they carry their own (PortalRun.lease_until). Nothing here writes SOFTECH.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.rpa.models import PortalAccount, PortalBasket, PortalJob, PortalLine, PortalRun
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
# a fill report whose own outcome was past the cart, but from the wrong account: not PRE_CART
WRONG_ACCOUNT_LATE = 'wrong_account_late'
ACTIONS = ('retry', 'link_order', 'cancel')
_LINE_STATUSES = {v for v, _ in PortalLine.STATUS}


class QueueError(ValueError):
    """A request the queue refuses (400)."""


class RunConflict(Exception):
    """The run is not this device's, or no longer open (409)."""


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
        try:
            qty = int(ln.get('qty'))
        except (TypeError, ValueError):
            continue
        out.append({'sku': str(ln.get('sku') or '')[:40], 'qty': qty})
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


def _needs_person(basket, reason, *, user, now):
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
    if may_have_ordered(basket):      # it may have reached Submit: read Order History
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


def _claim_history(device, jobs, now, plans):
    run = (PortalRun.objects.select_related('basket')
           .filter(kind='history', device__isnull=True, finished_at__isnull=True,
                   basket__status='needs_person', basket__job__in=jobs)
           .exclude(basket__job__account_id__in=_held_accounts())
           .order_by('started_at', 'pk').first())
    if run is None:
        return None
    try:
        plan = plans.history_plan(run.basket, since=order_window_start(run.basket))
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
    - except a late "submit_seen" on a fill run closed by lease expiry or a person, which is
    always taken in."""
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
        late_sighting = (run.kind == 'fill' and run.finished_at is not None and outcome == 'submit_seen'
                         and run.outcome in (LEASE_EXPIRED, 'resolved'))
        if run.finished_at is not None and not late_sighting:
            raise RunConflict()
        job = basket.job if basket is not None else run.discovery_job
        account = job.account
        seen = _seen_identity(payload)
        wrong_identity = seen is not None and _norm(seen) != _norm(account.identity_text)
        if wrong_identity and outcome != 'submit_seen':     # a Submit sighting is never thrown away
            outcome = ('wrong_account' if run.kind != 'fill' or outcome in PRE_CART
                       else WRONG_ACCOUNT_LATE)
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
            return _report_history(basket, run, outcome, payload, device, now)
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
        except Exception as exc:                     # noqa: BLE001 - the read is closed as an error
            logger.warning('portal discovery: recording failed for job %s (%s)', job.pk, type(exc).__name__)
            outcome = 'error'
    elif outcome not in PERSON_OUTCOMES:
        outcome = 'error'
    _close(run, outcome, now)
    return job


def _report_history(basket, run, outcome, payload, device, now):
    if outcome == 'history_found' and _ref(payload):
        _close(run, outcome, now, [_history_step(payload)])
        if basket.status == 'needs_person':
            old = {'needs_person_reason': basket.needs_person_reason}
            basket.needs_person_reason = f'history_found:{_ref(payload)}'[:255]
            basket.save(update_fields=['needs_person_reason'])
            _audit('rpa_portal_needs_person', basket, user=device.staff, old=old,
                   new={'needs_person_reason': basket.needs_person_reason, 'run_id': run.pk},
                   note=f'basket {basket.pk}: Order History found {_ref(payload)}')
        return basket
    _close(run, 'history_none' if outcome == 'history_none' else
           outcome if outcome in PERSON_OUTCOMES else 'error', now)
    return basket


def _submit_seen_late(basket, run, payload, device, now):
    """Submit was seen after the basket left this device. Whatever it is doing now (waiting for a
    person, retried, even claimed again or cancelled), a person must look at it first."""
    ref = _ref(payload)
    basket.submitted_seen_at = basket.submitted_seen_at or now
    _audit('rpa_portal_submit_seen', basket, user=device.staff,
           new={'order_ref': ref, 'run_id': run.pk, 'late': True}, note=f'basket {basket.pk}: late {ref}')
    if basket.status in ('submitted', 'recorded'):
        basket.save(update_fields=['submitted_seen_at'])
        return basket
    reason = f'submit_seen:{ref or "?"}'
    if basket.status == 'needs_person' and basket.needs_person_reason:
        reason = f'{basket.needs_person_reason}; {reason}'
    PortalRun.objects.filter(basket=basket, finished_at__isnull=True).exclude(kind='history').update(
        outcome='resolved', finished_at=now)          # a re-claimed fill stops at its next heartbeat
    basket.claimed_by = None
    basket.save(update_fields=['claimed_by'])
    _needs_person(basket, reason, user=device.staff, now=now)
    return basket


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
        except Exception as exc:                     # noqa: BLE001 - the order WAS placed: a person records it
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
        except Exception as exc:                     # noqa: BLE001 - a person looks at the answers
            logger.warning('portal report: record_check failed for basket %s (%s)', basket.pk, type(exc).__name__)
            basket.refresh_from_db()
            _needs_person(basket, 'record_failed', user=user, now=now)
        basket.refresh_from_db()
        return basket
    outcome = outcome if outcome in PERSON_OUTCOMES + (WRONG_ACCOUNT_LATE,) else 'error'
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
    """An Order History read since the basket got stuck found nothing, and none found an order."""
    since = PortalRun.objects.filter(basket=basket, kind='history', finished_at__isnull=False,
                                     started_at__gte=basket.needs_person_at)
    return (basket.needs_person_at is not None and since.filter(outcome='history_none').exists()
            and not since.filter(outcome='history_found').exists())


def _history_lines_for(basket, ref):
    for run in PortalRun.objects.filter(basket=basket).order_by('-pk'):
        for step in reversed(run.steps or []):
            if isinstance(step, dict) and step.get('label') == 'order_history' and step.get('order_ref') == ref:
                return step.get('history_lines') or []
    return []


def resolve(basket, *, staff, action, order_ref='', confirm_none=False, history_lines=None):
    """retry → ready (only when no order can have been placed, see the module docstring);
    link_order → submitted + record_order; cancel → cancelled. Needs rpa.edit."""
    from apps.rpa.portal import recording
    if not staff.can_do('rpa', 'edit'):
        raise PermissionDenied('لا تملك صلاحية حل سلال الروبوت')
    if action not in ACTIONS:
        raise QueueError('إجراء غير معروف')
    now = timezone.now()
    with transaction.atomic():
        b = PortalBasket.objects.select_for_update().select_related('job__portal').get(pk=basket.pk)
        if b.status != 'needs_person':
            raise QueueError('السلة لا تنتظر قرار موظف')
        old = {'status': b.status, 'needs_person_reason': b.needs_person_reason, 'portal_ref': b.portal_ref}
        new = {'action': action, 'confirm_none': bool(confirm_none)}
        if action == 'retry':
            if b.submitted_seen_at or b.portal_ref:
                raise QueueError('ظهر رقم طلب لهذه السلة — اربطها بالطلب أو ألغها، لا تُعاد')
            if may_have_ordered(b) and not _history_clears(b):
                if not confirm_none:
                    raise QueueError('ربما أُرسل الطلب — راجع سجل الطلبات أولاً أو أكّد أنه لم يُرسل')
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
            lines = history_lines if history_lines is not None else _history_lines_for(b, ref)
            b.status = 'submitted'
            b.lease_until = None
            b.save(update_fields=['status', 'lease_until'])
            new['order_ref'] = ref
            b = recording.record_order(b, order_ref=ref, history_lines=_clean_history(lines), staff=staff)
        else:
            b.status = 'cancelled'
            b.lease_until = None
            b.save(update_fields=['status', 'lease_until'])
        PortalRun.objects.filter(basket=b, finished_at__isnull=True).update(outcome='resolved', finished_at=now)
        new['status'] = b.status
        _audit('rpa_portal_resolved', b, user=staff, old=old, new=new,
               note=f'basket {b.pk}: {action}')
    return b
