"""
apps/whatsapp/delivery.py — did a message we sent actually reach the customer? (owner 2026-11-25: "a checker
that checks if the OTP or voucher code was actually sent").

Meta answers every Cloud-API send with receipts on our webhook: sent → delivered → read, or failed with an error
code (apps/whatsapp/webhook._handle_status_update writes them on WAMessage). A record that keeps the message's
wamid (VoucherOTP.wamid, PortalLogin.wamid) can therefore be checked:

  not_sent    never handed to WhatsApp (no wamid: WhatsApp not set up or the send failed → QR / manual)
  pending     handed over, no receipt yet (within NO_RECEIPT_AFTER)
  sent        Meta accepted it (single tick)
  delivered   reached the phone (double tick)
  read        opened (only when the customer has read receipts on)
  failed      Meta could not deliver it — error code + reason
  no_receipt  accepted but no "delivered" after NO_RECEIPT_AFTER — phone off / no internet, or our webhook is not
              receiving receipts (see webhook_silent)

Read-only: nothing here sends or retries. No phone number or OTP digit leaves this module unmasked.
"""
from datetime import timedelta

from django.utils import timezone

NO_RECEIPT_AFTER = timedelta(minutes=2)
SILENT_MIN_SENDS = 5          # webhook_silent needs at least this many sends to judge

LABELS = {
    'not_sent': 'لم يُرسل عبر واتساب', 'pending': 'جارٍ الإرسال', 'sent': 'أُرسل',
    'delivered': 'وصل للعميل', 'read': 'قرأه العميل', 'failed': 'فشل الإرسال',
    'no_receipt': 'لم يصل إشعار استلام',
}
OK_STATES = ('delivered', 'read')


def _mask(phone):
    d = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    return f'••••{d[-4:]}' if d else ''


def status(wamid, now=None):
    """{state, label, sent_at, delivered_at, read_at, error} for one message id."""
    from .models import WAMessage
    now = now or timezone.now()
    if not wamid:
        return {'state': 'not_sent', 'label': LABELS['not_sent'], 'sent_at': None, 'delivered_at': None,
                'read_at': None, 'error': ''}
    msg = WAMessage.objects.filter(wamid=wamid, direction='outbound').order_by('-pk').first()
    if msg is None:
        state, sent_at = 'pending', None
        return {'state': state, 'label': LABELS[state], 'sent_at': None, 'delivered_at': None, 'read_at': None,
                'error': ''}
    state = msg.status if msg.status in LABELS else 'sent'
    sent_at = msg.sent_at or msg.created_at
    if state in ('sent', 'pending') and sent_at and now - sent_at > NO_RECEIPT_AFTER:
        state = 'no_receipt'
    error = ''
    if state == 'failed':
        error = ' — '.join(x for x in (msg.error_code, (msg.error_message or '')[:200]) if x)
    return {'state': state, 'label': LABELS[state], 'sent_at': sent_at, 'delivered_at': msg.delivered_at,
            'read_at': msg.read_at, 'error': error}


def _rows(since, until):
    """OTPs and portal login links created in [since, until) with their delivery state."""
    from apps.portal.models import PortalLogin
    from apps.vouchers.models import VoucherOTP
    now = timezone.now()
    rows = []
    for o in (VoucherOTP.objects.filter(created_at__gte=since, created_at__lt=until)
              .select_related('voucher').order_by('created_at')):
        st = status(o.wamid, now)
        rows.append({'kind': 'otp', 'kind_label': 'رمز OTP لقسيمة', 'ref': o.voucher.code, 'phone': _mask(o.phone),
                     'channel': o.sent_via, 'at': o.created_at, **st})
    for lg in (PortalLogin.objects.filter(created_at__gte=since, created_at__lt=until)
               .select_related('customer').order_by('created_at')):
        st = status(lg.wamid, now)
        rows.append({'kind': 'portal_link', 'kind_label': 'رابط دخول البوابة', 'ref': lg.customer.softech_pic or '',
                     'phone': _mask(lg.customer.whatsapp_phone or lg.customer.phone), 'channel': '', 'at': lg.created_at,
                     **st})
    return rows


def webhook_silent(hours=2, now=None):
    """True when we sent messages in the last `hours` but NONE got any receipt — the webhook is not reaching us,
    so "no receipt" says nothing about the customers."""
    from .models import WAMessage
    now = now or timezone.now()
    recent = WAMessage.objects.filter(direction='outbound', created_at__gte=now - timedelta(hours=hours),
                                      created_at__lte=now - NO_RECEIPT_AFTER).exclude(wamid='')
    if recent.count() < SILENT_MIN_SENDS:
        return False
    return not recent.filter(status__in=('delivered', 'read', 'failed')).exists()


def report(day=None):
    """Yesterday's (or `day`'s) OTPs + portal links: counts by state, the problems, delivery rate, webhook state."""
    day = day or (timezone.localdate() - timedelta(days=1))
    tz = timezone.get_current_timezone()
    from datetime import datetime, time
    since = timezone.make_aware(datetime.combine(day, time.min), tz)
    rows = _rows(since, since + timedelta(days=1))
    by_state = {}
    for r in rows:
        by_state[r['state']] = by_state.get(r['state'], 0) + 1
    handed = sum(n for s, n in by_state.items() if s != 'not_sent')
    ok = sum(by_state.get(s, 0) for s in OK_STATES)
    problems = [r for r in rows if r['state'] in ('failed', 'no_receipt', 'not_sent')]
    return {'day': day.isoformat(), 'total': len(rows), 'by_state': by_state,
            'delivery_rate': round(100 * ok / handed, 1) if handed else None,
            'problems': problems, 'webhook_silent': webhook_silent()}


def digest_text(rep):
    lines = [f"OTP وروابط البوابة ({rep['day']}): {rep['total']} — وصل {rep['by_state'].get('delivered', 0) + rep['by_state'].get('read', 0)}"
             + (f" · نسبة الوصول {rep['delivery_rate']}%" if rep['delivery_rate'] is not None else '')]
    if rep['webhook_silent']:
        lines.append('⚠️ لا تصل إشعارات الاستلام من واتساب منذ ساعتين — راجع ربط الـ webhook في Meta.')
    for r in rep['problems'][:30]:
        lines.append(f"• {r['kind_label']} {r['ref']} {r['phone']}: {r['label']}" + (f" ({r['error']})" if r['error'] else ''))
    if len(rep['problems']) > 30:
        lines.append(f"… و{len(rep['problems']) - 30} أخرى")
    return '\n'.join(lines)


def roles():
    """Who gets the daily notice — the coupon / voucher digest recipients (COUPON_DIGEST_ROLES)."""
    from apps.vouchers.coupon_dashboard import digest_roles
    return digest_roles()


def notify(rep):
    """One in-app notice per recipient per day, only when something did not arrive or the webhook is silent."""
    if not rep['problems'] and not rep['webhook_silent']:
        return 0
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile
    dedup = f"message_delivery_{rep['day']}"
    title = f"📵 رسائل OTP لم تصل — {len(rep['problems'])} ({rep['day']})"
    body = digest_text(rep)
    sent = 0
    for p in StaffProfile.objects.filter(role__in=roles(), is_active=True):
        if Notification.objects.filter(recipient=p, dedup_key=dedup).exists():
            continue
        Notification.objects.create(recipient=p, notification_type='message_delivery', title=title, body=body,
                                    dedup_key=dedup)
        sent += 1
    return sent
