"""
customers/recognition.py — recognize-on-type + duplicate detection for the POS
customer field.

Given what the cashier is typing (a phone fragment, or a name), return the best
matching customers fast (indexed phone / whatsapp_phone / name) with a compact
CRM snippet, and flag records that look like DUPLICATES of each other (same
normalized phone) so staff can merge instead of creating a third copy.

Deterministic, read-only. Phone matching is on digits only (formatting-agnostic).
"""
import re

from django.db.models import Q

from .models import Customer
from apps.catalog.wildcard import wq

from . import access

_NON_DIGIT = re.compile(r'\D+')


def _digits(s):
    return _NON_DIGIT.sub('', s or '')


def _snippet(c, user=None):
    data = {
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'phone_alt': c.phone_alt,
        'whatsapp_phone': c.whatsapp_phone or c.phone,
        'softech_pic': c.softech_pic,
        'is_guest': c.is_guest,
        'segment': c.segment,
        'segment_label': c.get_segment_display() if c.segment else '',
        'churn_segment': c.churn_segment,
        'ltv': float(c.ltv) if c.ltv is not None else None,
        'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
        'days_since_last_visit': c.days_since_last_visit,
        'purchase_count_90d': c.purchase_count_90d,
        'customer_type_label': c.customer_type_label,
    }
    return access.mask_dict(user, c, data) if user is not None else data


def recognize(query, *, limit=6, user=None):
    """Return {'matches': [...], 'duplicates': [...]} for a typed phone/name.
    With `user`, results follow customers/access.py (B-2): other branches only on a full phone,
    their numbers masked."""
    raw = (query or '').strip()
    if len(raw) < 3:
        return {'matches': [], 'duplicates': []}

    d = _digits(raw)
    fields = ('id', 'name', 'phone', 'phone_alt', 'whatsapp_phone', 'softech_pic',
              'is_guest', 'segment', 'churn_segment', 'ltv', 'last_visit_date',
              'days_since_last_visit', 'purchase_count_90d', 'softech_ptclassifcode')

    if d and len(d) >= 3:
        # Phone path — exact first (best), then prefix, then contained.
        base = Customer.objects.filter(
            Q(phone__icontains=d) | Q(phone_alt__icontains=d) | Q(whatsapp_phone__icontains=d),
            is_account_placeholder=False,
        ).only(*fields, 'preferred_branch_id', 'created_by_id')
        if user is not None and (limit_q := access.findable_q(user, raw)) is not None:
            base = base.filter(limit_q)
        rows = list(base[: limit * 4])
        rows.sort(key=lambda c: _phone_rank(c, d))
        rows = rows[:limit]
    else:
        # Name path.
        base = Customer.objects.filter(wq(raw, 'name') | Q(softech_pic__iexact=raw),
                                       is_account_placeholder=False)
        if user is not None and (limit_q := access.findable_q(user, raw)) is not None:
            base = base.filter(limit_q)
        rows = list(base.only(*fields, 'preferred_branch_id', 'created_by_id')[:limit])

    matches = [_snippet(c, user) for c in rows]
    return {'matches': matches, 'duplicates': _duplicate_clusters(rows, user)}


def _phone_rank(c, d):
    """Lower = better. Exact match beats prefix beats substring; guests rank last."""
    for val, exact_w, prefix_w in ((c.phone, 0, 1), (c.whatsapp_phone, 0, 1), (c.phone_alt, 2, 3)):
        cd = _digits(val)
        if cd == d:
            return (exact_w, c.is_guest)
        if cd.startswith(d) or d.startswith(cd):
            return (prefix_w + 3, c.is_guest)
    return (9, c.is_guest)


def _duplicate_clusters(rows, user=None):
    """Group loaded rows whose primary phone normalizes identically (>1 = dup)."""
    by_phone = {}
    for c in rows:
        pd = _digits(c.phone)
        if pd:
            by_phone.setdefault(pd, []).append(c)
    clusters = []
    for pd, members in by_phone.items():
        if len(members) > 1:
            visible = user is None or all(access.phones_visible(user, m) for m in members)
            clusters.append({'phone': pd if visible else access.mask(pd),
                             'customers': [_snippet(m, user) for m in members]})
    return clusters
