"""
apps/supply/kpis.py — Demand & Supply Control-Tower KPIs (doc 24 §25).

Every KPI is computed deterministically from records this module already keeps
(SupplyCase, SupplyDecision, AvailabilityLine, the draft TransferRequests it created), and
is returned WITH its formula in ``definitions`` so the dashboard can show exactly what a
number means. A ratio with an empty denominator is None ("—"), never a misleading 0 or 100%.

Window: ``days`` (default 30) applies to flows (resolutions, decisions, lines); the open
queue is a live snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import median

from django.utils import timezone

from .cases import SCOPE_CLOSE_REASON
from .models import AvailabilityBatch, AvailabilityLine, SupplyCase, SupplyDecision

# Transfer-request statuses where the move actually happened / was committed by the
# transfers team (a draft or pending request has not saved any cash yet).
REALIZED_TRANSFER_STATUSES = ('approved', 'sent_to_erp', 'completed')
DEAD_TRANSFER_STATUSES = ('rejected', 'cancelled')
STALE_BATCH_DAYS = 7

DEFINITIONS = {
    'avg_days_to_resolve': 'متوسط (تاريخ الإغلاق − أول اكتشاف) بالأيام للحالات التي أُغلقت «مُلبّاة» خلال الفترة',
    'median_days_to_resolve': 'الوسيط لنفس المدة — أقل تأثراً بالحالات الشاذة',
    'internal_share': 'كمية التحويل الداخلي ÷ (التحويل الداخلي + الشراء الخارجي) من قرارات الفترة؛ لا تُحسب المسودات المرفوضة/الملغاة ولا الطلبات الملغاة',
    'external_share': 'كمية الشراء الخارجي ÷ نفس المقام',
    'supplier_fill_rate': 'كمية طلبات الشراء المستلمة ÷ (المستلمة + الملغاة) لطلبات الفترة التي حُسمت',
    'cash_avoided': 'Σ كمية التحويلات الداخلية المُنفَّذة (معتمدة/مرسلة للـERP/مكتملة) × آخر تكلفة شراء فعلية للوحدة — أي نقد لم يُصرف لأن المخزون نُقل بدل أن يُشترى',
    'auto_match_rate': 'الأسطر التي اقترح لها النظام صنفاً عند الاستيراد ÷ كل الأسطر',
    'match_precision': 'من الأسطر المؤكدة التي كان لها اقتراح: نسبة ما أُكّد كما اقترحه النظام',
    'correction_rate': 'من الأسطر المؤكدة التي كان لها اقتراح: نسبة ما صحّحه المستخدم إلى صنف آخر',
    'manual_match_rate': 'الأسطر المؤكدة التي لم يقترح لها النظام شيئاً ÷ كل الأسطر المؤكدة',
    'override_rate': 'القرارات التي خالفت التوصية (أكثر من الاحتياج المقرّب لأعلى أو أقل منه) ÷ كل القرارات',
    'committed_value': 'Σ الكمية المطلوبة × السعر المعروض لطلبات الشراء (غير الملغاة) خلال الفترة',
    'foc_savings': 'Σ (السعر المعروض − التكلفة الفعلية بعد البونص) × الكمية لطلبات الشراء',
}


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _ratio(num, den, digits=3):
    return round(num / den, digits) if den else None


def _unit_costs(item_ids) -> dict:
    """{item_id: unit cost} = the most recent actual purchase effective cost (tax + FOC
    aware, apps.procurement.PurchaseLine); falls back to the supplier map's last price."""
    from apps.catalog.models import Item
    from apps.procurement.models import PurchaseLine, SupplierItemMapping
    ids = [i for i in set(item_ids) if i]
    costs = {}
    for row in (PurchaseLine.objects.filter(item_id__in=ids, is_return=False, effective_cost__gt=0)
                .order_by('item_id', '-doc_date').values('item_id', 'effective_cost')):
        costs.setdefault(row['item_id'], _f(row['effective_cost']))       # first = latest
    missing = [i for i in ids if i not in costs]
    if missing:
        code_to_id = dict(Item.objects.filter(pk__in=missing).values_list('softech_id', 'id'))
        for m in (SupplierItemMapping.objects.filter(item_code__in=list(code_to_id), last_price__gt=0)
                  .order_by('item_code', '-last_purchase_date').values('item_code', 'last_price')):
            iid = code_to_id.get(m['item_code'])
            if iid and iid not in costs:
                costs[iid] = _f(m['last_price'])
    return costs


def supply_kpis(*, days: int = 30, branch_id=None) -> dict:
    now = timezone.now()
    since = now - timedelta(days=days)

    # ── 1. Open queue (live snapshot) ─────────────────────────────────────────────
    from .cases import queue_summary
    queue = queue_summary(branch_id=branch_id)

    # ── 2. Time to resolve ───────────────────────────────────────────────────────
    resolved = SupplyCase.objects.filter(status=SupplyCase.STATUS_FULFILLED,
                                         closed_at__gte=since, closed_at__isnull=False)
    if branch_id:
        resolved = resolved.filter(branch_id=branch_id)
    durations = [(c.closed_at - c.first_detected_at).total_seconds() / 86400.0
                 for c in resolved.only('closed_at', 'first_detected_at')]
    resolution = {
        'resolved_count': len(durations),
        'avg_days_to_resolve': round(sum(durations) / len(durations), 1) if durations else None,
        'median_days_to_resolve': round(median(durations), 1) if durations else None,
        # A scope closure is queue housekeeping (item left the follow-up scope), not a
        # shortage someone gave up on — counted separately so it can't inflate "cancelled".
        'cancelled_count': SupplyCase.objects.filter(
            status=SupplyCase.STATUS_CANCELLED, closed_at__gte=since,
            **({'branch_id': branch_id} if branch_id else {}))
            .exclude(close_reason__startswith=SCOPE_CLOSE_REASON).count(),
        'scoped_out_count': SupplyCase.objects.filter(
            status=SupplyCase.STATUS_CANCELLED, closed_at__gte=since,
            close_reason__startswith=SCOPE_CLOSE_REASON,
            **({'branch_id': branch_id} if branch_id else {})).count(),
    }

    # ── 3. Sourcing mix + cash avoided ───────────────────────────────────────────
    decisions = SupplyDecision.objects.filter(created_at__gte=since).select_related('item')
    if branch_id:
        decisions = decisions.filter(branch_id=branch_id)
    decisions = list(decisions)

    from apps.transfers.models import TransferRequest
    tr_ids = [t for d in decisions if d.kind == SupplyDecision.KIND_INTERNAL_TRANSFER
              for t in (d.result_refs or {}).get('transfer_requests', [])]
    trs = {t.pk: t for t in TransferRequest.objects.filter(pk__in=tr_ids).prefetch_related('items')}

    internal_realized = defaultdict(float)     # item_id → qty actually moved / committed
    internal_in_progress = internal_dead = 0.0
    for d in decisions:
        if d.kind != SupplyDecision.KIND_INTERNAL_TRANSFER:
            continue
        for tid in (d.result_refs or {}).get('transfer_requests', []):
            tr = trs.get(tid)
            if tr is None:
                continue
            qty = sum(_f(i.approved_quantity if i.approved_quantity is not None else i.quantity)
                      for i in tr.items.all() if i.item_id == d.item_id)
            if tr.status in REALIZED_TRANSFER_STATUSES:
                internal_realized[d.item_id] += qty
            elif tr.status in DEAD_TRANSFER_STATUSES:
                internal_dead += qty
            else:
                internal_in_progress += qty

    purchases = [d for d in decisions if d.kind == SupplyDecision.KIND_PURCHASE]
    live_purchases = [d for d in purchases if d.receipt_status != SupplyDecision.RECEIPT_CANCELLED]
    internal_qty = sum(internal_realized.values()) + internal_in_progress
    external_qty = sum(_f(d.decided_qty) for d in live_purchases)
    received = sum(_f(d.decided_qty) for d in purchases if d.receipt_status == SupplyDecision.RECEIPT_RECEIVED)
    cancelled = sum(_f(d.decided_qty) for d in purchases if d.receipt_status == SupplyDecision.RECEIPT_CANCELLED)

    costs = _unit_costs(internal_realized.keys())
    cash_avoided = sum(q * costs.get(iid, 0.0) for iid, q in internal_realized.items())
    unvalued_qty = sum(q for iid, q in internal_realized.items() if iid not in costs)

    sourcing = {
        'internal_qty': round(internal_qty, 3),
        'internal_realized_qty': round(sum(internal_realized.values()), 3),
        'internal_in_progress_qty': round(internal_in_progress, 3),
        'internal_rejected_qty': round(internal_dead, 3),
        'external_qty': round(external_qty, 3),
        'internal_share': _ratio(internal_qty, internal_qty + external_qty),
        'external_share': _ratio(external_qty, internal_qty + external_qty),
        'supplier_fill_rate': _ratio(received, received + cancelled),
        'cash_avoided': round(cash_avoided, 2),
        'cash_avoided_unvalued_qty': round(unvalued_qty, 3),
    }

    # ── 4. Procurement decisions ─────────────────────────────────────────────────
    procurement = {
        'orders': len({d.order_ref for d in live_purchases if d.order_ref}),
        'order_lines': len(live_purchases),
        'committed_value': round(sum(_f(d.decided_qty) * _f(d.unit_price)
                                     for d in live_purchases if d.unit_price is not None), 2),
        'foc_savings': round(sum((_f(d.unit_price) - _f(d.effective_cost)) * _f(d.decided_qty)
                                 for d in live_purchases
                                 if d.unit_price is not None and d.effective_cost is not None), 2),
        'override_rate': _ratio(sum(1 for d in decisions if d.is_override), len(decisions)),
        'decisions': len(decisions),
    }

    # ── 5. Catalog-match accuracy (availability inbox) ───────────────────────────
    lines = AvailabilityLine.objects.filter(created_at__gte=since).only(
        'item_id', 'is_confirmed', 'match_reason')
    total = suggested = confirmed = accepted = corrected = manual = unmatched = 0
    for ln in lines.iterator():
        total += 1
        sug = (ln.match_reason or {}).get('suggested_item_id')
        if sug:
            suggested += 1
        if not ln.item_id:
            unmatched += 1
        if ln.is_confirmed and ln.item_id:
            confirmed += 1
            if not sug:
                manual += 1
            elif sug == ln.item_id:
                accepted += 1
            else:
                corrected += 1
    matching = {
        'lines': total,
        'auto_match_rate': _ratio(suggested, total),
        'match_precision': _ratio(accepted, accepted + corrected),
        'correction_rate': _ratio(corrected, accepted + corrected),
        'manual_match_rate': _ratio(manual, confirmed),
        'confirmed_lines': confirmed,
        'unmatched_lines': unmatched,
    }

    # ── 6. Supplier availability intake ──────────────────────────────────────────
    batches = AvailabilityBatch.objects.filter(created_at__gte=since)
    availability = {
        'batches': batches.count(),
        'stale_open_batches': AvailabilityBatch.objects.filter(
            status=AvailabilityBatch.STATUS_OPEN,
            created_at__lt=now - timedelta(days=STALE_BATCH_DAYS)).count(),
    }

    return {
        'window_days': days,
        'generated_at': now.isoformat(),
        'queue': queue,
        'resolution': resolution,
        'sourcing': sourcing,
        'procurement': procurement,
        'matching': matching,
        'availability': availability,
        'definitions': DEFINITIONS,
    }
