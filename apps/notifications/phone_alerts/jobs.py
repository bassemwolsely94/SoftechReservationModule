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
    """Decide and apply the action for one alert under its row lock.

    Returns None (nothing to do) or one of 'expired', 'reminded', 'escalated', 'escalated_empty'.

    Escalation runs INSIDE the lock: ``fire`` only schedules delivery on commit, and if it raises the
    whole transaction rolls back so the next tick retries. When fire creates nothing (policy never /
    no recipients) the alert is still marked escalated (nothing more can be done) but not counted.

    Reminders are AT-MOST-ONCE by ruling: the claim (``reminders_sent`` + ``last_sent_at``) commits
    before the send, so a failed delivery consumes that reminder and is not retried immediately.
    A tick that escalates an alert sends no reminder for it.
    """
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
            return 'expired'

        if (alert.event != 'escalation' and alert.escalation_of_id is None
                and now - alert.created_at >= timedelta(minutes=policy.escalate_after_min)):
            created = dispatch.fire('escalation', alert, notification=None, requested=True,
                                    raise_errors=True)
            PhoneAlert.objects.filter(pk=alert.pk).update(status='escalated', escalated_at=now)
            return 'escalated' if created else 'escalated_empty'

        last = alert.last_sent_at or alert.created_at
        if (alert.reminders_sent < policy.max_reminders
                and now - last >= timedelta(minutes=policy.remind_after_min)):
            PhoneAlert.objects.filter(pk=alert.pk).update(
                reminders_sent=F('reminders_sent') + 1, last_sent_at=now)
            return 'reminded'
        return None


def tick(now=None):
    """Run one pass. Returns ``{'reminded', 'escalated', 'expired'}`` counts."""
    now = now or timezone.now()
    counts = {'reminded': 0, 'escalated': 0, 'expired': 0}
    ids = list(PhoneAlert.objects.filter(status__in=TICK_STATUSES, kind='alert')
               .order_by('pk').values_list('pk', flat=True))
    for pk in ids:
        try:
            outcome = _process(pk, now)
            if outcome == 'reminded':
                sender.deliver(PhoneAlert.objects.get(pk=pk), reminder=True)
            if outcome in counts:
                counts[outcome] += 1
        except Exception:
            logger.exception('phone alerts tick failed for alert %s', pk)
    return counts
