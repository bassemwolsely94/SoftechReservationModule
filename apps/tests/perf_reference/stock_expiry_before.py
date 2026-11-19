"""Pre-Stage-3 stock_expiry_summary (apps/batches/stock_expiry.py), frozen for the same-answer test."""
from apps.batches.stock_expiry import CLOSED, LIVE, QUARANTINE_ROLES, ROLE_LABELS, _roles


def stock_expiry_summary(branch_codes=None, store_codes=None, include_quarantine=False):
    """KPI cards for the FEFO tabs, from the mirror: value-at-risk + counts by band.

    The top-level keys cover live stock (plus 102/103/105 with include_quarantine). `buckets` gives
    one entry per store role (P-26) so the screens can show shelf risk apart from book residue.
    Closed stores are never counted anywhere."""
    import datetime as _d
    from django.db.models import Sum, Count
    from .models import StockExpiryBalance
    from .expiry_audit import _item_attr_map

    today = _d.date.today()
    scope = StockExpiryBalance.objects.exclude(store_role=CLOSED)
    if branch_codes:
        scope = scope.filter(branch_code__in=list(branch_codes))
    if store_codes:
        scope = scope.filter(store_code__in=list(store_codes))
    base = scope.filter(store_role__in=_roles(include_quarantine))

    def _value(q):
        attrs = _item_attr_map(list(q.values_list('item_code', flat=True).distinct()))
        val = 0.0
        for row in q.values('item_code').annotate(qq=Sum('qty')):
            val += float(row['qq'] or 0) * (attrs.get(row['item_code'], {}).get('unit_cost') or 0)
        return round(val, 2)

    def _bucket(q):
        agg = q.aggregate(qty=Sum('qty'), items=Count('item_code', distinct=True))
        return {'items': agg['items'] or 0, 'qty': float(agg['qty'] or 0), 'value': _value(q)}

    def band(d_from, d_to):
        q = base.filter(expiry_date__gte=today + _d.timedelta(days=d_from),
                        expiry_date__lt=today + _d.timedelta(days=d_to))
        agg = q.aggregate(qty=Sum('qty'), items=Count('item_code', distinct=True))
        codes = list(q.values_list('item_code', flat=True).distinct())
        attrs = _item_attr_map(codes)
        # value at risk needs per-item qty × cost
        val = 0.0
        for row in q.values('item_code').annotate(qq=Sum('qty')):
            uc = attrs.get(row['item_code'], {}).get('unit_cost') or 0
            val += float(row['qq'] or 0) * uc
        return {'items': agg['items'] or 0, 'qty': float(agg['qty'] or 0),
                'value': round(val, 2)}

    expired_q = base.filter(expiry_date__lt=today)
    exp_codes = list(expired_q.values_list('item_code', flat=True).distinct())
    exp_attrs = _item_attr_map(exp_codes)
    exp_val = 0.0
    for row in expired_q.values('item_code').annotate(qq=Sum('qty')):
        uc = exp_attrs.get(row['item_code'], {}).get('unit_cost') or 0
        exp_val += float(row['qq'] or 0) * uc

    b30, b90, b180 = band(0, 30), band(30, 90), band(90, 180)
    live = scope.filter(store_role=LIVE)
    live_expired = live.filter(expiry_date__lt=today)
    buckets = {LIVE: dict(_bucket(live), expired=_bucket(live_expired))}
    for role in QUARANTINE_ROLES:
        buckets[role] = _bucket(scope.filter(store_role=role))
    for role, b in buckets.items():
        b['label'] = ROLE_LABELS[role]
    return {
        'buckets': buckets,
        'lt_30':  b30,
        'lt_90':  b90,
        'lt_180': b180,
        'expired': {'items': expired_q.values('item_code').distinct().count(),
                    'qty': float(expired_q.aggregate(q=Sum('qty'))['q'] or 0),
                    'value': round(exp_val, 2)},
        'total_at_risk_value': round(b30['value'] + b90['value'] + b180['value'], 2),
    }
