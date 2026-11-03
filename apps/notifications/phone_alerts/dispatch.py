"""
Entry point for workflows: ``fire(event_key, source, actor=...)``.

Policy decides whether an alert goes out (never / optional + requester ticked / always),
``recipients.resolve`` decides to whom, and one PhoneAlert row per phone is written. Sending
happens after the surrounding transaction commits. ``fire`` never raises: a phone alert must
never break the workflow that triggered it.
"""
import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .events import EVENTS
from .models import PhoneAlert, PhoneAlertPolicy
from .recipients import resolve
from .sender import deliver_many

logger = logging.getLogger('elrezeiky.phone_alerts')

OPEN_STATUSES = ('queued', 'sent', 'delivered', 'read', 'escalated')


def _wanted(policy, source, requested):
    if policy is None or policy.mode == 'never':
        return False
    if policy.mode == 'always':
        return True
    if requested is None:
        requested = bool(getattr(source, 'phone_alert', False))
    return bool(requested)


def fire(event_key, source, *, actor=None, notification=None, requested=None):
    """Create (and schedule delivery of) the alerts for ``event_key`` on ``source``."""
    try:
        with transaction.atomic():   # savepoint: a failure leaves no half-created alerts
            return _fire(event_key, source, actor, notification, requested)
    except Exception:
        logger.exception('phone alert fire(%s) failed', event_key)
        return []


def _fire(event_key, source, actor, notification, requested):
    event = EVENTS.get(event_key)
    if event is None or source is None:
        return []
    if not _wanted(PhoneAlertPolicy.for_event(event_key), source, requested):
        return []

    ct = ContentType.objects.get_for_model(source)
    created = []
    for r in resolve(event, source, actor=actor):
        exists = PhoneAlert.objects.filter(
            event=event_key, source_ct=ct, source_id=source.pk, phone=r.phone,
            status__in=OPEN_STATUSES).exists()
        if exists:
            continue
        created.append(PhoneAlert.objects.create(
            event=event_key, kind='alert', notification=notification, source_ct=ct,
            source_id=source.pk, recipient_staff=r.staff, phone=r.phone,
            escalation_of=source if isinstance(source, PhoneAlert) else None))
    if created:
        ids = [a.pk for a in created]
        transaction.on_commit(lambda: deliver_many(ids))
    return created
