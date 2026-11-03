"""
Every-minute tick: expire alerts whose record has closed, remind unacknowledged ones, escalate once.

Each alert is handled under ``select_for_update(skip_locked=True)`` in its own short transaction,
so two scheduler processes can never remind/escalate the same alert twice; the WhatsApp send
happens after that transaction commits. The reminder is *claimed* inside the lock (counter and
``last_sent_at`` advance) and ``sender.deliver`` then records the real send.

Alerts whose event has no policy (e.g. morning briefs) are ignored: they never remind or escalate.
Escalation alerts remind per their own policy but never escalate again. The clock runs 24 h.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import dispatch, sender
from .events import EVENTS
from .models import PhoneAlert, PhoneAlertPolicy

logger = logging.getLogger('elrezeiky.phone_alerts')

TICK_STATUSES = ('sent', 'delivered', 'read')


def _process(alert_id, now):
    """Decide and apply the action for one alert: None, or (expired, remind, escalate)."""
    with transaction.atomic():
        alert = (PhoneAlert.objects.select_for_update(skip_locked=True)
                 .filter(pk=alert_id, status__in=TICK_STATUSES, kind='alert').first())
        if alert is None:
            return None
        event = EVENTS.get(alert.event)
        policy = PhoneAlertPolicy.for_event(alert.event)
        if event is None or policy is None:
            return None

        if not event.is_open(alert.source):
            PhoneAlert.objects.filter(pk=alert.pk).update(status='expired')
            return True, False, False

        remind = escalate = False
        last = alert.last_sent_at or alert.created_at
        if (alert.reminders_sent < policy.max_reminders
                and now - last >= timedelta(minutes=policy.remind_after_min)):
            PhoneAlert.objects.filter(pk=alert.pk).update(
                reminders_sent=F('reminders_sent') + 1, last_sent_at=now)
            remind = True
        if (alert.event != 'escalation' and alert.escalation_of_id is None
                and now - alert.created_at >= timedelta(minutes=policy.escalate_after_min)):
            PhoneAlert.objects.filter(pk=alert.pk).update(status='escalated', escalated_at=now)
            escalate = True
        return False, remind, escalate


def tick(now=None):
    """Run one pass. Returns ``{'reminded', 'escalated', 'expired'}`` counts."""
    now = now or timezone.now()
    counts = {'reminded': 0, 'escalated': 0, 'expired': 0}
    ids = list(PhoneAlert.objects.filter(status__in=TICK_STATUSES, kind='alert')
               .order_by('pk').values_list('pk', flat=True))
    for pk in ids:
        try:
            outcome = _process(pk, now)
            if outcome is None:
                continue
            expired, remind, escalate = outcome
            if expired:
                counts['expired'] += 1
                continue
            alert = PhoneAlert.objects.get(pk=pk)
            if remind:
                sender.deliver(alert, reminder=True)
                counts['reminded'] += 1
            if escalate:
                alert.refresh_from_db()
                dispatch.fire('escalation', alert, notification=None, requested=True)
                counts['escalated'] += 1
        except Exception:
            logger.exception('phone alerts tick failed for alert %s', pk)
    return counts
