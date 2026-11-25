"""
apps/customers/consent.py — may we contact this customer, for this purpose, on this channel? (backlog P-05,
owner approved 2026-11-11). The ONE rule every outbound sender uses: campaigns, refill reminders, outbound
call lists and restock WhatsApp. Deterministic; no SOFTECH read or write.

  purpose            needs a recorded "yes"?   notes
  service            no — allowed unless withdrawn   "your order is ready", "the item you asked for is back"
  refill             yes (opt-in)               refill reminders
  marketing          yes (opt-in)               offers / campaigns
  marketing_health   yes (opt-in)               campaigns that target a health condition
On top of that, account_state (B7): closed / deceased codes get nothing; entities get service messages only.
A "no" always wins over an older "yes". The latest ContactConsent row per (customer, purpose, channel) is the
decision. Replying STOP / إيقاف on WhatsApp withdraws every purpose for every customer on that number.
Legal note: the rules follow the PDPL reading in backlog P-05 (prior consent + free opt-out for direct
marketing); counsel should still confirm it.
"""
import logging

from django.db.models import OuterRef, Q, Subquery

logger = logging.getLogger('elrezeiky.customers')

SERVICE, REFILL, MARKETING, MARKETING_HEALTH = 'service', 'refill', 'marketing', 'marketing_health'
PURPOSES = (SERVICE, REFILL, MARKETING, MARKETING_HEALTH)
OPT_IN = frozenset({REFILL, MARKETING, MARKETING_HEALTH})
STOP_WORDS = frozenset({'stop', 'unsubscribe', 'إيقاف', 'ايقاف', 'الغاء', 'إلغاء', 'الغاء الاشتراك',
                        'إلغاء الاشتراك', 'وقف', 'توقف'})

# Nothing recorded (NULL) or a yes. Not `.exclude(_consent=False)`: in SQL NOT (NULL = false) is NULL, which
# would drop every customer without a record.
_NOT_REFUSED = Q(_consent__isnull=True) | Q(_consent=True)

REASON_LABELS = {'ok': 'مسموح', 'account_state': 'حساب مغلق / متوفى / جهة في SOFTECH',
                 'withdrawn': 'العميل رفض أو أوقف هذا النوع', 'no_consent': 'لا توجد موافقة مسجلة',
                 'no_customer': 'عميل غير معروف'}


def _latest(customer_ids, purpose, channel):
    """{customer_id: granted} for the customers with a recorded decision."""
    from .models import ContactConsent
    out = {}
    rows = (ContactConsent.objects.filter(customer_id__in=list(customer_ids), purpose=purpose, channel=channel)
            .order_by('customer_id', '-created_at', '-pk').values_list('customer_id', 'granted'))
    for cid, granted in rows:
        out.setdefault(cid, granted)
    return out


def decision(customer, purpose, channel='whatsapp'):
    """(allowed: bool, reason) — reason is a key of REASON_LABELS."""
    from . import account_state
    if purpose not in PURPOSES:
        raise ValueError(f'unknown purpose {purpose!r}')
    if customer is None:
        return (purpose not in OPT_IN), ('ok' if purpose not in OPT_IN else 'no_customer')
    st = account_state.state(customer)
    if st['blocked'] or (st['code'] == 'entity' and purpose != SERVICE):
        return False, 'account_state'
    granted = _latest([customer.pk], purpose, channel).get(customer.pk)
    if granted is False:
        return False, 'withdrawn'
    if purpose in OPT_IN and granted is not True:
        return False, 'no_consent'
    return True, 'ok'


def can_contact(customer, purpose, channel='whatsapp') -> bool:
    return decision(customer, purpose, channel)[0]


def decisions(customer_ids, purpose, channel='whatsapp'):
    """Bulk: {customer_id: granted or None} (None = nothing recorded). Account state is the caller's
    account_state.outreach_q() / state() — this only answers the consent half."""
    got = _latest(customer_ids, purpose, channel)
    return {cid: got.get(cid) for cid in customer_ids}


def filter_allowed(qs, purpose, channel='whatsapp'):
    """A Customer queryset narrowed to who may be contacted (account state + consent), for bulk senders."""
    from . import account_state
    from .models import ContactConsent
    latest = Subquery(ContactConsent.objects.filter(customer=OuterRef('pk'), purpose=purpose, channel=channel)
                      .order_by('-created_at', '-pk').values('granted')[:1])
    qs = qs.annotate(_consent=latest)
    if purpose == SERVICE:
        qs = qs.filter(~Q(softech_status__in=('0', '5')), softech_deceased=False)
        return qs.filter(_NOT_REFUSED)
    return qs.filter(account_state.outreach_q(), _consent=True)


def exclude_withdrawn(qs, purpose, channel):
    """Drop only those who said no (for staff-made calls, which do not need an opt-in)."""
    from .models import ContactConsent
    latest = Subquery(ContactConsent.objects.filter(customer=OuterRef('pk'), purpose=purpose, channel=channel)
                      .order_by('-created_at', '-pk').values('granted')[:1])
    return qs.annotate(_consent=latest).filter(_NOT_REFUSED)


def record(customer, purpose, granted, *, channel='whatsapp', source, user=None, note=''):
    """Record a decision. Idempotent: the same answer as the current one adds no row. Returns the row
    written, or None when nothing changed."""
    from .models import ContactConsent
    if purpose not in PURPOSES:
        raise ValueError(f'unknown purpose {purpose!r}')
    current = _latest([customer.pk], purpose, channel).get(customer.pk)
    if current is bool(granted):
        return None
    row = ContactConsent.objects.create(customer=customer, purpose=purpose, channel=channel, granted=bool(granted),
                                        source=source, note=(note or '')[:200], recorded_by=user)
    if user is not None:
        try:
            from apps.audit.models import AuditLog
            AuditLog.log('customer_updated', user=user, obj=customer,
                         old_data={'consent': {purpose: current}}, new_data={'consent': {purpose: bool(granted)}},
                         note=f'P-05 consent {purpose}/{channel}: {"yes" if granted else "no"} ({source})'[:255])
        except Exception:
            logger.exception('[consent] audit failed')
    return row


def summary_for(customer, channel='whatsapp'):
    """{purpose: {'granted': True/False/None, 'allowed': bool, 'reason': key, 'reason_label': str}}."""
    got = {}
    for p in PURPOSES:
        allowed, reason = decision(customer, p, channel)
        got[p] = {'granted': _latest([customer.pk], p, channel).get(customer.pk), 'allowed': allowed,
                  'reason': reason, 'reason_label': REASON_LABELS[reason]}
    return got


def is_stop_word(text) -> bool:
    return ' '.join(str(text or '').strip().lower().split()) in STOP_WORDS


def withdraw_by_phone(wa_id, *, source='whatsapp_reply'):
    """A STOP reply: every purpose withdrawn on WhatsApp for every customer on that number. Returns how many
    customers were matched."""
    from core import phones
    from .models import Customer
    found = phones.matching(Customer.objects.all(), wa_id, ('phone', 'phone_alt', 'whatsapp_phone'))
    for c in found:
        for p in PURPOSES:
            record(c, p, False, channel='whatsapp', source=source, note='STOP reply')
    return len(found)


def coverage(purpose, channel='whatsapp'):
    """How far consent collection has got for one purpose (P-05 measurement): among customers we could message
    (named, with a phone, not closed / deceased / entity) — how many said yes, no, or were never asked."""
    from django.db.models import Count
    from django.utils import timezone
    from . import account_state
    from .models import ContactConsent, Customer
    base = (Customer.objects.filter(is_guest=False, is_account_placeholder=False).exclude(phone='')
            .filter(account_state.outreach_q()))
    latest = Subquery(ContactConsent.objects.filter(customer=OuterRef('pk'), purpose=purpose, channel=channel)
                      .order_by('-created_at', '-pk').values('granted')[:1])
    counts = dict(base.annotate(_c=latest).values_list('_c').annotate(n=Count('pk')).values_list('_c', 'n'))
    yes, no, total = counts.get(True, 0), counts.get(False, 0), sum(counts.values())
    since = timezone.now() - timezone.timedelta(days=30)
    by_source = dict(ContactConsent.objects.filter(purpose=purpose, channel=channel, created_at__gte=since)
                     .values_list('source').annotate(n=Count('pk')).values_list('source', 'n'))
    return {'purpose': purpose, 'channel': channel, 'reachable': total, 'yes': yes, 'no': no,
            'not_asked': total - yes - no, 'asked_pct': round(100 * (yes + no) / total, 1) if total else 0,
            'opt_out_pct': round(100 * no / (yes + no), 1) if (yes + no) else 0, 'recorded_30d': by_source}
