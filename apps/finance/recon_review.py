"""
apps/finance/recon_review.py

Top-10 C15: people review the A/P reconciliation exceptions (duplicate payments, wrong links, paid
returns, …) in bulk, and finance gets one weekly digest of what is open, new and decided.

Rules:
  • A decision is a person's: «قيد التحقيق» (investigating), «تم الحل» (resolved), «ليس خطأ»
    (dismissed) or «إعادة فتح» (open). Resolved / dismissed need a note. Every change is a
    ReconAuditEvent (before / after). At most MAX_IDS per call.
  • A person's decision is sticky: the scanners do not raise the same exception again
    (recon_engine._upsert_exc / recon_anomalies._upsert_exc call is_suppressed).
  • A person's decision never releases a held match by itself. holding_payment_ids() — what the
    auto-approve policy skips — keeps every open, investigating or person-decided duplicate-payment /
    wrong-link / suspect-amount flag. Only the scanners' own auto-close (the SOFTECH data no longer
    shows the problem) releases it, as before. After a person's decision the match is approved by
    hand in «المقترحات». So this module adds no path to a SOFTECH write.
Nothing here reads or writes SOFTECH.
"""
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .recon_models import MatchCandidate, ReconAuditEvent, ReconException

DECISIONS = ('investigating', 'resolved', 'dismissed', 'open')
NOTE_REQUIRED = ('resolved', 'dismissed')
MAX_IDS = 500
# Flags that hold a payment's matches out of auto-approve (recon_actions.auto_approve).
HOLDING_TYPES = (ReconException.TYPE_DUPLICATE_PAYMENT, ReconException.TYPE_MISALLOCATION,
                 ReconException.TYPE_SUSPECT_AMOUNT)
DECISION_LABELS = {'investigating': 'قيد التحقيق', 'resolved': 'تم الحل', 'dismissed': 'ليس خطأ',
                   'open': 'أُعيد فتحه'}


class ReviewError(Exception):
    pass


def _person_decided():
    """A person decided it (resolved_at is set only by decide(); the scanners' auto-close leaves it empty)."""
    return Q(resolved_at__isnull=False) & ~Q(status='open')


def is_suppressed(etype, party, invoice=None, payment=None) -> bool:
    """True when an exception for the same facts is already open / being investigated, or a person
    has decided it — the scanners then do not raise it again."""
    return ReconException.objects.filter(
        exception_type=etype, party=party, invoice=invoice, payment=payment,
    ).filter(Q(status__in=('open', 'investigating')) | _person_decided()).exists()


def holding_payment_ids(party_type) -> set:
    return set(ReconException.objects.filter(
        payment__isnull=False, party__party_type=party_type, exception_type__in=HOLDING_TYPES,
    ).filter(Q(status__in=('open', 'investigating')) | _person_decided())
        .values_list('payment_id', flat=True))


def decide(ids, action, note='', user=None) -> dict:
    """Bulk decision on exceptions. Returns {'changed': n, 'unchanged': n, 'missing': [ids]}."""
    if action not in DECISIONS:
        raise ReviewError('قرار غير معروف')
    note = (note or '').strip()
    if action in NOTE_REQUIRED and not note:
        raise ReviewError('اكتب سبب القرار في الملاحظة')
    try:
        ids = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise ReviewError('أرقام غير صحيحة')
    if not ids:
        raise ReviewError('لم يُحدَّد شيء')
    if len(ids) > MAX_IDS:
        raise ReviewError(f'الحد {MAX_IDS} في المرة الواحدة')
    now = timezone.now()
    changed = unchanged = 0
    with transaction.atomic():
        rows = {e.pk: e for e in ReconException.objects.select_for_update().filter(pk__in=ids)}
        for pk in ids:
            e = rows.get(pk)
            if e is None:
                continue
            before = {'status': e.status, 'resolved_at': e.resolved_at.isoformat() if e.resolved_at else None,
                      'resolution_notes': e.resolution_notes}
            if e.status == action and (action != 'open' or e.resolved_at is None):
                unchanged += 1
                continue
            e.status = action
            if action == 'open':
                e.resolved_at, e.resolved_by = None, None
            else:
                e.resolved_at, e.resolved_by = now, user
            if note:
                stamp = timezone.localtime(now).strftime('%Y-%m-%d %H:%M')
                e.resolution_notes = (f'{e.resolution_notes}\n' if e.resolution_notes else '') + \
                    f'[{stamp}] {DECISION_LABELS[action]}: {note}'
            e.save(update_fields=['status', 'resolved_at', 'resolved_by', 'resolution_notes'])
            ReconAuditEvent.objects.create(
                action=f'exception_{action}', party_id=e.party_id, performed_by=user,
                before_state={'exception': e.pk, 'type': e.exception_type, **before},
                after_state={'exception': e.pk, 'status': e.status}, detail=note[:2000])
            changed += 1
    return {'changed': changed, 'unchanged': unchanged, 'missing': [i for i in ids if i not in rows]}


# ── weekly digest ─────────────────────────────────────────────────────────────

def _value(e):
    if e.payment_id and e.payment and e.payment.amount:
        return float(e.payment.amount)
    if e.invoice_id and e.invoice and e.invoice.doc_value:
        return float(e.invoice.doc_value)
    return 0.0


def digest_data(today=None, party_type='supplier') -> dict:
    """What finance sees once a week: open exceptions per type (count + money named on them),
    new this week, decided by people this week, and matches held for review."""
    today = today or timezone.localdate()
    week_ago = timezone.now() - timezone.timedelta(days=7)
    labels = dict(ReconException.TYPE_CHOICES)
    open_qs = (ReconException.objects.filter(party__party_type=party_type, status__in=('open', 'investigating'))
               .select_related('payment', 'invoice'))
    by_type = {}
    for e in open_qs.only('exception_type', 'severity', 'status', 'created_at', 'payment__amount',
                          'invoice__doc_value'):
        t = by_type.setdefault(e.exception_type, {'label': labels.get(e.exception_type, e.exception_type),
                                                  'severity': e.severity, 'open': 0, 'investigating': 0,
                                                  'new': 0, 'value': 0.0})
        t[e.status] += 1
        t['new'] += int(e.created_at >= week_ago)
        t['value'] = round(t['value'] + _value(e), 2)
        if e.severity == 'critical':
            t['severity'] = 'critical'
    decided = dict(ReconException.objects.filter(party__party_type=party_type, resolved_at__gte=week_ago)
                   .exclude(status='open').values_list('status').annotate(n=Count('id')))
    held = (MatchCandidate.objects.filter(party__party_type=party_type, status=MatchCandidate.STATUS_PROPOSED)
            .exclude(decision_note='').aggregate(n=Count('id'), value=Sum('proposed_amount')))
    order = {'critical': 0, 'warning': 1, 'info': 2}
    rows = sorted(by_type.items(), key=lambda kv: (order.get(kv[1]['severity'], 3), -kv[1]['value']))
    return {'as_of': today.isoformat(), 'types': [{'type': k, **v} for k, v in rows],
            'decided_this_week': decided, 'held_matches': {'count': held['n'] or 0,
                                                           'value': float(held['value'] or 0)}}


def digest_recipients():
    from apps.config.models import SystemSetting
    from apps.users.models import StaffProfile
    try:
        ids = SystemSetting.get('ap_review_recipients', None)
    except Exception:
        ids = None
    if isinstance(ids, list) and ids:
        return list(StaffProfile.objects.filter(pk__in=ids, is_active=True))
    from apps.users.roles import AP_REVIEW_ROLES
    qs = list(StaffProfile.objects.filter(role__in=AP_REVIEW_ROLES, is_active=True))
    if qs:
        return qs
    # nobody in an A/P-review role yet → the superusers (the owner's accounts)
    return list(StaffProfile.objects.filter(user__is_superuser=True, is_active=True))


def weekly_digest(today=None) -> dict:
    """One in-app digest per recipient per ISO week (dedup). In-app only — no WhatsApp/SMS."""
    from apps.notifications.models import Notification
    d = digest_data(today=today)
    if not d['types'] and not d['held_matches']['count']:
        return {'sent': 0}
    lines = []
    for t in d['types']:
        if t['type'] == ReconException.TYPE_UNPAID_OLD:
            continue                                         # a report, not a review item — its own screen
        extra = f" · قيد التحقيق {t['investigating']}" if t['investigating'] else ''
        lines.append(f"{t['label']}: {t['open']} مفتوح{extra} · جديد هذا الأسبوع {t['new']} · "
                     f"مبالغ مذكورة {round(t['value']):,} ج")
    dec = d['decided_this_week']
    lines.append(f"قرارات هذا الأسبوع: تم الحل {dec.get('resolved', 0)} · ليس خطأ {dec.get('dismissed', 0)} · "
                 f"قيد التحقيق {dec.get('investigating', 0)}")
    lines.append(f"مطابقات موقوفة للمراجعة: {d['held_matches']['count']} ({round(d['held_matches']['value']):,} ج)")
    body = '\n'.join(lines) + '\n\nافتح «تسوية الموردين» ← «الاستثناءات».'
    year, week, _ = (today or timezone.localdate()).isocalendar()
    sent = 0
    for staff in digest_recipients():
        n = Notification.send_to_user(staff, 'ap_review_digest', f'🧾 مراجعة تسوية الموردين — أسبوع {week}',
                                      body, dedup_key=f'ap_review_{year}_{week}', dedup_once=True)
        sent += int(n is not None)
    return {'sent': sent}
