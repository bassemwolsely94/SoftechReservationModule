"""
Entry point for workflows: ``fire(event_key, source, actor=...)``.

Policy decides whether an alert goes out (never / optional + requester ticked / always),
``recipients.resolve`` decides to whom, and one PhoneAlert row per phone is written. Sending
happens after the surrounding transaction commits, on a background thread
(``core.threads.start_thread``) so a slow WhatsApp API never holds the user's request; the tick
sends anything a dead thread left ``queued``. ``fire`` never raises: a phone alert must never
break the workflow that triggered it.
"""
import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from core.threads import start_thread

from .events import EVENTS
from .models import PhoneAlert, PhoneAlertPolicy
from .recipients import resolve
from .sender import deliver_many

logger = logging.getLogger('elrezeiky.phone_alerts')

# still-live alerts: a superseding status change expires these
OPEN_STATUSES = ('queued', 'sent', 'delivered', 'read', 'failed', 'escalated')
# an alert waiting for this phone blocks a duplicate; an escalated one does not (its escalation
# already went out), so a reassigned task or a resubmitted transfer alerts again
DEDUP_STATUSES = ('queued', 'sent', 'delivered', 'read', 'failed')


def _close_db():
    from django.db import connections
    connections.close_all()


def _deliver_in_background(ids):
    """Thread body: send, then release this thread's DB connections."""
    try:
        deliver_many(ids)
    finally:
        _close_db()


def _deliver_after_commit(ids):
    start_thread(_deliver_in_background, args=(ids,), name='phone-alerts')


def _wanted(policy, source, requested):
    if policy is None or policy.mode == 'never':
        return False
    if policy.mode == 'always':
        return True
    if requested is None:
        requested = bool(getattr(source, 'phone_alert', False))
    return bool(requested)


SUPERSEDING_EVENTS = ('transfer_status', 'reservation_status_urgent', 'task_status')


def fire(event_key, source, *, actor=None, notification=None, requested=None, raise_errors=False,
         only_staff=None):
    """Create (and schedule delivery of) the alerts for ``event_key`` on ``source``.

    Never raises by default (workflows must not break); ``raise_errors=True`` lets the exception
    propagate after the savepoint has rolled back, for callers (the tick) that must retry.
    ``only_staff`` (StaffProfile pks) restricts the resolved recipients; None = no filter.
    """
    try:
        with transaction.atomic():   # savepoint: a failure leaves no half-created alerts
            return _fire(event_key, source, actor, notification, requested, only_staff)
    except Exception:
        logger.exception('phone alert fire(%s) failed', event_key)
        if raise_errors:
            raise
        return []


def _fire(event_key, source, actor, notification, requested, only_staff=None):
    event = EVENTS.get(event_key)
    if event is None or source is None:
        return []
    if not _wanted(PhoneAlertPolicy.for_event(event_key), source, requested):
        return []

    ct = ContentType.objects.get_for_model(source)
    recipients = resolve(event, source, actor=actor)
    if only_staff is not None:
        allowed = set(only_staff)
        recipients = [r for r in recipients if r.staff is not None and r.staff.pk in allowed]
    supersede = event_key in SUPERSEDING_EVENTS
    if supersede and recipients:
        # a newer status change replaces the still-open alert for the same record
        PhoneAlert.objects.filter(
            event=event_key, source_ct=ct, source_id=source.pk, status__in=OPEN_STATUSES,
        ).update(status='expired')
    created = []
    for r in recipients:
        exists = (not supersede) and PhoneAlert.objects.filter(
            event=event_key, source_ct=ct, source_id=source.pk, phone=r.phone,
            status__in=DEDUP_STATUSES).exists()
        if exists:
            continue
        created.append(PhoneAlert.objects.create(
            event=event_key, kind='alert', notification=notification, source_ct=ct,
            source_id=source.pk, recipient_staff=r.staff, phone=r.phone,
            escalation_of=source if isinstance(source, PhoneAlert) else None))
    if created:
        ids = [a.pk for a in created]
        transaction.on_commit(lambda: _deliver_after_commit(ids))
    return created
