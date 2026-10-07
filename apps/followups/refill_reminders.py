"""
apps/followups/refill_reminders.py — WhatsApp refill reminders (B1, owner 2026-10-07).

Daily: pick refill / chronic follow-up tasks that fall due soon and send ONE approved template
(`refill_reminder`, Arabic) per customer with three quick replies:
    جهّزوا طلبي في الفرع  → a `cc_whatsapp` pickup Reservation at the branch
    توصيل للمنزل          → a `cc_whatsapp` delivery Reservation
    إيقاف التذكيرات       → RefillReminderOptOut (never reminded again)
A pharmacist confirms the items before anything is prepared — no item is dispensed or
substituted automatically, and the message never names the medicine (health privacy).

Deterministic eligibility (every skip has a reason): task open (pending / called), due within
[today − OVERDUE_DAYS, today + DAYS_AHEAD], customer with a usable phone, not opted out, not
reminded within MIN_GAP_DAYS, branch able to transact, item not known out-of-stock at that branch;
one message per customer per run; DAILY_CAP per run.

Gate: REFILL_REMINDER_SEND_ENABLED (default False). While off, nothing is stored or sent — the
review screen shows a live preview of who WOULD be messaged. Settings (getattr defaults):
REFILL_REMINDER_TEMPLATE='refill_reminder', _LANGUAGE='ar', _DAYS_AHEAD=3, _OVERDUE_DAYS=2,
_MIN_GAP_DAYS=25, _DAILY_CAP=300, _MAX_ATTEMPTS=2.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from collections import Counter

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.followups')

TASK_TYPES = ('refill', 'chronic')
OPEN_STATUSES = ('pending', 'called')
_PAYLOAD_RE = re.compile(r'^refill:(\d+):(branch|delivery|stop)$')
_LOCK_KEY = 7_301_101
AR_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس',
             'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
SKIP_LABELS = {
    'no_phone': 'لا يوجد رقم صالح', 'opted_out': 'أوقف التذكيرات', 'recent_reminder': 'ذُكّر مؤخراً',
    'no_branch': 'لا يوجد فرع متاح', 'out_of_stock': 'الصنف غير متوفر بالفرع',
    'same_customer': 'تذكير واحد لكل عميل', 'already_sent': 'أُرسل له تذكير لهذه المهمة',
    'over_cap': 'تجاوز الحد اليومي',
}
REPLY_TEXT = {
    'branch': 'تم استلام طلبك ✅ سيتواصل معك الصيدلي لتأكيد الأصناف ثم نجهّزها لك في الفرع.',
    'delivery': 'تم استلام طلبك ✅ سيتواصل معك الصيدلي لتأكيد الأصناف وعنوان التوصيل.',
    'stop': 'تم إيقاف تذكيرات الصرف. يمكنك طلب علاجك في أي وقت من خلال الفرع أو الكول سنتر.',
}


def _cfg(name, default):
    return getattr(settings, f'REFILL_REMINDER_{name}', default)


def send_enabled() -> bool:
    return bool(_cfg('SEND_ENABLED', False))


def _digits(phone) -> str:
    return re.sub(r'\D', '', str(phone or ''))


def phone_for(customer) -> str:
    """WhatsApp number to use, or '' when unusable (Egyptian mobile: 01xxxxxxxxx / 201xxxxxxxxx)."""
    for p in (getattr(customer, 'whatsapp_phone', ''), getattr(customer, 'phone', '')):
        d = _digits(p)
        if (len(d) == 11 and d.startswith('01')) or (len(d) == 12 and d.startswith('201')):
            return d
    return ''


def _same_phone(a, b) -> bool:
    a, b = _digits(a), _digits(b)
    return bool(a and b) and a[-10:] == b[-10:]


def mask(phone) -> str:
    d = _digits(phone)
    return f'••••{d[-4:]}' if d else ''


def format_due(d) -> str:
    return f'{d.day} {AR_MONTHS[d.month - 1]}'


def _branch_for(task):
    b = task.branch or getattr(task.customer, 'preferred_branch', None)
    if b is not None and b.can_transact:
        return b
    return None


def _out_of_stock(task, branch) -> bool:
    """Only a KNOWN zero at the branch counts; no stock row = unknown → not skipped."""
    if not task.item_id or branch is None:
        return False
    from apps.catalog.models import ItemStock
    row = ItemStock.objects.filter(item_id=task.item_id, branch=branch).first()
    return row is not None and row.quantity_on_hand <= 0


# ── who would be messaged ─────────────────────────────────────────────────────
def candidates(today=None, cap=None):
    """Returns (to_send: [dict], skipped: Counter, skipped_rows: [dict]) — pure read."""
    from .models import FollowUpTask, RefillReminder, RefillReminderOptOut
    today = today or timezone.localdate()
    cap = int(cap or _cfg('DAILY_CAP', 300))
    lo = today - dt.timedelta(days=int(_cfg('OVERDUE_DAYS', 2)))
    hi = today + dt.timedelta(days=int(_cfg('DAYS_AHEAD', 3)))
    gap_from = timezone.now() - dt.timedelta(days=int(_cfg('MIN_GAP_DAYS', 25)))
    max_attempts = int(_cfg('MAX_ATTEMPTS', 2))

    tasks = (FollowUpTask.objects
             .filter(task_type__in=TASK_TYPES, status__in=OPEN_STATUSES, due_date__range=(lo, hi),
                     customer__isnull=False, phone_invalid=False)
             .select_related('customer', 'customer__preferred_branch', 'branch', 'item')
             .order_by('due_date', '-priority_score', 'pk'))
    opted = set(RefillReminderOptOut.objects.values_list('customer_id', flat=True))
    recent = set(RefillReminder.objects.filter(status__in=['sent', 'replied'], sent_at__gte=gap_from)
                 .values_list('customer_id', flat=True))
    existing = {r['task_id']: r for r in RefillReminder.objects.filter(
        task__in=tasks).values('task_id', 'status', 'attempts')}

    to_send, skipped, skipped_rows, seen = [], Counter(), [], set()

    def skip(task, reason):
        skipped[reason] += 1
        if len(skipped_rows) < 500:
            skipped_rows.append({'task_id': task.pk, 'customer': task.customer.name,
                                 'due_date': task.due_date.isoformat(), 'reason': reason,
                                 'reason_label': SKIP_LABELS[reason]})

    for t in tasks:
        prev = existing.get(t.pk)
        if prev and (prev['status'] != 'failed' or prev['attempts'] >= max_attempts):
            skip(t, 'already_sent')
            continue
        if t.customer_id in opted:
            skip(t, 'opted_out')
            continue
        if t.customer_id in recent:
            skip(t, 'recent_reminder')
            continue
        if t.customer_id in seen:
            skip(t, 'same_customer')
            continue
        phone = phone_for(t.customer)
        if not phone:
            skip(t, 'no_phone')
            continue
        branch = _branch_for(t)
        if branch is None:
            skip(t, 'no_branch')
            continue
        if _out_of_stock(t, branch):
            skip(t, 'out_of_stock')
            continue
        if len(to_send) >= cap:
            skip(t, 'over_cap')
            continue
        seen.add(t.customer_id)
        to_send.append({'task': t, 'phone': phone, 'branch': branch})
    return to_send, skipped, skipped_rows


def preview(today=None):
    """Review-screen view of the next run (no side effects)."""
    to_send, skipped, skipped_rows = candidates(today)
    return {
        'send_enabled': send_enabled(),
        'template': _cfg('TEMPLATE', 'refill_reminder'),
        'to_send': [{'task_id': c['task'].pk, 'customer': c['task'].customer.name,
                     'phone': mask(c['phone']), 'branch': c['branch'].name_ar or c['branch'].name,
                     'due_date': c['task'].due_date.isoformat(),
                     'item': c['task'].item.name if c['task'].item_id else ''} for c in to_send],
        'skipped': dict(skipped),
        'skipped_rows': skipped_rows,
        'skip_labels': SKIP_LABELS,
    }


# ── sending (gated) ───────────────────────────────────────────────────────────
def _variables(task, branch):
    first = (task.customer.name or '').split()
    return [{'type': 'text', 'text': first[0] if first else 'عميلنا'},
            {'type': 'text', 'text': format_due(task.due_date)},
            {'type': 'text', 'text': branch.name_ar or branch.name}]


def _send_one(c, sender):
    from .models import RefillReminder as RR
    task = c['task']
    with transaction.atomic():
        rem = RR.objects.select_for_update().filter(task=task).first()
        if rem is None:
            try:
                rem = RR.objects.create(task=task, customer=task.customer, branch=c['branch'], phone=c['phone'],
                                        due_date=task.due_date, status=RR.STATUS_FAILED, error='جارٍ الإرسال')
            except IntegrityError:          # another run took it
                return 'skipped'
        elif rem.status != RR.STATUS_FAILED:
            return 'skipped'
        else:
            rem.attempts += 1
            rem.phone, rem.branch, rem.error = c['phone'], c['branch'], 'جارٍ الإرسال'
            rem.save(update_fields=['attempts', 'phone', 'branch', 'error'])
    try:
        res = sender.send_template(
            wa_id=c['phone'], template_name=_cfg('TEMPLATE', 'refill_reminder'),
            language=_cfg('LANGUAGE', 'ar'), variables=_variables(task, c['branch']),
            quick_reply_payloads=[f'refill:{rem.pk}:branch', f'refill:{rem.pk}:delivery', f'refill:{rem.pk}:stop'])
        wamid = ((res or {}).get('messages') or [{}])[0].get('id', '')
        rem.status, rem.error, rem.wamid, rem.sent_at = RR.STATUS_SENT, '', wamid, timezone.now()
        rem.save(update_fields=['status', 'error', 'wamid', 'sent_at'])
        return 'sent'
    except Exception as exc:
        rem.error = f'{type(exc).__name__}: {exc}'[:1000]
        rem.save(update_fields=['error'])
        logger.warning('[refill_reminders] send failed for task %s: %s', task.pk, exc)
        return 'failed'


def run(today=None, *, sender=None):
    """Scheduled entry point. Gate off → preview counts only (nothing stored or sent)."""
    to_send, skipped, _ = candidates(today)
    out = {'send_enabled': send_enabled(), 'candidates': len(to_send), 'skipped': dict(skipped),
           'sent': 0, 'failed': 0}
    if not out['send_enabled'] or not to_send:
        return out
    from apps.vouchers.coupon_dashboard import pg_lock      # shared non-blocking advisory lock
    with pg_lock(_LOCK_KEY) as got:
        if not got:
            out['busy'] = True
            return out
        if sender is None:
            from apps.whatsapp.sender import WhatsAppSender
            sender = WhatsAppSender()
        for c in to_send:
            r = _send_one(c, sender)
            if r in ('sent', 'failed'):
                out[r] += 1
    logger.info('[refill_reminders] run: %s', out)
    return out


# ── replies (quick-reply taps from the webhook) ───────────────────────────────
def _create_reservation(rem, choice):
    from apps.notifications.models import Notification
    from apps.reservations.models import Reservation, ReservationStatusLog
    task, cust = rem.task, rem.customer
    branch = rem.branch if rem.branch and rem.branch.can_transact else _branch_for(task)
    if branch is None:
        return None
    method = 'delivery' if choice == 'delivery' else 'pickup'
    res = Reservation.objects.create(
        customer=cust, item=task.item, manual_item_name='' if task.item_id else 'علاج مزمن (من تذكير الصرف)',
        branch=branch, quantity_requested=task.source_item_qty or 1, status='pending',
        order_source='cc_whatsapp', fulfillment_method=method,
        contact_name=cust.name or '', contact_phone=rem.phone,
        notes=('طلب من تذكير الصرف عبر واتساب — '
               + ('توصيل للمنزل' if method == 'delivery' else 'استلام من الفرع')
               + ' — يُرجى الاتصال لتأكيد الأصناف قبل التجهيز'))
    ReservationStatusLog.objects.create(reservation=res, old_status='', new_status='pending',
                                        changed_by=None, note='أُنشئ من رد العميل على تذكير الصرف (واتساب)')
    try:
        Notification.send_to_call_center(
            notification_type='reservation_created',
            title=f'طلب صرف من تذكير واتساب — {res.item_label}',
            body=f'العميل: {cust.name} | الفرع: {branch.name_ar or branch.name} | '
                 + ('توصيل للمنزل' if method == 'delivery' else 'استلام من الفرع'),
            reservation=res, dedup_key=f'res_created_{res.pk}')
    except Exception:
        logger.exception('[refill_reminders] reservation notification failed')
    return res


def handle_button_reply(*, wa_id, payload, context_wamid='', account=None) -> str:
    """Process a quick-reply tap. Idempotent: the first answer wins, repeats are ignored.
    Returns what happened (for logs/tests)."""
    from .models import RefillReminder as RR, RefillReminderOptOut
    m = _PAYLOAD_RE.match(payload or '')
    if not m:
        return 'not_ours'
    rem_id, choice = int(m.group(1)), m.group(2)
    with transaction.atomic():
        rem = (RR.objects.select_for_update(of=('self',)).select_related('task', 'customer', 'branch')
               .filter(pk=rem_id).first())
        if rem is None:
            return 'unknown'
        if not _same_phone(rem.phone, wa_id):
            logger.warning('[refill_reminders] reply for reminder %s from another number', rem_id)
            return 'wrong_sender'
        if rem.reply_choice:
            return 'duplicate'
        if choice == RR.CHOICE_STOP:
            RefillReminderOptOut.objects.get_or_create(customer=rem.customer,
                                                       defaults={'source': 'whatsapp_button'})
        else:
            rem.reservation = _create_reservation(rem, choice)
        rem.reply_choice, rem.replied_at, rem.status = choice, timezone.now(), RR.STATUS_REPLIED
        rem.save(update_fields=['reply_choice', 'replied_at', 'status', 'reservation'])
        task = rem.task
        task.notes = (task.notes + f'\n[{timezone.localdate()}] رد واتساب: '
                      + dict(RR.CHOICE_CHOICES)[choice]
                      + (f' — حجز #{rem.reservation_id}' if rem.reservation_id else '')).strip()
        task.save(update_fields=['notes', 'updated_at'])
    if send_enabled():                       # inside the 24-h window the customer just opened
        try:
            from apps.whatsapp.sender import WhatsAppSender
            WhatsAppSender(account=account).send_text(wa_id=wa_id, body=REPLY_TEXT[choice])
        except Exception as exc:
            logger.warning('[refill_reminders] confirmation text failed: %s', exc)
    return choice


# ── review screen ─────────────────────────────────────────────────────────────
def summary(days=30):
    from django.db.models import Count
    from .models import RefillReminder as RR, RefillReminderOptOut
    since = timezone.now() - dt.timedelta(days=days)
    qs = RR.objects.filter(created_at__gte=since)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    by_choice = dict(qs.exclude(reply_choice='').values_list('reply_choice').annotate(n=Count('id')))
    sent = by_status.get('sent', 0) + by_status.get('replied', 0)
    return {'days': days, 'by_status': by_status, 'by_choice': by_choice, 'sent': sent,
            'reply_rate': round(100 * by_status.get('replied', 0) / sent, 1) if sent else 0,
            'reservations': qs.exclude(reservation=None).count(),
            'opt_outs': RefillReminderOptOut.objects.count()}
