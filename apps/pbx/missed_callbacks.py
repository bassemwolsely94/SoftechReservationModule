"""
apps/pbx/missed_callbacks.py — Project 3 (b): missed inbound call → automatic call-back.

Runs right after each CDR sync (apps/sync/tasks._run_pbx_cdr_sync) while
MISSED_CALL_CALLBACKS_ENABLED is on. The task IS the existing call-back: a callcenter.CallLog with
status='callback' + callback_due, shown on /callcenter/callbacks — no new task system.

* one open call-back per number: further misses only raise its `missed_count`;
* skipped: transfer legs, numbers labelled staff/supplier/branch/spam (PhoneLabel), calls already
  returned (an answered call on the number after the miss — the PIC-analytics "returned" rule),
  numbers that already have an open call-back (manual or automatic);
* routing (owner 2026-11-03): the call-center pool — no agent, no branch;
* due: CALL + MISSED_CALL_DUE_MINUTES inside working hours, else the next opening hour;
* auto-close: an answered call on the number after the miss closes it (resolution auto_returned).

Idempotent: CallLog.missed_cdr is UNIQUE, and missed_count is recomputed (never incremented).
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pbx')

LOOKBACK = timedelta(hours=24)
SKIP_LABELS = ('staff', 'supplier', 'branch', 'spam')
NOTE = 'مكالمة فائتة — معاودة اتصال تلقائية'


def enabled():
    return bool(getattr(settings, 'MISSED_CALL_CALLBACKS_ENABLED', False))


def due_for(call_at):
    """When the call-back is due: +N minutes inside working hours, else the next opening."""
    open_h = int(getattr(settings, 'MISSED_CALL_OPEN_HOUR', 9))
    close_h = int(getattr(settings, 'MISSED_CALL_CLOSE_HOUR', 23))
    minutes = int(getattr(settings, 'MISSED_CALL_DUE_MINUTES', 15))
    local = timezone.localtime(call_at)
    opening = local.replace(hour=open_h, minute=0, second=0, microsecond=0)
    if local.hour < open_h:
        return opening
    if local.hour >= close_h:
        return opening + timedelta(days=1)
    return local + timedelta(minutes=minutes)


def _missed_qs():
    from .models import CdrCall
    return (CdrCall.objects.filter(direction='inbound', is_transfer=False)
            .exclude(status='answered').exclude(phone_key=''))


def _open_callback_keys():
    """{phone_key: CallLog} for every open call-back (any source)."""
    from apps.callcenter.models import CallLog
    from .cdr import phone_key
    out = {}
    for log in CallLog.objects.filter(status='callback').order_by('called_at'):
        k = phone_key(log.phone_number)
        if k:
            out.setdefault(k, log)
    return out


def _count_misses(log):
    """Missed calls on the call-back's number from its first miss on (recomputed each run)."""
    return _missed_qs().filter(phone_key=log.missed_cdr.phone_key,
                               call_at__gte=log.missed_cdr.call_at).count()


def queue_missed_callbacks(now=None):
    """Create the call-backs for unreturned missed calls of the last 24 h. Returns a summary."""
    from apps.audit.models import AuditLog
    from apps.callcenter.models import CallLog
    from apps.pic_analytics.models import PhoneLabel
    from apps.pic_analytics.queries.calls import returned_map

    now = now or timezone.now()
    summary = {'created': 0, 'skipped_labelled': 0, 'skipped_returned': 0, 'skipped_open': 0}
    calls = list(_missed_qs().filter(call_at__gte=now - LOOKBACK, call_at__lte=now,
                                     auto_callback__isnull=True)
                 .select_related('customer').order_by('call_at'))
    if not calls:
        return summary
    labelled = set(PhoneLabel.objects.filter(phone_key__in={c.phone_key for c in calls},
                                             label__in=SKIP_LABELS).values_list('phone_key', flat=True))
    returned = returned_map(calls, any_time=True)
    open_by_key = _open_callback_keys()

    first_by_key = defaultdict(list)
    for c in calls:
        if c.phone_key in labelled:
            summary['skipped_labelled'] += 1
        elif returned.get(c.id):
            summary['skipped_returned'] += 1
        elif c.phone_key in open_by_key:
            summary['skipped_open'] += 1
        else:
            first_by_key[c.phone_key].append(c)

    for key, misses in first_by_key.items():
        first = misses[0]
        try:
            with transaction.atomic():
                log = CallLog.objects.create(
                    phone_number=first.customer_number or key, customer=first.customer,
                    direction='inbound', status='callback', source='pbx', purpose='general',
                    called_at=first.call_at, callback_due=due_for(first.call_at),
                    missed_cdr=first, missed_count=len(misses), notes=NOTE,
                )
        except IntegrityError:                       # another run linked this call first
            continue
        summary['created'] += 1
        AuditLog.log('missed_call_callback_created', obj=log,
                     new_data={'cdr': first.pk, 'phone_key': key, 'missed_count': len(misses),
                               'due': log.callback_due.isoformat()})

    # repeat misses on numbers that already have an automatic call-back → refresh the count
    for log in CallLog.objects.filter(status='callback', missed_cdr__isnull=False).select_related('missed_cdr'):
        n = _count_misses(log)
        if n != log.missed_count:
            CallLog.objects.filter(pk=log.pk).update(missed_count=n)
    return summary


def close_returned_callbacks(now=None):
    """Close open AUTOMATIC call-backs whose number has had an answered call since the miss."""
    from apps.audit.models import AuditLog
    from apps.callcenter.models import CallLog
    from .models import CdrCall

    now = now or timezone.now()
    closed = 0
    for log in CallLog.objects.filter(status='callback', missed_cdr__isnull=False).select_related('missed_cdr'):
        answered = (CdrCall.objects.filter(phone_key=log.missed_cdr.phone_key, status='answered',
                                           is_transfer=False, call_at__gt=log.missed_cdr.call_at)
                    .order_by('call_at').first())
        if not answered:
            continue
        n = CallLog.objects.filter(pk=log.pk, status='callback').update(
            status='answered', callback_resolution='auto_returned', callback_resolved_at=now)
        if n:
            closed += 1
            AuditLog.log('missed_call_callback_auto_closed', obj=log,
                         changes={'status': ['callback', 'answered']},
                         new_data={'answered_cdr': answered.pk,
                                   'answered_at': answered.call_at.isoformat()})
    return closed


def run(now=None):
    """Close what was returned first, then queue the new misses."""
    closed = close_returned_callbacks(now)
    summary = queue_missed_callbacks(now)
    summary['closed'] = closed
    return summary
