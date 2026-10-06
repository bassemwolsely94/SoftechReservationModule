"""
apps/offers/views.py — Offer CRUD + the read-only evaluation endpoint.

`/api/offers/evaluate/` computes the deterministic discount PLAN for a basket. It
NEVER writes to SOFTECH and never persists — execution is a separate gated batch.
"""
from decimal import Decimal

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Offer
from .serializers import OfferSerializer
from .permissions import CanManageOffers
from .engine import evaluate_offers


COST_VISIBLE_ROLES = {'admin', 'supervisor', 'purchasing'}


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_see_cost(request):
    p = _profile(request)
    return bool(p and p.role in COST_VISIBLE_ROLES)


def _mask_margin(plan, can_see_cost):
    """Strip cost-bearing fields (cogs, margin %) for roles not allowed to see cost.
    The operational signals (breached, requires_approval, floor) stay visible."""
    if can_see_cost:
        return plan
    margin = plan.get('margin')
    if margin and margin.get('lines'):
        margin['lines'] = [{'index': l['index'], 'net': l['net'], 'breached': l['breached']}
                           for l in margin['lines']]
        margin['cost_masked'] = True
    return plan


class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.all().prefetch_related('items', 'categories', 'tags', 'branches')
    serializer_class = OfferSerializer
    permission_classes = [CanManageOffers]
    filterset_fields = ['status', 'offer_type', 'stackable', 'is_clearance']
    search_fields = ['name', 'name_ar']
    ordering_fields = ['priority', 'name', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))

    # ── Contradiction checks (no items / loss / overlap / priority) ───────────
    @action(detail=True, methods=['get'], url_path='validate')
    def validate(self, request, pk=None):
        from .validation import validate_offer
        return Response({'warnings': validate_offer(self.get_object())})

    # ── Channel A: flat-rate offer → item posdiscp (dry-run planner) ──────────
    @action(detail=True, methods=['get'], url_path='posdiscp-plan')
    def posdiscp_plan(self, request, pk=None):
        """Dry-run: the exact posdiscp changes this flat-rate offer implies (no writes)."""
        from .channel_a import plan_posdiscp
        branch = request.query_params.get('branch')
        plan = plan_posdiscp(self.get_object(),
                             branch_id=int(branch) if branch and str(branch).isdigit() else None)
        # cap the item list in the response
        plan_out = {**plan, 'changes': plan['changes'][:500], 'truncated': len(plan['changes']) > 500}
        return Response(plan_out)

    @action(detail=True, methods=['get'], url_path='promo-plan')
    def promo_plan(self, request, pk=None):
        """Channel B dry-run: the native specialoffers row(s) we'd write (no writes)."""
        from .channel_b import plan_channel_b
        return Response(plan_channel_b(self.get_object()))

    @action(detail=True, methods=['post'], url_path='promo-apply')
    def promo_apply(self, request, pk=None):
        """Channel B gated live write into SOFTECH specialoffers. Admin only."""
        from .channel_b import apply_channel_b
        p = _profile(request)
        if not (p and p.role == 'admin'):
            return Response({'detail': 'يتطلب صلاحية مدير'}, status=status.HTTP_403_FORBIDDEN)
        confirm = str(request.data.get('confirm')).lower() in ('1', 'true')
        result = apply_channel_b(self.get_object(), actor=p, commit=True, confirm=confirm)
        if result.get('requires_confirm'):
            return Response(result, status=status.HTTP_409_CONFLICT)
        return Response(result)

    @action(detail=True, methods=['post'], url_path='posdiscp-apply')
    def posdiscp_apply(self, request, pk=None):
        """
        A2 — gated live posdiscp write. Admin only. Writes to SOFTECH ONLY when the
        flag is on AND confirm=true AND the actor has a linked SOFTECH usercode;
        otherwise returns the dry-run plan (409 if it just needs confirmation).
        """
        from .channel_a import apply_posdiscp
        p = _profile(request)
        if not (p and p.role == 'admin'):
            return Response({'detail': 'يتطلب صلاحية مدير'}, status=status.HTTP_403_FORBIDDEN)
        confirm = str(request.data.get('confirm')).lower() in ('1', 'true')
        result = apply_posdiscp(self.get_object(), actor=p, commit=True, confirm=confirm)
        if result.get('requires_confirm'):
            return Response(result, status=status.HTTP_409_CONFLICT)
        return Response(result)


def _decimalify(plan):
    """JSON-safe: Decimals → float for the API response."""
    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    return conv(plan)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def evaluate(request):
    """
    POST { basket: [{softech_id, qty, unit_price}], customer, branch, channel }
    → deterministic discount plan. Read-only, no SOFTECH write, no persistence.
    """
    data = request.data or {}
    raw_basket = data.get('basket') or []
    if not isinstance(raw_basket, list) or not raw_basket:
        return Response({'detail': 'basket مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

    # Resolve items by softech_id so targeting (category/tag/classification) works.
    codes = [str(l.get('softech_id')) for l in raw_basket if l.get('softech_id')]
    item_map = {}
    if codes:
        from apps.catalog.models import Item
        item_map = {i.softech_id: i for i in
                    Item.objects.filter(softech_id__in=codes)
                    .select_related('category')}

    basket = []
    for l in raw_basket:
        code = str(l.get('softech_id') or '')
        basket.append({
            'softech_id': code,
            'item': item_map.get(code),
            'qty': l.get('qty', 0),
            'unit_price': l.get('unit_price', 0),
        })

    customer = None
    cid = data.get('customer')
    if cid:
        from apps.customers.models import Customer
        customer = Customer.objects.filter(pk=cid).only('id', 'segment').first()

    branch_id = data.get('branch')
    branch_id = int(branch_id) if branch_id and str(branch_id).isdigit() else None

    from .models import MarginConfig
    margin_cfg = MarginConfig.get_solo()

    if str(data.get('attach_preview')).lower() in ('1', 'true'):
        # DRY-RUN attach: also returns the per-line cust_discp we WOULD write +
        # the SOFTECH-recompute reconciliation. Writes nothing; no SOFTECH contact.
        from .attach import build_attach_plan
        out = build_attach_plan(basket, customer=customer, branch_id=branch_id,
                                channel=data.get('channel'), margin_cfg=margin_cfg)
        out['plan'] = _mask_margin(out['plan'], _can_see_cost(request))
        return Response(_decimalify(out))

    plan = evaluate_offers(basket, customer=customer, branch_id=branch_id,
                           channel=data.get('channel'), margin_cfg=margin_cfg)
    plan = _mask_margin(plan, _can_see_cost(request))
    return Response(_decimalify(plan))


TARGET_FIELD_LABELS = {
    'producer_code': 'الشركة المنتجة (كود)', 'producer_name': 'الشركة المنتجة',
    'supplier_code': 'المورد الرئيسي (كود)', 'supplier_name': 'المورد الرئيسي',
    'name': 'اسم الصنف', 'name_scientific': 'الاسم العلمي',
    'family_code': 'العائلة (كود)', 'family_name': 'العائلة',
    'medicine_type': 'التصنيف العام (كود)', 'medicine_type_name': 'التصنيف العام',
    'store_classif': 'تصنيف التعاقدات',
    'origin_code': 'بلد المنشأ (كود)', 'origin_name': 'بلد المنشأ',
    'shape_code': 'الشكل الصيدلي (كود)', 'shape_name': 'الشكل الصيدلي',
    'effect_code': 'دواعي الاستعمال (كود)', 'unit_code': 'الوحدة (كود)', 'unit_name': 'الوحدة',
    'insurance_type': 'نوع التأمين', 'category': 'التصنيف', 'item_level': 'مستوى الصنف',
    'pack_price': 'سعر العبوة', 'unit_price': 'سعر الوحدة',
    'requires_fridge': 'يحفظ بالثلاجة', 'is_fast_moving': 'سريع الحركة',
    'is_imported': 'مستورد', 'no_more_use': 'موقوف', 'item_archive': 'مؤرشف',
    'is_stockable': 'قابل للتخزين', 'in_shortage': 'نقص بالسوق',
}
# fields whose distinct values are worth offering as a multi-select dropdown (via field-values)
FIELD_VALUE_PAIRS = {
    'producer_code': 'producer_name', 'supplier_code': 'supplier_name',
    'family_code': 'family_name', 'medicine_type': 'medicine_type_name',
    'origin_code': 'origin_name', 'shape_code': 'shape_name',
    'unit_code': 'unit_name', 'store_classif': 'store_classif_name',
}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def target_fields(request):
    """Whitelisted selector fields (key, label, type, ops, has_values) for the config UI."""
    from .targeting import FIELDS
    ops_by_type = {
        'str':  ['in', 'not_in', 'contains', 'eq', 'ne'],
        'num':  ['range', 'gte', 'lte', 'eq', 'ne', 'in', 'not_in'],
        'bool': ['is_true', 'is_false'],
    }
    return Response([
        {'field': k, 'label': TARGET_FIELD_LABELS.get(k, k), 'type': t, 'ops': ops_by_type[t],
         'has_values': k in FIELD_VALUE_PAIRS}
        for k, (_mf, t) in FIELDS.items()
    ])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def field_values(request):
    """Distinct {value,label} for a code field, so the UI can multi-select from real
    values (e.g. all producers). ?field=producer_code&q=<filter>."""
    from .targeting import FIELDS
    from apps.catalog.models import Item
    from django.db.models import Q
    field = request.query_params.get('field')
    if field not in FIELD_VALUE_PAIRS or field not in FIELDS:
        return Response({'detail': 'حقل غير مدعوم'}, status=status.HTTP_400_BAD_REQUEST)
    code_col = FIELDS[field][0]
    label_col = FIELD_VALUE_PAIRS[field]
    qs = (Item.objects.exclude(**{f'{code_col}__in': ['', None]})
          .values(code_col, label_col).distinct())
    q = request.query_params.get('q')
    if q:
        qs = qs.filter(Q(**{f'{code_col}__icontains': q}) | Q(**{f'{label_col}__icontains': q}))
    rows, seen = [], set()
    for r in qs.order_by(label_col or code_col)[:400]:
        v = str(r[code_col])
        if v in seen:
            continue
        seen.add(v)
        rows.append({'value': v, 'label': r.get(label_col) or v})
    return Response(rows)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def target_preview(request):
    """
    Resolve a selector spec → count + sample of matching items (config preview).
    Body: { target_all, target_spec, include_ids, category_ids, tag_ids,
            classification_filters, exclude_ids, require_stock, branch }.
    """
    from .targeting import preview_items
    d = request.data or {}
    branch = d.get('branch')
    qs = preview_items(
        target_all=bool(d.get('target_all')),
        target_spec=d.get('target_spec'),
        include_ids=d.get('include_ids'), category_ids=d.get('category_ids'),
        tag_ids=d.get('tag_ids'), classification_filters=d.get('classification_filters'),
        exclude_ids=d.get('exclude_ids'),
        require_stock=bool(d.get('require_stock')),
        branch_id=int(branch) if branch and str(branch).isdigit() else None,
    )
    total = qs.count()
    try:
        limit = min(max(int(d.get('limit') or 50), 1), 500)
    except (TypeError, ValueError):
        limit = 50
    sample = list(qs.only('id', 'softech_id', 'name', 'pack_price', 'pos_discp', 'cost_price')[:limit])
    return Response({
        'count': total,
        'sample': [{'id': i.id, 'softech_id': i.softech_id, 'name': i.name,
                    'pack_price': float(i.pack_price or 0),
                    'pos_discp': float(i.pos_discp or 0),
                    'cost_price': float(i.cost_price or 0)} for i in sample],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_to_order(request):
    """
    Attach the offer plan onto a real POS order (PG only; no SOFTECH). Gated behind
    POS_OFFERS_EXECUTION_ENABLED. Body: { order: <id>, commit: true }.
    """
    from apps.pos_orders.models import SoftechSalesOrder
    from .order_attach import apply_offers_to_order
    oid = request.data.get('order')
    order = SoftechSalesOrder.objects.filter(pk=oid).first()
    if not order:
        return Response({'detail': 'أمر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    if order.is_locked:
        return Response({'detail': 'الأمر مقفل — لا يمكن تعديله.'}, status=status.HTTP_409_CONFLICT)
    commit = str(request.data.get('commit', True)).lower() not in ('0', 'false')
    result = apply_offers_to_order(order, actor=_profile(request), commit=commit)
    return Response(_decimalify(result))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def manual_matches(request):
    """
    List detected historical manual-promo matches (read-only). Filters:
    ?pattern=&confidence=&branch=&limit=. Also returns a counts summary.
    """
    from django.db.models import Count
    from .models import ManualOfferMatch
    qs = ManualOfferMatch.objects.select_related('matched_offer', 'item', 'branch', 'purchase')
    for f in ('pattern', 'confidence'):
        v = request.query_params.get(f)
        if v:
            qs = qs.filter(**{f: v})
    branch = request.query_params.get('branch')
    if branch and str(branch).isdigit():
        qs = qs.filter(branch_id=int(branch))
    summary = {row['pattern']: row['n'] for row in qs.values('pattern').annotate(n=Count('id'))}
    try:
        limit = min(int(request.query_params.get('limit', 100)), 500)
    except (TypeError, ValueError):
        limit = 100
    rows = [{
        'id': m.id, 'invoice_id': m.purchase_id,
        'item': (m.item.name if m.item_id else None),
        'softech_id': (m.item.softech_id if m.item_id else None),
        'matched_offer': (m.matched_offer.name if m.matched_offer_id else None),
        'pattern': m.pattern, 'pattern_label': m.get_pattern_display(),
        'confidence': m.confidence,
        'disc_pct': float(m.disc_pct), 'discount_amount': float(m.discount_amount),
        'branch': (m.branch.name if m.branch_id else None),
        'invoice_date': m.invoice_date.isoformat() if m.invoice_date else None,
        'detail': m.detail,
    } for m in qs.order_by('-invoice_date')[:limit]]
    return Response({'summary': summary, 'count': len(rows), 'results': rows})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_manual_detection(request):
    """Trigger a detection scan (admin/supervisor/purchasing). Read-only vs SOFTECH."""
    p = _profile(request)
    if not (p and p.role in COST_VISIBLE_ROLES):
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    from datetime import timedelta
    from django.utils import timezone
    from .detection import detect_manual_offers
    months = request.data.get('months')
    since = (timezone.now() - timedelta(days=30 * int(months))) if months else None
    branch = request.data.get('branch')
    counts = detect_manual_offers(since=since,
                                  branch_id=int(branch) if branch else None,
                                  limit=request.data.get('limit'))
    return Response(counts)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def margin_config(request):
    """Margin-protection floor (singleton). PATCH is admin-only."""
    from .models import MarginConfig
    cfg = MarginConfig.get_solo()
    if request.method == 'PATCH':
        p = _profile(request)
        if not (p and p.role == 'admin'):
            return Response({'detail': 'يتطلب صلاحية مدير'}, status=status.HTTP_403_FORBIDDEN)
        if 'min_margin_percent' in request.data:
            cfg.min_margin_percent = request.data['min_margin_percent']
        if 'enforce' in request.data:
            cfg.enforce = bool(request.data['enforce'])
        cfg.updated_by = p
        cfg.save()
    return Response({
        'min_margin_percent': float(cfg.min_margin_percent),
        'enforce': cfg.enforce,
        'updated_at': cfg.updated_at.isoformat() if cfg.updated_at else None,
    })
