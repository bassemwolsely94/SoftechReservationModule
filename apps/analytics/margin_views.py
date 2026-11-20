"""
apps/analytics/margin_views.py — C19 / P-35 «💹 الهامش: قناة × فرع» board. READ-ONLY report.

  GET /api/analytics/margin-board/   (the sales dashboard's filters: date_from / date_to / branches / channels / …)

One row per sales channel (PurchaseHistory.sales_channel = the customer's SOFTECH classification), one column per live
branch in the user's scope, every cell on the ONE margin basis of apps/analytics/margin.py (VAT-aligned), with the old
VAT-inclusive margin beside it so the gap is visible. Net = sales (115) − returns (30), doccode 80 excluded — the same
filtered queryset as /api/analytics/sales/, so the totals equal that screen's ex-VAT fields.

Sales booked on a branch that is no longer live (closed / pending) stay in the totals under one «فروع أخرى» column with
no branch code, so the grand total still equals the sales screen.

Delivery fee contribution = delivery.DeliveryOrder.delivery_fees of the orders delivered in the period, per branch (the
delivery module's own figure; shown beside the board, never added into the SOFTECH sales margin).

Analytics module rights (matrix_permission('analytics')); branch users see their branches only (core.branch_scope, via
the shared filter). Nothing is written.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import branch_scope

from . import margin as M
from .views import ANALYTICS, _get_channel_label_map, _line_qs_for, _parse_date, _purchase_qs_filtered

OTHER = '__other__'
ZERO = Decimal('0')


def _cell(acc) -> dict:
    rev, rev_ex, cogs = acc['rev'], acc['rev_ex'], acc['cogs']
    profit_ex = rev_ex - cogs
    profit_incl = rev - cogs
    return {'revenue': M.money(rev), 'revenue_ex_vat': M.money(rev_ex), 'cogs': M.money(cogs),
            'profit_ex_vat': M.money(profit_ex), 'margin_ex_vat_pct': M.margin_pct(profit_ex, rev_ex),
            'profit_incl_vat': M.money(profit_incl), 'margin_incl_vat_pct': M.margin_pct(profit_incl, rev)}


def _blank():
    return {'rev': ZERO, 'rev_ex': ZERO, 'cogs': ZERO}


def _add(a, b, sign=1):
    for k in a:
        a[k] += sign * b[k]


def board(params, user) -> dict:
    from apps.branches.models import Branch
    qs = _purchase_qs_filtered(params, user)
    line_qs = _line_qs_for(qs, params)
    rev, rev_ex, cogs, _profit = M.line_expressions()
    agg = {}
    # one grouped query: sales (115) and returns (30) as conditional sums, netted here
    sale, ret = Q(purchase__doc_code='115'), Q(purchase__doc_code='30')
    for row in (line_qs.filter(purchase__doc_code__in=('115', '30'))
                .values('purchase__sales_channel', 'purchase__branch_id').order_by()
                .annotate(rev_s=Sum(rev, filter=sale), rev_ex_s=Sum(rev_ex, filter=sale),
                          cogs_s=Sum(cogs, filter=sale), rev_r=Sum(rev, filter=ret),
                          rev_ex_r=Sum(rev_ex, filter=ret), cogs_r=Sum(cogs, filter=ret))):
        key = (row['purchase__sales_channel'] or '', row['purchase__branch_id'])
        a = agg.setdefault(key, _blank())
        for k in ('rev', 'rev_ex', 'cogs'):
            a[k] += Decimal(str(row[f'{k}_s'] or 0)) - Decimal(str(row[f'{k}_r'] or 0))

    ids = branch_scope.branch_ids(user)
    live = list(Branch.objects.live().order_by('display_order', 'softech_branch_id'))
    if ids is not None:
        live = [b for b in live if b.id in ids]
    live_ids = {b.id for b in live}
    cols = [b.softech_branch_id for b in live]
    by_id = {b.id: b.softech_branch_id for b in live}

    cells = defaultdict(_blank)            # (channel, column) → sums
    for (ch, bid), a in agg.items():
        col = by_id[bid] if bid in live_ids else OTHER
        _add(cells[(ch, col)], a)
    has_other = any(col == OTHER for _ch, col in cells)
    if has_other:
        cols.append(OTHER)

    # one label map per call: views._get_channel_label_map caches only a non-empty map, so calling
    # _channel_label() per row re-queried the classification tables for every channel (N+1)
    labels = _get_channel_label_map()

    def label(code):
        return 'غير مصنّف' if not code else labels.get(str(code), str(code))

    channels = sorted({ch for ch, _c in cells}, key=lambda ch: -sum(cells[(ch, c)]['rev'] for c in cols))
    rows = []
    col_tot = defaultdict(_blank)
    grand = _blank()
    for ch in channels:
        row_tot = _blank()
        row_cells = {}
        for c in cols:
            a = cells.get((ch, c))
            if a is None:
                continue
            row_cells[c] = _cell(a)
            _add(row_tot, a)
            _add(col_tot[c], a)
        _add(grand, row_tot)
        rows.append({'channel_code': ch, 'channel_label': label(ch), 'cells': row_cells,
                     'total': _cell(row_tot)})

    return {
        'basis': M.BASIS, 'basis_label': M.BASIS_LABEL_AR,
        'columns': [{'branch_code': c if c != OTHER else '', 'key': c,
                     'label': 'فروع أخرى (مغلقة)' if c == OTHER else ''} for c in cols],
        'rows': rows,
        'column_totals': {c: _cell(col_tot[c]) for c in cols},
        'total': _cell(grand),
        'delivery_fees': _delivery_fees(params, live),
    }


def _delivery_fees(params, live) -> dict:
    """{branch_code: fees} — delivered orders in the period, per live branch in view (delivery module figure)."""
    from apps.delivery.models import DeliveryOrder
    qs = DeliveryOrder.objects.filter(status=DeliveryOrder.STATUS_DELIVERED, branch__in=live)
    df, dt = _parse_date(params.get('date_from')), _parse_date(params.get('date_to'))
    if df:
        qs = qs.filter(delivered_at__date__gte=df)
    if dt:
        qs = qs.filter(delivered_at__date__lte=dt)
    out = {b.softech_branch_id: 0.0 for b in live}
    for r in qs.values('branch__softech_branch_id').order_by().annotate(f=Sum('delivery_fees', filter=Q(delivery_fees__gt=0))):
        out[r['branch__softech_branch_id']] = M.money(r['f'])
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated, ANALYTICS])
def margin_board(request):
    return Response(board(request.query_params, request.user))
