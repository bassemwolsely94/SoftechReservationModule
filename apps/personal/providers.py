"""
apps/personal/providers.py — the WIDGET CATALOG for the personal dashboard.

Each entry maps a `widget_type` to:
    kind   — the SoftechIdentityClaim.kind a widget of this type binds to
             ('supplier' / 'customer' / 'salesperson').
    label  — Arabic catalog label shown in the "add widget" picker.
    icon   — emoji for the picker/card.
    source — 'softech_live' (bounded live SELECT, cached) or 'mirror' (Postgres).
    fetch  — callable(person_key, config) -> dict payload for the card.

Every provider is called as ``fetch(person_key, config, staff)``:
    person_key — the already-resolved & authorised SOFTECH code:
        supplier/customer widgets → the APPROVED claim's personcode
        salesperson widgets       → the claim's usercode, else the staff's own
                                    softech_user_id (see views.resolve_person_key)
        self widgets (my_tasks)   → None (bound to the staff, not a SOFTECH code)
    config     — the widget's JSON config (period, limits, chart type …).
    staff      — the requesting StaffProfile (used by self-scoped widgets).

Nothing here trusts a client-supplied code — resolution + the approved-claim
ownership check happen in the view before fetch() is called.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum, Count, Q
from django.utils import timezone

from . import queries


# ── config helpers ────────────────────────────────────────────────────────────

def _days(config: dict, default: int = 90) -> int:
    try:
        d = int((config or {}).get('period_days', default))
    except (TypeError, ValueError):
        d = default
    return max(1, min(d, 1095))  # clamp 1 day … 3 years


# ── SOFTECH-live providers (supplier / customer) ──────────────────────────────

def _supplier_transactions(person_key, config, staff=None):
    return queries.supplier_transactions(person_key, days=_days(config, 90))


def _supplier_payments(person_key, config, staff=None):
    return queries.supplier_payments(person_key, days=_days(config, 180))


def _customer_transactions(person_key, config, staff=None):
    return queries.customer_transactions(person_key, days=_days(config, 180))


def _customer_payments(person_key, config, staff=None):
    return queries.customer_payments(person_key, days=_days(config, 180))


# ── Mirror providers (salesperson / author — Postgres, fast) ──────────────────

def _my_sales(person_key, config, staff=None):
    """Aggregate the caller's own sales from the mirrored PurchaseHistory.

    `person_key` is the SOFTECH cashier/salesperson usercode
    (PurchaseHistory.softech_user).
    """
    from apps.customers.models import PurchaseHistory

    usercode = str(person_key or '').strip()
    if not usercode:
        return {'error': 'no usercode'}
    days = _days(config, 30)
    since = timezone.now() - timedelta(days=days)
    qs = PurchaseHistory.objects.filter(softech_user=usercode, invoice_date__gte=since)

    sales = qs.filter(doc_code='115')
    returns = qs.filter(doc_code='30')
    agg = sales.aggregate(revenue=Sum('total_amount'), invoices=Count('id'))
    ret = returns.aggregate(value=Sum('total_amount'), count=Count('id'))

    # daily trend
    trend = {}
    for row in (sales.values('invoice_date__date')
                     .annotate(v=Sum('total_amount'), n=Count('id'))
                     .order_by('invoice_date__date')):
        d = row['invoice_date__date']
        if d:
            trend[str(d)] = {'value': float(row['v'] or 0), 'invoices': row['n']}

    return {
        'days': days,
        'revenue':       float(agg['revenue'] or 0),
        'invoices':      agg['invoices'] or 0,
        'returns_value': float(ret['value'] or 0),
        'returns_count': ret['count'] or 0,
        'trend':         [{'date': k, **v} for k, v in trend.items()],
    }


def _my_analytics(person_key, config, staff=None):
    """Top items + sales-channel mix for the caller's own sales (mirror)."""
    from apps.customers.models import PurchaseHistoryLine, PurchaseHistory

    usercode = str(person_key or '').strip()
    if not usercode:
        return {'error': 'no usercode'}
    days = _days(config, 90)
    since = timezone.now() - timedelta(days=days)
    base = PurchaseHistory.objects.filter(
        softech_user=usercode, doc_code='115', invoice_date__gte=since,
    )

    channels = list(
        base.values('sales_channel')
            .annotate(value=Sum('total_amount'), invoices=Count('id'))
            .order_by('-value')[:10]
    )
    top_items = list(
        PurchaseHistoryLine.objects
        .filter(purchase__in=base)
        .values('item__softech_id', 'item__name')
        .annotate(qty=Sum('quantity'), value=Sum('line_total'))
        .order_by('-value')[:15]
    )
    return {
        'days': days,
        'channels': [
            {'channel': c['sales_channel'] or '—',
             'value': float(c['value'] or 0), 'invoices': c['invoices']}
            for c in channels
        ],
        'top_items': [
            {'softech_id': t['item__softech_id'], 'name': t['item__name'] or '—',
             'qty': float(t['qty'] or 0), 'value': float(t['value'] or 0)}
            for t in top_items
        ],
    }


def _my_narrative_reports(person_key, config, staff=None):
    """The caller's own narrative-audit findings (apps.insights, salesperson scope)."""
    try:
        from apps.insights.models import InsightFinding
    except Exception:
        return {'error': 'insights app unavailable'}

    usercode = str(person_key or '').strip()
    if not usercode:
        return {'error': 'no usercode'}
    limit = int((config or {}).get('limit', 30))
    qs = (
        InsightFinding.objects
        .filter(scope_type='salesperson', scope_key=usercode)
        .select_related('run')
        .order_by('-run__period_start', 'severity')[:limit]
    )
    findings = [
        {
            'rule_code':  f.rule_code,
            'category':   f.category,
            'severity':   f.severity,
            'message_ar': f.message_ar,
            'value':      float(f.value) if f.value is not None else None,
            'baseline':   float(f.baseline) if f.baseline is not None else None,
            'period':     str(f.run.period_start) if f.run_id else None,
            'period_type': f.run.period_type if f.run_id else None,
        }
        for f in qs
    ]
    counts = {'critical': 0, 'warning': 0, 'info': 0}
    for f in findings:
        counts[f['severity']] = counts.get(f['severity'], 0) + 1
    return {'findings': findings, 'counts': counts}


# ── Self-scoped providers (bound to the staff, not a SOFTECH code) ────────────

def _my_tasks(person_key, config, staff=None):
    """The caller's allocated operational tasks.

    REUSE — reads the SAME queryset as GET /api/tasks/my/ via the shared
    selector apps.tasks.selectors.tasks_for_staff, so the personal-dashboard
    view and the tasks module never drift. No new task concept is introduced.
    """
    if staff is None:
        return {'error': 'no staff'}
    try:
        from apps.tasks.selectors import tasks_for_staff
        from apps.tasks.serializers import TaskListSerializer
    except Exception:
        return {'error': 'tasks app unavailable'}

    limit = int((config or {}).get('limit', 50))
    include_done = bool((config or {}).get('include_done'))
    qs = list(tasks_for_staff(staff, include_done=include_done)[:limit])
    data = TaskListSerializer(qs, many=True).data
    overdue = sum(1 for t in qs if getattr(t, 'is_overdue', False))
    open_count = sum(1 for t in qs if t.status not in ('completed', 'cancelled'))
    return {
        'count':   len(data),
        'open':    open_count,
        'overdue': overdue,
        'tasks':   data,
    }


# ── the catalog ───────────────────────────────────────────────────────────────

WIDGET_REGISTRY: dict[str, dict] = {
    'supplier_transactions': {
        'kind': 'supplier', 'source': 'softech_live', 'icon': '📦',
        'label': 'مشتريات المورد (stktrans)',
        'desc':  'فواتير الشراء والمرتجعات المسجّلة على المورد',
        'fetch': _supplier_transactions,
    },
    'supplier_payments': {
        'kind': 'supplier', 'source': 'softech_live', 'icon': '💸',
        'label': 'مدفوعات المورد (شيكات ودفعات)',
        'desc':  'الشيكات والدفعات المرتبطة بكود المورد',
        'fetch': _supplier_payments,
    },
    'customer_transactions': {
        'kind': 'customer', 'source': 'softech_live', 'icon': '🧾',
        'label': 'مبيعات العميل (stktrans)',
        'desc':  'فواتير البيع والمرتجعات على كود العميل / الموظف',
        'fetch': _customer_transactions,
    },
    'customer_payments': {
        'kind': 'customer', 'source': 'softech_live', 'icon': '💰',
        'label': 'مدفوعات العميل (تحصيلات ودفعات)',
        'desc':  'تحصيلات العميل والدفعات المسجّلة',
        'fetch': _customer_payments,
    },
    'my_sales': {
        'kind': 'salesperson', 'source': 'mirror', 'icon': '📈',
        'label': 'مبيعاتي',
        'desc':  'إجمالي مبيعاتك كمسؤول بيع خلال الفترة',
        'fetch': _my_sales,
    },
    'my_analytics': {
        'kind': 'salesperson', 'source': 'mirror', 'icon': '📊',
        'label': 'تحليلات مبيعاتي',
        'desc':  'أعلى الأصناف ومزيج القنوات لمبيعاتك',
        'fetch': _my_analytics,
    },
    'my_narrative_reports': {
        'kind': 'salesperson', 'source': 'mirror', 'icon': '📝',
        'label': 'تقاريري السردية',
        'desc':  'ملاحظات التحليل السردي الخاصة بك',
        'fetch': _my_narrative_reports,
    },
    'my_tasks': {
        'kind': 'self', 'source': 'mirror', 'icon': '✅',
        'label': 'مهامي المسندة',
        'desc':  'المهام التشغيلية المُسنَدة إليك (نفس مصدر شاشة «مهامي»)',
        'fetch': _my_tasks,
    },
}


def catalog() -> list[dict]:
    """Serialisable widget catalog for the 'add widget' picker."""
    return [
        {
            'widget_type': key,
            'kind':        meta['kind'],
            'source':      meta['source'],
            'icon':        meta['icon'],
            'label':       meta['label'],
            'desc':        meta['desc'],
        }
        for key, meta in WIDGET_REGISTRY.items()
    ]
