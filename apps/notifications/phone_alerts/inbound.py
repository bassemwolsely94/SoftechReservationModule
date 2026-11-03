"""
Inbound side of phone alerts: «استلمت» taps, free-text remarks and delivery receipts.

Everything here is idempotent and never trusts the sender blindly: a tap only counts from the
phone the alert was sent to, the first tap wins, and a remark is attached only when it is
unambiguous (quote of the alert, or exactly one recently acknowledged alert without a remark).
"""
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.sms import sms_number

from .models import PhoneAlert, PhoneAlertAttempt

logger = logging.getLogger('elrezeiky.phone_alerts')

_TAP_RE = re.compile(r'^alert:([\w-]+):ack$')
REMARK_WINDOW = timedelta(minutes=30)
REPLY_TEXT = 'تم التسجيل ✓ لو عندك ملاحظة اكتبها هنا وهتوصل للفرع'
MOBILE_SUFFIX = 'عبر الموبايل'


# ── chatter ──────────────────────────────────────────────────────────────────
def post_source_note(source, text, author_staff=None):
    """Post ``text`` to the source record's own chatter and notify like a normal post does."""
    from django.utils.crypto import get_random_string
    from apps.notifications.models import Notification, ChatterMessage
    from apps.reservations.models import Reservation, ReservationActivity
    from apps.tasks.models import OperationalTask, TaskMessage
    from apps.transfers.models import TransferRequest, TransferRequestMessage

    key = f'pa_note_{get_random_string(10)}'
    if isinstance(source, Reservation):
        activity = ReservationActivity.objects.create(
            reservation=source, activity_type='note', message=text, created_by=author_staff)
        if source.branch_id:
            Notification.send_to_branch(
                branch=source.branch, notification_type='call_logged',
                title=f'تحديث على حجز #{source.pk}', body=text[:200], reservation=source,
                include_admins=False, dedup_key=key)
        return activity
    if isinstance(source, TransferRequest):
        msg = TransferRequestMessage.objects.create(
            request=source, message_type='message', message=text, created_by=author_staff)
        from apps.transfers.views import _notify
        author_branch = getattr(author_staff, 'branch_id', None)
        to_requesting = author_branch == source.supplying_branch_id
        _notify(source, f'رسالة جديدة — {source.request_number}', text[:100],
                'transfer_response' if to_requesting else 'transfer_request',
                branch=source.requesting_branch if to_requesting else source.supplying_branch)
        return msg
    if isinstance(source, OperationalTask):
        msg = TaskMessage.objects.create(task=source, author=author_staff,
                                         message_type='comment', body=text)
        from apps.tasks.views import _notify_watchers
        _notify_watchers(source, text[:100], author_staff)
        return msg
    # No chatter of its own: the generic one (needs an author).
    if author_staff is None:
        logger.warning('phone alert note for %r dropped: no author for generic chatter', source)
        return None
    return ChatterMessage.objects.create(
        model_name=source._meta.model_name, record_id=source.pk, author=author_staff, message=text)


def _post_safely(alert, text):
    """Post to the record behind ``alert`` (an escalation posts to the escalated alert's record)."""
    try:
        source = alert.source
        if isinstance(source, PhoneAlert):
            source = source.source
        if source is None:
            return
        with transaction.atomic():
            post_source_note(source, text, alert.recipient_staff)
    except Exception:
        logger.exception('phone alert %s: chatter post failed', alert.pk)


def _who(alert):
    staff = alert.recipient_staff
    return (getattr(staff, 'full_name', '') or '').strip() or alert.phone


# ── replies ──────────────────────────────────────────────────────────────────
def _reply(account, wa_id, body):
    if not getattr(settings, 'PHONE_ALERTS_SEND_ENABLED', False):
        return
    try:
        from apps.whatsapp.sender import WhatsAppSender
        wa = WhatsAppSender(account=account)
        if wa.is_configured:
            wa.send_text(wa_id=wa_id, body=body)
    except Exception as exc:
        logger.warning('phone alert reply failed: %s', type(exc).__name__)


# ── tap ──────────────────────────────────────────────────────────────────────
def handle_alert_tap(*, wa_id, payload, context_wamid='', account=None) -> str:
    """Quick-reply «استلمت». First tap from the alert's own phone wins; repeats are no-ops."""
    m = _TAP_RE.match(payload or '')
    if not m:
        return 'not_ours'
    with transaction.atomic():
        alert = (PhoneAlert.objects.select_for_update(of=('self',))
                 .select_related('recipient_staff').filter(token=m.group(1)).first())
        if alert is None:
            return 'unknown'
        if sms_number(wa_id) != alert.phone:
            logger.warning('phone alert %s: tap from another number ignored', alert.pk)
            return 'wrong_sender'
        if alert.status == 'acknowledged' or alert.ack_at is not None:
            return 'duplicate'
        alert.status, alert.ack_at = 'acknowledged', timezone.now()
        alert.save(update_fields=['status', 'ack_at'])
    _post_safely(alert, f'استلم {_who(alert)} {MOBILE_SUFFIX}')
    _reply(account, wa_id, REPLY_TEXT)
    return 'acknowledged'


# ── free text ────────────────────────────────────────────────────────────────
def handle_free_text(*, wa_id, text, context_wamid='', account=None) -> str:
    """Attach a staff phone's free text as the remark of one unambiguous alert, else 'unmatched'."""
    text = (text or '').strip()
    phone = sms_number(wa_id)
    if not text or not phone:
        return 'unmatched'
    with transaction.atomic():
        base = PhoneAlert.objects.select_for_update(of=('self',)).select_related('recipient_staff')
        alert = None
        if context_wamid:
            quoted = base.filter(wa_message_id=context_wamid, phone=phone).first()
            if quoted is not None:
                if quoted.remark:
                    return 'already_remarked'
                alert = quoted
        if alert is None:
            cutoff = timezone.now() - REMARK_WINDOW
            recent = list(base.filter(phone=phone, status='acknowledged', ack_at__gte=cutoff,
                                      remark='')[:2])
            if len(recent) == 1:
                alert = recent[0]
        if alert is None:
            return 'unmatched'
        alert.remark = text
        alert.save(update_fields=['remark'])
    _post_safely(alert, f'ملاحظة من {_who(alert)} ({MOBILE_SUFFIX}): {text}')
    return 'remark'


# ── delivery receipts ────────────────────────────────────────────────────────
# receipt -> alert statuses it may move the alert FROM (never downgrades ack/escalated/expired)
_STATUS_FROM = {
    'delivered': ('queued', 'sent', 'failed'),
    'read': ('queued', 'sent', 'delivered', 'failed'),
    'failed': ('queued', 'sent'),
}


def apply_status(wamid, new_status, errors=None) -> bool:
    """Apply a Meta delivery receipt to the PhoneAlert that owns ``wamid``. True if one matched."""
    if not wamid or new_status not in _STATUS_FROM:
        return False
    with transaction.atomic():
        alert = PhoneAlert.objects.select_for_update().filter(wa_message_id=wamid).first()
        if alert is None:
            return False
        error = ''
        if new_status == 'failed':
            first = (errors or [{}])[0] or {}
            error = f"{first.get('code', '')} {first.get('title', '')}".strip()
        PhoneAlertAttempt.objects.create(alert=alert, channel='whatsapp', result=new_status,
                                         provider_message_id=wamid, error=error[:1000])
        if alert.status in _STATUS_FROM[new_status]:
            alert.status = new_status
            alert.save(update_fields=['status'])
    return True
