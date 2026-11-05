"""
WhatsApp counselling card — a staff member sends a customer the pharmacist-approved "how to use"
sheets for items they bought (owner 2026-11-03: staff choose per sale; no automatic sends).

Deterministic rules, every skip has a reason:
  * COUNSEL_CARD_SEND_ENABLED off → nothing stored, nothing sent (the drawer still previews)
  * same idempotency key → the first send is returned, never a second message (double tap)
  * customer or phone opted out → a 'blocked_optout' row, no message
  * only items with an APPROVED sheet; the exact version is pinned on the send
  * an item already sent to this phone within COUNSEL_CARD_DEDUPE_DAYS is dropped unless «إعادة الإرسال»
  * per-branch daily cap (Cairo day)
The message never names a medicine (privacy + Meta review): a template with the customer's first
name and a private link (/c/<token>), or plain text with the link inside an open 24-h window.
"""
import datetime as dt
import hashlib
import hmac
import logging

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.catalog.models import Item

from .models import CounselCardItem, CounselCardOptOut, CounselCardSend
from .selectors import approved_content, sheet_for

logger = logging.getLogger(__name__)
CARD_SIGNING_SALT = 'counsel-card'


def enabled() -> bool:
    return bool(getattr(settings, 'COUNSEL_CARD_SEND_ENABLED', False))


def normalise_phone(raw) -> str | None:
    """Egyptian mobile → '2010xxxxxxxx' (12 digits), else None."""
    d = ''.join(ch for ch in str(raw or '') if ch.isdigit())
    if d.startswith('00'):
        d = d[2:]
    if len(d) == 11 and d.startswith('01'):
        d = '2' + d
    if len(d) == 12 and d.startswith('201') and d[3] in '0125':
        return d
    return None


def phone_hash(phone: str) -> str:
    return hmac.new(settings.COUNSEL_PHONE_HASH_KEY.encode(), phone.encode(), hashlib.sha256).hexdigest()


def mask(phone: str) -> str:
    local = '0' + phone[2:] if phone.startswith('20') else phone
    return local[:3] + '*****' + local[-3:]


def first_name(customer) -> str:
    name = (getattr(customer, 'name', '') or '').strip()
    return name.split()[0][:80] if name else ''


def default_phone(customer) -> str:
    from apps.followups.refill_reminders import phone_for
    return phone_for(customer) if customer else ''


def token_for(send) -> str:
    return signing.dumps({'s': send.pk}, salt=CARD_SIGNING_SALT)


def link_for(send) -> str:
    base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
    return f'{base}/c/{token_for(send)}'


def opted_out(customer, ph: str) -> bool:
    q = CounselCardOptOut.objects.filter(phone_hash=ph)
    if customer is not None:
        q = q | CounselCardOptOut.objects.filter(customer=customer)
    return q.exists()


# a send still in flight (queued) counts too, so two drawers open at once cannot both send
LIVE = ('queued', 'sent')


def _recent_item_ids(ph: str) -> set:
    since = timezone.now() - dt.timedelta(days=int(getattr(settings, 'COUNSEL_CARD_DEDUPE_DAYS', 7)))
    return set(CounselCardItem.objects.filter(send__phone_hash=ph, send__status__in=LIVE,
                                              send__created_at__gte=since)
               .values_list('item_id', flat=True))


def _lines(item_ids, ph):
    ids = []
    for i in item_ids or []:
        try:
            ids.append(int(i))
        except (TypeError, ValueError):
            continue
    items = {i.pk: i for i in Item.objects.filter(pk__in=ids)}
    recent = _recent_item_ids(ph) if ph else set()
    out = []
    for iid in dict.fromkeys(ids):
        it = items.get(iid)
        if it is None:
            continue
        content = approved_content(it)
        out.append({'item': it, 'content': content, 'recently_sent': iid in recent})
    return out


def message_text(name: str, url: str) -> str:
    hello = f'مرحباً {name}، ' if name else 'مرحباً، '
    return f'{hello}إرشادات استخدام مشترياتك من صيدليات الرزيقي: {url}'


def plan_card(*, customer, phone, item_ids) -> dict:
    """What a send would do — never writes. Used by the drawer's preview (switch on or off)."""
    norm = normalise_phone(phone or default_phone(customer))
    ph = phone_hash(norm) if norm else ''
    lines = _lines(item_ids, ph)
    blocked = 'bad_phone' if not norm else ('opted_out' if opted_out(customer, ph) else '')
    name = first_name(customer)
    return {
        'enabled': enabled(),
        'phone': mask(norm) if norm else '',
        'blocked_reason': blocked,
        'first_name': name,
        'message_preview': message_text(name, '…/c/<رابط خاص>'),
        'lines': [{'item_id': l['item'].pk, 'name': l['item'].name, 'has_guidance': bool(l['content']),
                   'recently_sent': l['recently_sent']} for l in lines],
        'page_preview': [{'item_id': l['item'].pk, 'name': l['item'].name, **l['content']}
                         for l in lines if l['content']],
    }


def _cap_reached(branch) -> bool:
    cap = int(getattr(settings, 'COUNSEL_CARD_DAILY_CAP', 200))
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return CounselCardSend.objects.filter(branch=branch, status__in=LIVE, created_at__gte=start).count() >= cap


def _template_ready(name: str) -> bool:
    from apps.whatsapp.models import WATemplate
    return WATemplate.objects.filter(name=name, status='approved').exists()


def _window_open(phone: str) -> bool:
    from apps.whatsapp.models import WAConversation
    return any(c.window_open for c in WAConversation.objects.filter(wa_id=phone))


def send_card(*, customer, phone, item_ids, actor, branch, source='pos', idempotency_key='',
              resend=False, sender=None) -> CounselCardSend:
    if not enabled():
        raise ValidationError({'detail': 'الإرسال غير مفعّل'})
    key = (idempotency_key or '').strip()[:64]
    if not key:
        raise ValidationError({'idempotency_key': 'مطلوب'})
    existing = CounselCardSend.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.sent_by_id != getattr(actor, 'pk', None):
            raise ValidationError({'idempotency_key': 'مفتاح مستخدم من قبل'})
        return existing
    norm = normalise_phone(phone or default_phone(customer))
    if not norm:
        raise ValidationError({'phone': 'رقم موبايل مصري غير صحيح'})
    ph = phone_hash(norm)
    base = dict(customer=customer, first_name=first_name(customer), phone_masked=mask(norm), phone_hash=ph,
                branch=branch, sent_by=actor, source=source if source in dict(CounselCardSend.SOURCE_CHOICES)
                else 'pos', idempotency_key=key, resend=bool(resend))

    if opted_out(customer, ph):
        try:
            return CounselCardSend.objects.create(status='blocked_optout', fail_reason='opted_out', **base)
        except IntegrityError:
            return CounselCardSend.objects.get(idempotency_key=key)

    try:
        with transaction.atomic():
            # one send at a time per phone and per branch: the repeat and cap checks below then see
            # any parallel send's queued row (two drawers, two tills)
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s)), pg_advisory_xact_lock(hashtext(%s))',
                            [f'counsel-phone:{ph}', f'counsel-branch:{branch.pk}'])
            lines = [l for l in _lines(item_ids, ph) if l['content']]
            if not lines:
                raise ValidationError({'detail': 'لا يوجد إرشاد معتمد للأصناف المختارة'})
            if not resend:
                lines = [l for l in lines if not l['recently_sent']]
                if not lines:
                    raise ValidationError(
                        {'detail': 'أُرسلت إرشادات هذه الأصناف لهذا الرقم مؤخراً — اختر «إعادة الإرسال»'})
            if _cap_reached(branch):
                raise ValidationError({'detail': 'تم بلوغ الحد اليومي لرسائل الإرشادات في هذا الفرع'})
            # owner question 6 (round 2, R5): 1 card per number per SEND_MIN_INTERVAL_SECONDS, even
            # with «إعادة الإرسال». Last check, inside this transaction: a refusal above keeps the slot.
            from apps.notifications import send_limits
            claimed_at = timezone.now()
            if not send_limits.claim('counsel_card', norm, now=claimed_at):
                raise ValidationError({'detail': 'أُرسلت رسالة إرشادات لهذا الرقم منذ أقل من 10 دقائق — حاول لاحقاً'})
            send = CounselCardSend.objects.create(status='queued', **base)
            for l in lines:
                sheet = sheet_for(l['item'])
                CounselCardItem.objects.create(send=send, item=l['item'], content=sheet,
                                               version=sheet.approved_version)
    except IntegrityError:
        return CounselCardSend.objects.get(idempotency_key=key)

    _deliver(send, norm, sender)
    if send.status == 'failed':                        # reached nobody: the 10-minute slot goes back
        send_limits.release('counsel_card', norm, claimed_at)
    AuditLog.log('counsel_card_sent', user=actor, obj=send,
                 new_data={'status': send.status, 'phone': send.phone_masked, 'channel': send.channel,
                           'items': [{'item': l['item'].pk, 'version': l['content']['version']} for l in lines]},
                 note=send.fail_reason)
    if send.status == 'sent':
        try:
            from apps.omni.services import emit
            emit('counsel_card_sent', send, customer=customer, phone=norm, channel='whatsapp',
                 summary='أُرسلت إرشادات الاستخدام', actor=actor,
                 payload={'items': len(lines)}, attach_only=False)
        except Exception as exc:                       # the timeline is a nicety; the send stands
            logger.warning('counsel card timeline emit failed: %s', exc)
    return send


def _deliver(send, phone, sender):
    url = link_for(send)
    if sender is None:
        from apps.whatsapp.sender import WhatsAppSender
        sender = WhatsAppSender()
    template = getattr(settings, 'COUNSEL_CARD_TEMPLATE', 'counsel_card')
    try:
        if _window_open(phone):
            # the inbox keeps the text without the private link (it opens the customer's sheets)
            result = sender.send_text(wa_id=phone, body=message_text(send.first_name, url),
                                      record_body=message_text(send.first_name, '[رابط الإرشادات]'))
            send.channel = 'text'
        elif not _template_ready(template):
            send.status, send.fail_reason = 'failed', 'template_not_approved'
            send.save(update_fields=['status', 'fail_reason'])
            return
        else:
            result = sender.send_template(
                wa_id=phone, template_name=template,
                language=getattr(settings, 'COUNSEL_CARD_LANGUAGE', 'ar'),
                variables=[{'type': 'text', 'text': send.first_name or 'عميلنا'}],
                url_button_params=[token_for(send)])
            send.channel = 'template'
        msgs = (result or {}).get('messages') or [{}]
        send.wamid = (msgs[0] or {}).get('id', '')[:128]
        send.status = 'sent'
    except Exception as exc:
        logger.warning('counsel card %s send failed: %s', send.pk, exc)
        send.status, send.fail_reason = 'failed', str(exc)[:255]
    send.save(update_fields=['status', 'fail_reason', 'channel', 'wamid'])
