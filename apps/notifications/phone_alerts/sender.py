"""
Deliver one PhoneAlert: WhatsApp template from the staff ChannelAccount, SMS as fallback.

``deliver`` never raises: every outcome is recorded as a PhoneAlertAttempt. A number that got
the same event within SEND_MIN_INTERVAL_SECONDS is not sent to again (``throttled``). With the send
switch off, or no (active) staff account configured, it records ``dry_run`` and the alert
still moves to ``sent`` so the reminder clock and the log behave exactly as in production.
"""
import logging
import re

from django.conf import settings
from django.utils import timezone

from .events import EVENTS
from .models import PhoneAlert, PhoneAlertAttempt

logger = logging.getLogger('elrezeiky.phone_alerts')

ACCOUNT_SETTING = 'phone_alerts_channel_account'
REMINDER_PREFIX = 'تذكير: '
ESCALATION_PREFIX = 'تصعيد: '
SUBJECT_MAX = 60


def staff_account():
    """The staff-alerts WhatsApp ChannelAccount, or None (unset / missing / inactive)."""
    from apps.config.models import SystemSetting
    from apps.omni.models import ChannelAccount
    try:
        raw = SystemSetting.get(ACCOUNT_SETTING, None)
        pk = int(raw)
    except (TypeError, ValueError):
        return None
    return ChannelAccount.objects.filter(pk=pk, channel='whatsapp', is_active=True).first()


def _one_line(value, limit=None):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if limit and len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    return text


def subject_of(source):
    """Short, staff-facing subject of the record: never the customer's name or a raw status code
    (the text goes through Meta to staff phones and shared branch mobiles)."""
    from apps.callcenter.models import CallLog
    from apps.reservations.models import Reservation
    from apps.tasks.models import OperationalTask
    from apps.transfers.models import TransferRequest
    if source is None:
        return ''
    if isinstance(source, Reservation):
        return f'#{source.pk} {source.item_label}'
    if isinstance(source, TransferRequest):
        return str(source.request_number or source.pk)
    if isinstance(source, OperationalTask):
        return source.title or str(source.task_number or source.pk)
    if isinstance(source, CallLog):           # no customer number: staff open the call-back queue
        count = source.missed_count or 1
        return f'#{source.pk} مكالمة فائتة' + (f' ×{count}' if count > 1 else '')
    return ''


def build_staff_alert(alert, reminder=False):
    """(variables, payloads) of the ``staff_alert`` template for ``alert``."""
    from .recipients import source_branch
    event = EVENTS.get(alert.event)
    source = alert.source
    title = event.label_ar if event else alert.event
    if event is not None and event.key == 'escalation' and source is not None:
        # source is the escalated PhoneAlert: describe ITS record, flagged as an escalation.
        original = EVENTS.get(source.event)
        title = ESCALATION_PREFIX + (original.label_ar if original else source.event)
        event, source = original, source.source
    if reminder:
        title = REMINDER_PREFIX + title
    branch = None
    try:
        branch = source_branch(event, source)
    except Exception:
        logger.debug('phone alert %s: branch lookup failed', alert.pk, exc_info=True)
    reference = ''
    if source is not None:
        reference = (getattr(source, 'request_number', '') or getattr(source, 'task_number', '')
                     or getattr(source, 'pk', ''))
    texts = [_one_line(title), _one_line(branch.name if branch else '') or '—',
             _one_line(subject_of(source), SUBJECT_MAX) or '—', _one_line(reference) or '—']
    variables = [{'type': 'text', 'text': t} for t in texts]
    return variables, [f'alert:{alert.token}:ack']


def _sending_enabled(alert):
    # the morning brief has its own switch; the weekly expiry worklist rides the phone-alerts one
    if alert.kind == 'brief' and alert.event != 'expiry_worklist':
        return bool(getattr(settings, 'MORNING_BRIEF_SEND_ENABLED', False))
    return bool(getattr(settings, 'PHONE_ALERTS_SEND_ENABLED', False))


def _provider_id(result):
    try:
        return result['messages'][0]['id']
    except (TypeError, KeyError, IndexError):
        return ''


def _attempt(alert, channel, result, provider_id='', error=''):
    return PhoneAlertAttempt.objects.create(
        alert=alert, channel=channel, result=result,
        provider_message_id=provider_id or '', error=str(error)[:1000])


def _mark_sent(alert, wa_id=None):
    now = timezone.now()
    current = PhoneAlert.objects.filter(pk=alert.pk).values_list('last_sent_at', flat=True).first()
    # never move the tick's claim backwards (a claim stamped later than the real send stays)
    fields = {'last_sent_at': max(now, current) if current else now}
    if alert.status in ('queued', 'failed'):
        fields['status'] = 'sent'
    if wa_id:
        fields['wa_message_id'] = wa_id
    PhoneAlert.objects.filter(pk=alert.pk).update(**fields)
    for k, v in fields.items():
        setattr(alert, k, v)


def _sms_fallback(alert, variables):
    from core.sms import SmsSender
    sms = SmsSender()
    if not sms.is_configured:
        return None
    body = ' — '.join(v['text'] for v in variables)
    try:
        sms.send(alert.phone, body)
    except Exception as exc:
        logger.warning('phone alert %s: SMS fallback failed: %s', alert.pk, type(exc).__name__)
        return _attempt(alert, 'sms', 'failed', error=exc)
    return _attempt(alert, 'sms', 'sent')


def deliver(alert, *, reminder=False, template='staff_alert', variables=None, payloads=None):
    """Send ``alert`` once. Returns the last PhoneAlertAttempt; never raises."""
    try:
        return _deliver(alert, reminder, template, variables, payloads)
    except Exception as exc:  # last-resort guard: delivery must not break callers
        logger.exception('phone alert %s: deliver crashed', getattr(alert, 'pk', None))
        try:
            PhoneAlert.objects.filter(pk=alert.pk, status__in=('queued', 'failed')).update(status='failed')
            return _attempt(alert, 'whatsapp', 'failed', error=exc)
        except Exception:
            return None


def _deliver(alert, reminder, template, variables, payloads):
    if variables is None:
        variables, built = build_staff_alert(alert, reminder)
        payloads = built if payloads is None else payloads
    account = staff_account()
    if not _sending_enabled(alert) or account is None:
        att = _attempt(alert, 'whatsapp', 'dry_run')
        _mark_sent(alert)
        return att

    # owner question 6 (round 2, R5): 1 real message per number per type per
    # SEND_MIN_INTERVAL_SECONDS. Not marked sent: an alert's reminder clock retries it later; a
    # brief has its own once-a-day guard. A send that reached nobody gives the slot back.
    from apps.notifications import send_limits
    kind, claimed_at = f'phone_alert:{alert.event}', timezone.now()
    if not send_limits.claim(kind, alert.phone, now=claimed_at):
        return _attempt(alert, 'whatsapp', 'throttled')

    try:
        from apps.whatsapp.sender import WhatsAppSender
        wa = WhatsAppSender(account=account)
        if not wa.is_configured:
            raise RuntimeError('WhatsApp account has no credentials')
        result = wa.send_template(wa_id=alert.phone, template_name=template, language='ar',
                                  variables=variables, quick_reply_payloads=payloads or [])
    except Exception as exc:
        logger.warning('phone alert %s: WhatsApp failed: %s', alert.pk, type(exc).__name__)
        failed = _attempt(alert, 'whatsapp', 'failed', error=exc)
        sms = _sms_fallback(alert, variables)
        if sms is not None and sms.result == 'sent':
            _mark_sent(alert)
            return sms
        send_limits.release(kind, alert.phone, claimed_at)
        if alert.status in ('queued', 'failed'):
            PhoneAlert.objects.filter(pk=alert.pk).update(status='failed')
            alert.status = 'failed'
        return sms or failed

    wamid = _provider_id(result)
    att = _attempt(alert, 'whatsapp', 'sent', provider_id=wamid)
    _mark_sent(alert, wamid)
    return att


def claim_first_send(alert_id, now=None):
    """Atomically claim a never-sent queued alert (sets ``last_sent_at``). True if this caller won.

    deliver_many (after commit) and the tick (stale queued sweep) both claim first, so the one
    WhatsApp message goes out once even when they race."""
    return PhoneAlert.objects.filter(pk=alert_id, status='queued', last_sent_at__isnull=True).update(
        last_sent_at=now or timezone.now()) == 1


def deliver_many(alert_ids):
    """Deliver the alerts with these ids (after commit, on a background thread).

    Only alerts still 'queued' and not yet claimed: one superseded/expired between creation and
    commit, or already picked up by the tick, is not sent."""
    try:
        for alert in PhoneAlert.objects.filter(pk__in=alert_ids, status='queued').order_by('pk'):
            if not claim_first_send(alert.pk):
                continue
            alert.refresh_from_db()
            deliver(alert)
    except Exception:
        logger.exception('phone alerts: deliver_many failed for %s', alert_ids)
