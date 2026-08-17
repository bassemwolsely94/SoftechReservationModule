"""
apps/purchasing/views.py

Read-only API + export for the Purchasing Optimization Engine.

Endpoints:
  GET  /api/purchasing/runs/          — list of engine runs (paginated)
  GET  /api/purchasing/runs/latest/   — most recent successful run
  GET  /api/purchasing/summary/       — pre-computed dashboard summary stats
  GET  /api/purchasing/metrics/       — per-item×branch metrics (filterable)
  GET  /api/purchasing/aggregated/    — per-item network totals (filterable)
  GET  /api/purchasing/export/        — Excel / CSV download
  POST /api/purchasing/trigger/       — admin-only: trigger a manual engine run
"""
import io
import csv
import logging
import threading
from decimal import Decimal

from django.http import HttpResponse, StreamingHttpResponse
from django.db.models import Sum, Count, Q, F, DecimalField, ExpressionWrapper
from rest_framework import generics, permissions, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import DemandCalculationRun, ItemDemandMetrics, ItemDemandAggregated, SalesTransactionLine
from .serializers import RunSerializer, MetricsSerializer, AggregatedSerializer


# ── Shared item-level filter helper ───────────────────────────────────────────

def _apply_item_filters(qs, params):
    """
    Apply advanced item-level filters from URL query params to any QuerySet
    that has an 'item' FK pointing to catalog.Item.

    Supported params:
      medicine_type=<str>     — item.medicine_type (10=Medicine,50=Cosmetics,20=Others…)
      supplier_code=<str>     — item.supplier_code exact match
      family_code=<str>       — item.family_code exact match
      category=<int>          — item.category_id FK
      requires_fridge=1       — item.requires_fridge=True
      is_active=1|0           — 1=active only, 0=archived only (default: all)
      is_stockable=1|0        — stockable filter
      is_fast_moving=1        — item.is_fast_moving=True (FMI items)
      insurance_type=<code>   — item.insurance_type (0=none,1=Talbia,2=TPA,3=Takaful,4=Other)
      item_level=1            — item.item_level=True
      has_points=1            — item.has_points=True
      branch_trans=<code>     — item.branch_trans (0=full,1=dispatch only,2=return only,3=stop)
      supplier_trans=<code>   — item.supplier_trans (purchase permissions)
      customer_trans=<code>   — item.customer_trans (sale permissions)
      nosale_classif=<code>   — item.nosale_classif (10=normal,20/30/31=restricted)
      store_classif=<code>    — item.store_classif (contract discount tier; FK custdiscpclassif)
    """
    def _list(key, cast=None):
        """Parse a comma-separated multi-value param into a list (or None)."""
        raw = params.get(key)
        if not raw:
            return None
        vals = [v.strip() for v in str(raw).split(',') if v.strip()]
        if cast:
            out = []
            for v in vals:
                try:
                    out.append(cast(v))
                except (ValueError, TypeError):
                    pass
            vals = out
        return vals or None

    def _num(key):
        try:
            return float(params.get(key))
        except (TypeError, ValueError):
            return None

    # ── Categorical multi-value filters (param → item field), matched with __in.
    #    Labels mirror the SOFTECH item card exactly (see AdvancedFiltersBar).
    CAT_FIELDS = {
        'medicine_type':  'item__medicine_type',    # تصنيف عام
        'shape_code':     'item__shape_code',        # الشكل الدوائى / الخط
        'effect_code':    'item__effect_code',       # الاستخدام
        'origin_code':    'item__origin_code',       # المنشأ
        'supplier_code':  'item__supplier_code',     # المورد
        'producer_code':  'item__producer_code',     # الشركة المنتجة
        'family_code':    'item__family_code',        # العائلة
        'store_classif':  'item__store_classif',     # تصنيف خصم التعاقدات
        'nosale_classif': 'item__nosale_classif',    # تصنيف منع الصرف
        'insurance_type': 'item__insurance_type',    # تصنيف التأمين الصحى
        'branch_trans':   'item__branch_trans',      # صلاحية الفروع
        'supplier_trans': 'item__supplier_trans',    # صلاحية الموردين
        'customer_trans': 'item__customer_trans',    # صلاحية العملاء
    }
    for key, field in CAT_FIELDS.items():
        vals = _list(key)
        if vals:
            qs = qs.filter(**{f'{field}__in': vals})

    # category (dosage-form FK) + item_level are integers
    cats = _list('category', cast=int)
    if cats:
        qs = qs.filter(item__category_id__in=cats)
    levels = _list('item_level', cast=int)
    if levels:
        qs = qs.filter(item__item_level__in=levels)

    # ── Boolean flags ──────────────────────────────────────────────────────────
    if params.get('requires_fridge') == '1':
        qs = qs.filter(item__requires_fridge=True)
    if params.get('is_fast_moving') == '1':
        qs = qs.filter(item__is_fast_moving=True)
    if params.get('has_points') == '1':
        qs = qs.filter(item__has_points=True)
    is_stockable = params.get('is_stockable')
    if is_stockable == '1':
        qs = qs.filter(item__is_stockable=True)
    elif is_stockable == '0':
        qs = qs.filter(item__is_stockable=False)
    is_active = params.get('is_active')
    if is_active == '1':
        qs = qs.filter(item__is_active=True)
    elif is_active == '0':
        qs = qs.filter(item__is_active=False)

    # ── Numeric ranges ─────────────────────────────────────────────────────────
    price_min, price_max = _num('price_min'), _num('price_max')      # سعر الجمهور
    if price_min is not None:
        qs = qs.filter(item__pack_price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(item__pack_price__lte=price_max)
    disc_min, disc_max = _num('discount_min'), _num('discount_max')  # خصم أساسى
    if disc_min is not None:
        qs = qs.filter(item__pharmacy_discp__gte=disc_min)
    if disc_max is not None:
        qs = qs.filter(item__pharmacy_discp__lte=disc_max)

    return qs

logger = logging.getLogger('elrezeiky.purchasing')


# ── Shared helper ─────────────────────────────────────────────────────────────

def _latest_run():
    """Return the most recent successful DemandCalculationRun, or None."""
    return (
        DemandCalculationRun.objects
        .filter(status='success')
        .order_by('-started_at')
        .first()
    )


# ── Runs ──────────────────────────────────────────────────────────────────────

class RunListView(generics.ListAPIView):
    """Recent engine runs."""
    queryset           = DemandCalculationRun.objects.all().order_by('-started_at')[:50]
    serializer_class   = RunSerializer
    permission_classes = [permissions.IsAuthenticated]


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def latest_run(request):
    """
    Return the most recent run (or 404 if none yet).

    Default: most recent *successful* run — this drives the dashboard table data.
    ?any=1 : most recent run of *any* status (success/partial/failed/running) —
             used by the header to surface a failed/incomplete last attempt.
    """
    if request.query_params.get('any') in ('1', 'true', 'True'):
        run = DemandCalculationRun.objects.order_by('-started_at').first()
    else:
        run = _latest_run()
    if not run:
        return Response({'detail': 'لم يتم تشغيل المحرك بعد'}, status=404)
    data = RunSerializer(run).data
    # Fallback for runs predating data_through_date: report the current latest
    # sale date so the staleness warning still works on the existing run.
    if not data.get('data_through_date'):
        from .models import SalesTransactionLine
        from django.db.models import Max
        mx = SalesTransactionLine.objects.aggregate(mx=Max('doc_date'))['mx']
        if mx:
            data['data_through_date'] = mx.isoformat()
    return Response(data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def active_run(request):
    """
    Return the currently running/pending DemandCalculationRun, if any.

    Used by the frontend progress bar to poll live status while the engine
    executes.  Returns 404 if no run is active so the frontend can treat
    it as a simple presence check.

    Fields updated mid-run (available before status='success'):
      rows_synced       — set after MODULE 2 (SOFTECH → PG copy)
      softech_available — set after MODULE 2
      rows_written      — set after MODULE 11 (persist metrics)
      branches_processed, items_processed — set at end
    """
    from django.utils import timezone as _tz
    import datetime as _dt

    # Auto-expire runs with NO ACTIVITY for > 20 minutes (updated_at, bumped on
    # every progress/phase save). Activity-based so a long-but-progressing run
    # (e.g. a big catch-up backfill) is never wrongly expired, while a truly
    # hung/crashed run still gets cleaned up.
    cutoff = _tz.now() - _dt.timedelta(minutes=20)
    stale_count = DemandCalculationRun.objects.filter(
        status__in=('running', 'pending'),
        updated_at__lt=cutoff,
    ).update(
        status='failed',
        finished_at=_tz.now(),
        error_message='Run timed out — auto-expired after 20 minutes with no completion',
    )
    if stale_count:
        logger.warning('[active_run] Auto-expired %d stale run(s)', stale_count)

    run = (
        DemandCalculationRun.objects
        .filter(status__in=('running', 'pending'))
        .order_by('-started_at')
        .first()
    )
    if not run:
        return Response({'detail': 'لا يوجد تشغيل نشط'}, status=status.HTTP_404_NOT_FOUND)
    return Response(RunSerializer(run).data)


# ── Summary (server-side — no page-size cap) ──────────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def purchasing_summary(request):
    """
    Pre-computed summary stats for the dashboard header cards.

    Computes everything server-side in two SQL queries so the frontend
    never needs to page through all rows to count them.

    Response keys:
      run_id, calc_date, softech_available
      total_items           — distinct items in the network (from aggregated)
      count_A / B / C / X   — items per ABC tier
      items_with_gap        — distinct items where ANY branch has gap > 0
      total_gap_value       — Σ(gap × pack_price) for all needing-purchase items
      total_monthly_value   — Σ(monthly_value) network-wide (EGP)
      unmatched_softech     — stktrans rows with no matching catalog item
    """
    run = _latest_run()
    if not run:
        return Response({'detail': 'لم يتم تشغيل المحرك بعد'}, status=404)

    # ── ABC counts + total monthly value (one query on aggregated) ─────────
    agg = ItemDemandAggregated.objects.filter(run=run).aggregate(
        total_items         = Count('id'),
        count_A             = Count('id', filter=Q(abc_class='A')),
        count_B             = Count('id', filter=Q(abc_class='B')),
        count_C             = Count('id', filter=Q(abc_class='C')),
        count_X             = Count('id', filter=Q(abc_class='X')),
        total_monthly_value = Sum('total_monthly_value'),
    )

    # ── Needs-purchase: distinct items with gap > 0 in any branch ──────────
    metrics_gap = ItemDemandMetrics.objects.filter(run=run, gap__gt=0).aggregate(
        items_with_gap  = Count('item_id', distinct=True),
        # gap value = Σ(gap × pack_price) — pack_price stored per-metrics row
        total_gap_value = Sum(
            ExpressionWrapper(F('gap') * F('pack_price'), output_field=DecimalField(max_digits=18, decimal_places=2))
        ),
    )

    # ── Unmatched SOFTECH rows (items not in our catalog) ─────────────────
    unmatched = SalesTransactionLine.objects.filter(item__isnull=True).count()

    return Response({
        'run_id':             run.pk,
        'calc_date':          run.calc_date,
        'softech_available':  run.softech_available,
        'rows_synced':        run.rows_synced,
        'duration_seconds':   run.duration_seconds,
        'total_items':        agg['total_items']  or 0,
        'count_A':            agg['count_A']      or 0,
        'count_B':            agg['count_B']      or 0,
        'count_C':            agg['count_C']      or 0,
        'count_X':            agg['count_X']      or 0,
        'total_monthly_value': float(agg['total_monthly_value'] or 0),
        'items_with_gap':     metrics_gap['items_with_gap']  or 0,
        'total_gap_value':    float(metrics_gap['total_gap_value'] or 0),
        'unmatched_softech':  unmatched,
    })


# ── Per-branch metrics ────────────────────────────────────────────────────────

class MetricsListView(generics.ListAPIView):
    """
    Per-item × per-branch metrics for the latest run.

    Filters:
      ?branch=<id>          — filter to one branch
      ?abc_class=A|B|C|X    — filter by ABC class
      ?needs_purchase=1     — only items with gap > 0
      ?search=<text>        — item name / softech_id
      ?ordering=priority|-priority|monthly_avg|gap|coverage_months|...
    """
    serializer_class   = MetricsSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['branch', 'abc_class']
    search_fields      = ['item__name', 'item__softech_id']
    ordering_fields    = [
        'priority', 'monthly_avg', 'gap', 'coverage_months',
        'monthly_value', 'current_stock', 'in_transit_qty', 'abc_class',
        'rate_30d', 'rate_90d', 'rate_365d', 'safety_stock',
    ]
    ordering = ['-priority']

    def get_queryset(self):
        run = _latest_run()
        if not run:
            return ItemDemandMetrics.objects.none()

        qs = (
            ItemDemandMetrics.objects
            .filter(run=run)
            .select_related('item', 'item__category', 'branch')
        )

        if self.request.query_params.get('needs_purchase') == '1':
            qs = qs.filter(gap__gt=0)

        qs = _apply_item_filters(qs, self.request.query_params)
        return qs


# ── Aggregated (network) ──────────────────────────────────────────────────────

class AggregatedListView(generics.ListAPIView):
    """
    Cross-branch aggregated metrics for the latest run.

    Filters:
      ?abc_class=A|B|C|X
      ?search=<text>
      ?needs_purchase=1   — only items where total_gap > 0
      ?ordering=total_monthly_value|-total_monthly_value|...
    """
    serializer_class   = AggregatedSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['abc_class']
    search_fields      = ['item__name', 'item__softech_id']
    ordering_fields    = [
        'total_monthly_value', 'total_monthly_avg', 'total_gap',
        'total_current_stock', 'cumulative_pct', 'abc_class',
    ]
    ordering = ['-total_monthly_value']

    def get_queryset(self):
        run = _latest_run()
        if not run:
            return ItemDemandAggregated.objects.none()

        qs = (
            ItemDemandAggregated.objects
            .filter(run=run)
            .select_related('item', 'item__category')
        )

        if self.request.query_params.get('needs_purchase') == '1':
            qs = qs.filter(total_gap__gt=0)

        qs = _apply_item_filters(qs, self.request.query_params)
        return qs


# ── Export — Excel / CSV ──────────────────────────────────────────────────────

# Column spec: (header_ar, field_getter, number_format or None)
_METRICS_COLUMNS = [
    ('اسم الصنف',          lambda r: r.item.name,                          None),
    ('رمز الصنف',          lambda r: r.item.softech_id,                    None),
    ('الفرع',              lambda r: r.branch.name_ar or r.branch.name,    None),
    ('ABC',                lambda r: r.abc_class,                           None),
    ('كمية 30 يوم',        lambda r: float(r.qty_30d or 0),                '#,##0.00'),
    ('كمية 90 يوم',        lambda r: float(r.qty_90d or 0),                '#,##0.00'),
    ('كمية 365 يوم',       lambda r: float(r.qty_365d or 0),               '#,##0.00'),
    ('معدل 30 يوم',        lambda r: float(r.rate_30d or 0),               '#,##0.00'),
    ('معدل 90 يوم',        lambda r: float(r.rate_90d or 0),               '#,##0.00'),
    ('معدل 365 يوم',       lambda r: float(r.rate_365d or 0),              '#,##0.00'),
    ('المتوسط المرجح',     lambda r: float(r.monthly_avg or 0),            '#,##0.00'),
    ('معدل حركات البيع',   lambda r: float(r.monthly_avg_trns or 0),       '#,##0.00'),
    ('الحد الأدنى',        lambda r: float(r.safety_stock or 0),           '#,##0.00'),
    ('المخزون الحالي',     lambda r: float(r.current_stock or 0),          '#,##0.00'),
    ('التغطية (أشهر)',     lambda r: float(r.coverage_months) if r.coverage_months is not None else '',  '#,##0.0'),
    ('نسبة من الشبكة',     lambda r: float(r.pct_stock_of_total or 0),     '0.00%'),
    ('الفجوة',             lambda r: float(r.gap or 0),                    '#,##0.00'),
    ('الأولوية',           lambda r: float(r.priority or 0),               '#,##0.000'),
    ('سعر العبوة (ج.م)',   lambda r: float(r.pack_price or 0),             '#,##0.00'),
    ('القيمة الشهرية (ج.م)',lambda r: float(r.monthly_value or 0),         '#,##0.00'),
    ('آخر بيع',            lambda r: r.last_sale_date,                     None),
    ('فواتير 30 يوم',      lambda r: r.invoices_30d or 0,                  '#,##0'),
    ('فواتير 90 يوم',      lambda r: r.invoices_90d or 0,                  '#,##0'),
    ('فواتير 365 يوم',     lambda r: r.invoices_365d or 0,                 '#,##0'),
    ('حركات 30 يوم',       lambda r: r.trns_30d or 0,                      '#,##0'),
    ('حركات 90 يوم',       lambda r: r.trns_90d or 0,                      '#,##0'),
    ('حركات 365 يوم',      lambda r: r.trns_365d or 0,                     '#,##0'),
]

_AGG_COLUMNS = [
    ('اسم الصنف',              lambda r: r.item.name,                        None),
    ('رمز الصنف',              lambda r: r.item.softech_id,                  None),
    ('ABC',                    lambda r: r.abc_class,                         None),
    ('التراكمي %',             lambda r: float(r.cumulative_pct or 0),       '0.00'),
    ('إجمالي كمية 30 يوم',     lambda r: float(r.total_qty_30d or 0),        '#,##0.00'),
    ('إجمالي كمية 90 يوم',     lambda r: float(r.total_qty_90d or 0),        '#,##0.00'),
    ('إجمالي كمية 365 يوم',    lambda r: float(r.total_qty_365d or 0),       '#,##0.00'),
    ('إجمالي المتوسط الشهري',  lambda r: float(r.total_monthly_avg or 0),    '#,##0.00'),
    ('إجمالي المخزون',          lambda r: float(r.total_current_stock or 0),  '#,##0.00'),
    ('إجمالي الفجوة',           lambda r: float(r.total_gap or 0),            '#,##0.00'),
    ('إجمالي القيمة (ج.م)',     lambda r: float(r.total_monthly_value or 0),  '#,##0.00'),
    ('سعر العبوة (ج.م)',        lambda r: float(r.pack_price or 0),           '#,##0.00'),
    ('فروع بمبيعات',            lambda r: r.branches_with_sales or 0,         '#,##0'),
    ('فروع بفجوات',             lambda r: r.branches_with_gap or 0,           '#,##0'),
]


def _build_metrics_qs(request, run):
    """Return a filtered, ordered QuerySet of ItemDemandMetrics for export."""
    qs = (
        ItemDemandMetrics.objects
        .filter(run=run)
        .select_related('item', 'item__category', 'branch')
        .order_by('-priority')
    )
    branch = request.GET.get('branch')
    abc    = request.GET.get('abc_class')
    needs  = request.GET.get('needs_purchase')
    search = request.GET.get('search')

    if branch:
        qs = qs.filter(branch_id=branch)
    if abc:
        qs = qs.filter(abc_class=abc)
    if needs == '1':
        qs = qs.filter(gap__gt=0)
    if search:
        qs = qs.filter(Q(item__name__icontains=search) | Q(item__softech_id__icontains=search))
    qs = _apply_item_filters(qs, request.GET)
    return qs


def _build_agg_qs(request, run):
    """Return a filtered, ordered QuerySet of ItemDemandAggregated for export."""
    qs = (
        ItemDemandAggregated.objects
        .filter(run=run)
        .select_related('item', 'item__category')
        .order_by('-total_monthly_value')
    )
    abc   = request.GET.get('abc_class')
    needs = request.GET.get('needs_purchase')
    search = request.GET.get('search')

    if abc:
        qs = qs.filter(abc_class=abc)
    if needs == '1':
        qs = qs.filter(total_gap__gt=0)
    if search:
        qs = qs.filter(Q(item__name__icontains=search) | Q(item__softech_id__icontains=search))
    qs = _apply_item_filters(qs, request.GET)
    return qs


def _export_xlsx(qs, columns, sheet_name, filename, run):
    """
    Build an openpyxl workbook in *write-only* (streaming) mode.

    Write-only serialises each row immediately into the ZIP stream instead of
    holding the entire DOM in memory.  For 10 k–40 k rows this is ~5× faster
    and avoids request timeouts.

    Supported features: freeze_panes, column_dimensions, sheet_view.rightToLeft.
    Trade-offs vs normal mode: merge_cells and row_dimensions are not available
    (cosmetic only — the data and column widths are fully preserved).
    """
    try:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return HttpResponse('openpyxl not installed', status=500)

    # ── Pre-build immutable style objects once (shared across all cells) ──────
    HEADER_FILL  = PatternFill('solid', fgColor='1E3A5F')
    HEADER_FONT  = Font(bold=True, color='FFFFFF', size=10, name='Calibri')
    HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
    THIN         = Side(style='thin', color='D0D0D0')
    BORDER       = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    GAP_FILL     = PatternFill('solid', fgColor='FFF0F0')   # light-red: needs purchase
    ALT_FILL     = PatternFill('solid', fgColor='FAFAFA')   # zebra stripe
    NUM_ALIGN    = Alignment(horizontal='center', vertical='center')
    TEXT_ALIGN   = Alignment(horizontal='right',  vertical='center')
    CTR_ALIGN    = Alignment(horizontal='center', vertical='center')
    ABC_FILLS    = {
        'A': PatternFill('solid', fgColor='E8F5E9'),
        'B': PatternFill('solid', fgColor='E3F2FD'),
        'C': PatternFill('solid', fgColor='FFF8E1'),
        'X': PatternFill('solid', fgColor='F5F5F5'),
    }
    ABC_FONTS    = {
        'A': Font(bold=True, color='2E7D32', name='Calibri'),
        'B': Font(bold=True, color='1565C0', name='Calibri'),
        'C': Font(bold=True, color='F57F17', name='Calibri'),
        'X': Font(bold=True, color='9E9E9E', name='Calibri'),
    }

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=sheet_name)
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = 'A5'   # rows 1-4: title / info / blank / header

    # ── Column widths (supported in write-only mode) ──────────────────────────
    COL_WIDTHS = {
        'اسم الصنف': 32, 'رمز الصنف': 12, 'الفرع': 16,
        'ABC': 6, 'التراكمي %': 9, 'آخر بيع': 12,
    }
    n_cols = len(columns)
    for col_idx, (hdr, _, num_fmt) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            COL_WIDTHS.get(hdr, 12 if num_fmt else 14)
        )

    def _blanks(n):
        return [WriteOnlyCell(ws) for _ in range(n)]

    # ── Rows 1-3: title / info / blank separator ──────────────────────────────
    title_cell = WriteOnlyCell(ws,
        value='صيدليات الرزيقي — لوحة المشتريات الأمثل')
    title_cell.font      = Font(bold=True, size=14, color='1E3A5F', name='Calibri')
    title_cell.alignment = Alignment(horizontal='right')
    ws.append([title_cell] + _blanks(n_cols - 1))

    info_cell = WriteOnlyCell(ws,
        value=(f'تاريخ الحساب: {run.calc_date}  |  تشغيل #{run.pk}  |  '
               f'{"SOFTECH متاح" if run.softech_available else "بيانات PG فقط"}  |  '
               f'المدة: {run.duration_seconds}s'))
    info_cell.font      = Font(size=9, color='666666', name='Calibri')
    info_cell.alignment = Alignment(horizontal='right')
    ws.append([info_cell] + _blanks(n_cols - 1))

    ws.append(_blanks(n_cols))   # blank separator row

    # ── Row 4: header ─────────────────────────────────────────────────────────
    hdr_row = []
    for col_hdr, _, _ in columns:
        c = WriteOnlyCell(ws, value=col_hdr)
        c.fill = HEADER_FILL; c.font = HEADER_FONT
        c.alignment = HEADER_ALIGN; c.border = BORDER
        hdr_row.append(c)
    ws.append(hdr_row)

    # ── Data rows (rows 5+) ───────────────────────────────────────────────────
    # Locate special columns by name (0-based index)
    abc_idx = next((i for i, col in enumerate(columns) if col[0] == 'ABC'), None)
    gap_idx = next((i for i, col in enumerate(columns) if 'فجوة' in col[0]), None)

    for row_num, obj in enumerate(qs.iterator(chunk_size=500), start=1):
        # Pre-compute all column values first so we don't re-read from the sheet
        vals = []
        for _, getter, _ in columns:
            try:
                vals.append(getter(obj))
            except Exception:
                vals.append('')

        abc_val = str(vals[abc_idx] or 'X') if abc_idx is not None else 'X'
        is_gap  = (gap_idx is not None and float(vals[gap_idx] or 0) > 0)

        data_row = []
        for col_i, (val, (_, _, num_fmt)) in enumerate(zip(vals, columns)):
            c = WriteOnlyCell(ws, value=val)
            c.border = BORDER

            if col_i == abc_idx:
                c.fill      = ABC_FILLS.get(abc_val, ABC_FILLS['X'])
                c.font      = ABC_FONTS.get(abc_val, ABC_FONTS['X'])
                c.alignment = CTR_ALIGN
            else:
                if is_gap:
                    c.fill  = GAP_FILL
                elif row_num % 2 == 0:
                    c.fill  = ALT_FILL
                c.alignment = NUM_ALIGN if num_fmt else TEXT_ALIGN

            if num_fmt:
                c.number_format = num_fmt

            data_row.append(c)
        ws.append(data_row)

    # ── Serialise & return ────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _export_csv(qs, columns, filename):
    """Stream a UTF-8-with-BOM CSV so Excel opens it correctly."""

    def generate():
        # BOM for Excel Arabic compatibility
        yield '﻿'
        writer_buf = io.StringIO()
        writer = csv.writer(writer_buf)
        writer.writerow([col[0] for col in columns])
        yield writer_buf.getvalue()

        for obj in qs.iterator(chunk_size=500):
            writer_buf = io.StringIO()
            writer = csv.writer(writer_buf)
            row = []
            for _, getter, _ in columns:
                try:
                    v = getter(obj)
                    row.append('' if v is None else v)
                except Exception:
                    row.append('')
            writer.writerow(row)
            yield writer_buf.getvalue()

    response = StreamingHttpResponse(generate(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ── Pivot export — one row per item, branch metrics as column groups ───────────
#
# Reproduces the layout of the reference Power Query Excel exactly:
#   "اولوية النواقص لكل فرع ب 3 معدلات — DataModel"
#
# Header columns (item info):
#   كود الصنف | اسم الصنف | كود المورد | كود العائلة | سعر العبوة
# Then for each active branch (sorted by softech_branch_id):
#   {code}.الرصيد-الحالى | {code}.معدل-البيع-الشهرى | {code}.كمية-الأمان
#   {code}.معامل-التغطية | {code}.الفرق-مطلوب/راكد | {code}.أولوية-الطلب
#   {code}.معدل-الحركات-الشهرى | {code}.%من-المخزون
#
# Items with no data in a given branch get empty cells (not zero).

# Per-branch column specs: (arabic label suffix, lambda metric→value, number_format)
_PIVOT_BRANCH_COLS = [
    ('الرصيد-الحالى',        lambda m: float(m.current_stock or 0),             '#,##0.00'),
    ('معدل-البيع-الشهرى',    lambda m: float(m.monthly_avg or 0),               '#,##0.00'),
    ('كمية-الأمان',          lambda m: float(m.safety_stock or 0),              '#,##0.00'),
    ('معامل-التغطية',        lambda m: (float(m.coverage_months)
                                         if m.coverage_months is not None else None), '#,##0.0'),
    ('الفرق-مطلوب/راكد',    lambda m: float(m.gap or 0),                       '#,##0.00'),
    ('أولوية-الطلب',         lambda m: float(m.priority or 0),                  '#,##0.000'),
    ('معدل-الحركات-الشهرى',  lambda m: float(m.monthly_avg_trns or 0),          '#,##0.00'),
    ('%من-المخزون',          lambda m: float(m.pct_stock_of_total or 0),         '0.00%'),
]


def _build_rank_dict(value_map, ascending=False):
    """
    Compute Excel RANK (non-dense) for a dict of {key: numeric_value}.

    Ties get the same rank; the next rank skips the count  (e.g. 1, 1, 3 …).
    Keys whose value is None are mapped to None in the result.
    Returns: {key: int_rank_or_None}

    Parameters
    ----------
    value_map : dict
        {key: numeric_value | None}
    ascending : bool
        False (default) → rank 1 = highest value (DESC, e.g. monthly rate).
        True            → rank 1 = lowest  value (ASC,  e.g. coverage months).
    """
    valid = [(k, float(v)) for k, v in value_map.items() if v is not None]
    # Sort so that "best" value comes first based on direction
    valid.sort(key=lambda x: x[1], reverse=not ascending)

    ranks = {}
    n = len(valid)
    i = 0
    while i < n:
        j = i + 1
        while j < n and valid[j][1] == valid[i][1]:
            j += 1
        for idx in range(i, j):
            ranks[valid[idx][0]] = i + 1   # non-dense: all tied items share rank i+1
        i = j

    # Items missing from value_map (None) keep rank = None
    for k in value_map:
        if k not in ranks:
            ranks[k] = None
    return ranks


def _export_xlsx_pivot(run, request, filename):
    """
    Build pivot Excel: one row per item, per-branch metrics as column groups.
    Uses write-only mode for streaming efficiency (works for 5k–15k items × 15 branches).
    """
    try:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return HttpResponse('openpyxl not installed', status=500)

    from apps.purchasing.models import ItemDemandMetrics
    from apps.branches.models import Branch
    from collections import defaultdict

    # ── 1. Determine active branches for this run ─────────────────────────────
    branch_ids = list(
        ItemDemandMetrics.objects
        .filter(run=run)
        .values_list('branch_id', flat=True)
        .distinct()
    )
    branches = list(
        Branch.objects
        .filter(id__in=branch_ids, is_active=True)
        .order_by('softech_branch_id', 'name')
    )
    if not branches:
        return HttpResponse('لا توجد بيانات للتصدير', status=404)

    # ── 2. Fetch all metrics → build pivot dict ───────────────────────────────
    # item_id → { branch_id → ItemDemandMetrics row }
    branch_id_set = {b.id for b in branches}
    pivot = defaultdict(dict)   # item_id → {branch_id: metric}
    item_order = []             # insertion-ordered item IDs
    item_obj   = {}             # item_id → item object

    # Order by ABC class then descending priority to match the reference Excel sort
    qs = (
        ItemDemandMetrics.objects
        .filter(run=run)
        .select_related('item', 'item__category')
        .order_by('item__name')
    )
    for m in qs.iterator(chunk_size=1000):
        iid = m.item_id
        if iid not in item_obj:
            item_obj[iid] = m.item
            item_order.append(iid)
        if m.branch_id in branch_id_set:
            pivot[iid][m.branch_id] = m

    logger.info('[PIVOT] %d items × %d branches', len(item_order), len(branches))

    # ── 3. Build workbook ─────────────────────────────────────────────────────
    HEADER_FILL  = PatternFill('solid', fgColor='1E3A5F')
    BRANCH_FILLS = [
        PatternFill('solid', fgColor='E8F0FE'),  # blue-tinted
        PatternFill('solid', fgColor='E6F4EA'),  # green-tinted
    ]
    HEADER_FONT  = Font(bold=True, color='FFFFFF', size=9, name='Calibri')
    BRANCH_FONTS = [
        Font(bold=True, color='1A3C7A', size=9, name='Calibri'),
        Font(bold=True, color='1A5C2A', size=9, name='Calibri'),
    ]
    DATA_FONT    = Font(size=9, name='Calibri')
    HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
    NUM_ALIGN    = Alignment(horizontal='center', vertical='center')
    TEXT_ALIGN   = Alignment(horizontal='right',  vertical='center')
    THIN         = Side(style='thin', color='D0D0D0')
    BORDER       = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    ABC_FILLS    = {
        'A': PatternFill('solid', fgColor='E8F5E9'),
        'B': PatternFill('solid', fgColor='E3F2FD'),
        'C': PatternFill('solid', fgColor='FFF8E1'),
        'X': PatternFill('solid', fgColor='F5F5F5'),
    }

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title='المعدلات-الشهرية')
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = 'A3'

    # Column widths
    ITEM_COL_WIDTHS = [10, 32, 10, 8, 10]  # code, name, supplier, family, price
    for ci, w in enumerate(ITEM_COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    branch_col_start = len(ITEM_COL_WIDTHS) + 1
    BRANCH_COL_WIDTHS = [10, 11, 9, 9, 11, 10, 11, 9]
    for bi, branch in enumerate(branches):
        for ci, w in enumerate(BRANCH_COL_WIDTHS):
            col = branch_col_start + bi * len(_PIVOT_BRANCH_COLS) + ci
            ws.column_dimensions[get_column_letter(col)].width = w

    def _hdr(ws, val, fill, font, align=HEADER_ALIGN):
        c = WriteOnlyCell(ws, value=val)
        c.fill = fill; c.font = font; c.alignment = align; c.border = BORDER
        return c

    # ── Row 1: branch group headers (merged visually by repetition) ──────────
    row1 = [
        _hdr(ws, 'كود الصنف',  HEADER_FILL, HEADER_FONT),
        _hdr(ws, 'اسم الصنف',  HEADER_FILL, HEADER_FONT),
        _hdr(ws, 'كود المورد', HEADER_FILL, HEADER_FONT),
        _hdr(ws, 'كود العائلة',HEADER_FILL, HEADER_FONT),
        _hdr(ws, 'سعر العبوة', HEADER_FILL, HEADER_FONT),
    ]
    for bi, branch in enumerate(branches):
        bfill = BRANCH_FILLS[bi % 2]
        bfont = BRANCH_FONTS[bi % 2]
        code  = branch.softech_branch_id or branch.name
        # Branch code repeated across all its columns (acts as group header)
        for col_label, _, _ in _PIVOT_BRANCH_COLS:
            row1.append(_hdr(ws, code, bfill, bfont))
    ws.append(row1)

    # ── Row 2: column sub-headers ─────────────────────────────────────────────
    row2 = [
        WriteOnlyCell(ws),  # code
        WriteOnlyCell(ws),  # name
        WriteOnlyCell(ws),  # supplier
        WriteOnlyCell(ws),  # family
        WriteOnlyCell(ws),  # price
    ]
    for bi, branch in enumerate(branches):
        bfill = BRANCH_FILLS[bi % 2]
        bfont = BRANCH_FONTS[bi % 2]
        for col_label, _, _ in _PIVOT_BRANCH_COLS:
            row2.append(_hdr(ws, col_label, bfill, bfont))
    ws.append(row2)

    # ── Precompute branch fills (reused across all rows) ──────────────────────
    BRANCH_LIGHT_FILLS = [
        PatternFill('solid', fgColor='F0F4FF'),  # even branches — blue tint
        PatternFill('solid', fgColor='F0FFF4'),  # odd branches  — green tint
    ]

    # ── Data rows ─────────────────────────────────────────────────────────────
    for iid in item_order:
        item = item_obj[iid]
        # ABC class from first branch with data
        abc = 'X'
        for b in branches:
            m0 = pivot[iid].get(b.id)
            if m0:
                abc = m0.abc_class
                break
        afill = ABC_FILLS.get(abc, ABC_FILLS['X'])

        # Item info cells
        def _icell(val, num_fmt=None, align=None):
            c = WriteOnlyCell(ws, value=val)
            c.font = DATA_FONT; c.fill = afill; c.border = BORDER
            c.alignment = align or (NUM_ALIGN if num_fmt else TEXT_ALIGN)
            if num_fmt: c.number_format = num_fmt
            return c

        row = [
            _icell(item.softech_id,               align=NUM_ALIGN),
            _icell(item.name),
            _icell(item.supplier_code or ''),
            _icell(item.family_code   or ''),
            _icell(float(item.pack_price or 0),   '#,##0.00'),
        ]

        # Branch metric cells
        for bi, branch in enumerate(branches):
            m        = pivot[iid].get(branch.id)
            bfill    = BRANCH_LIGHT_FILLS[bi % 2]
            for col_label, getter, num_fmt in _PIVOT_BRANCH_COLS:
                c = WriteOnlyCell(ws, value=None)
                c.font = DATA_FONT; c.fill = bfill; c.border = BORDER
                c.alignment = NUM_ALIGN if num_fmt else TEXT_ALIGN
                if num_fmt:
                    c.number_format = num_fmt
                if m is not None:
                    try:
                        c.value = getter(m)
                    except Exception:
                        c.value = None
                row.append(c)

        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    logger.info('[PIVOT] exported %d items × %d branches', len(item_order), len(branches))
    return resp


def _export_xlsx_pivot_v2(run, request, filename):
    """
    129-column pivot export matching the reference Excel:
    "اولوية النواقص لكل فرع ب 3 معدلات سنوى — DataModel"

    Item info now carries 4 classification LABELS (نوع الدواء / الشكل الصيدلى /
    الشكل والوحدة / تصنيف الخصم) and every branch block carries a بضاعة-بالطريق
    (in-transit) column right after الرصيد-الحالى.

    Column layout (129 total):
      [  0-12]  Item info          (13 cols — 4 classification labels)
      [ 13-18]  Branch 100         (6 cols — +in-transit, no coverage/priority)
      [ 19-26]  Branch 130         (8 cols — +in-transit)
      [ 27-34]  Branch 140         (8 cols)
      [ 35-42]  Branch 150         (8 cols)
      [ 43-50]  Branch 160         (8 cols)
      [ 51-58]  Branch 170         (8 cols)
      [ 59-64]  Network totals     (6 cols — +in-transit)
      [ 56-61]  % of total stock   (6 cols — one per branch)
      [ 62-67]  Rank by rate DESC  (6 cols — cross-branch rank per item)
      [ 68-72]  Rank coverage ASC  (5 cols — branches 130-170)
      [ 73-77]  Rank deficit DESC  (5 cols — branches 130-170)
      [ 78-85]  Summary calcs      (8 cols)
      [ 86-119] Empty placeholders (34 cols)

    Ranks are cross-branch per item (e.g. Rank 1 = branch with highest rate
    for this item), NOT cross-item within a branch.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return HttpResponse('openpyxl not installed', status=500)

    from apps.branches.models import Branch
    from collections import defaultdict

    # ── 1. Load fixed branches in exact reference order ───────────────────────
    BRANCH_ORDER = ['100', '130', '140', '150', '160', '170']

    branch_map = {
        b.softech_branch_id: b
        for b in Branch.objects.filter(
            softech_branch_id__in=BRANCH_ORDER,
            is_active=True,
        )
    }
    branches        = [branch_map[sid] for sid in BRANCH_ORDER if sid in branch_map]
    branch_100      = branch_map.get('100')
    branches_no100  = [b for b in branches if b.softech_branch_id != '100']  # 130-170

    if not branches:
        return HttpResponse('لا توجد فروع للتصدير', status=404)

    # ── 2. Load all metrics for these branches ────────────────────────────────
    branch_id_set = {b.id for b in branches}

    qs = (
        ItemDemandMetrics.objects
        .filter(run=run, branch_id__in=branch_id_set)
        .select_related('item', 'item__category')
        .order_by('item__name')
    )

    # pivot: {item_id: {branch_id: metric_row}}
    pivot      = defaultdict(dict)
    item_order = []   # insertion-ordered item IDs (sorted by item name)
    item_obj   = {}   # {item_id: Item}

    for m in qs.iterator(chunk_size=1000):
        iid = m.item_id
        if iid not in item_obj:
            item_obj[iid] = m.item
            item_order.append(iid)
        pivot[iid][m.branch_id] = m

    logger.info('[PIVOT-V2] %d items × %d branches → 132 cols', len(item_order), len(branches))

    # ── 3. Styles ──────────────────────────────────────────────────────────────
    THIN   = Side(style='thin', color='D0D0D0')
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    _f = lambda hex_: PatternFill('solid', fgColor=hex_)
    _fnt = lambda bold, color, size=9: Font(bold=bold, color=color, size=size, name='Calibri')

    HDR_FILL   = _f('1E3A5F');  HDR_FONT  = _fnt(True,  'FFFFFF')
    B100_HFILL = _f('2E4B8F');  B100_DFILL = _f('EEF3FF')
    BGRP_HFILLS = [_f('1F6B3A'), _f('7B3F00'), _f('5D0D7A'), _f('8B1A00'), _f('005B6B')]
    BGRP_DFILLS = [_f('EDF9F1'), _f('FFF8F0'), _f('F7EEFF'), _f('FFF0EF'), _f('E8FAFB')]
    TOT_HFILL  = _f('E65100');  TOT_DFILL  = _f('FFF8E1')
    PCT_HFILL  = _f('6A1B9A');  PCT_DFILL  = _f('F3E5F5')
    RNK_HFILL  = _f('006064');  RNK_DFILL  = _f('E0F7FA')
    SUM_HFILL  = _f('B71C1C');  SUM_DFILL  = _f('FCE4EC')

    ABC_FILLS = {
        'A': _f('E8F5E9'), 'B': _f('E3F2FD'),
        'C': _f('FFF8E1'), 'X': _f('F5F5F5'),
    }

    DATA_FONT   = Font(size=9, name='Calibri')
    HDR_ALIGN   = Alignment(horizontal='center', vertical='center', wrap_text=True)
    NUM_ALIGN   = Alignment(horizontal='center', vertical='center')
    TEXT_ALIGN  = Alignment(horizontal='right',  vertical='center')
    CTR_ALIGN   = NUM_ALIGN

    # ── 4. Workbook setup ─────────────────────────────────────────────────────
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title='المعدلات-الشهرية')
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = 'Q3'   # freeze rows 1-2 + first 16 item-info cols

    # Column widths: 16 item + 6 b100 + 40 b130-170 + 6 tot + 6 pct + 6 rrate + 5 rcov + 5 rdef + 8 sum + 34 empty
    _cw = (
        # 16 item info: archive, medtype, dosage, shape, discount, supply-order,
        #   supp_code, supp_name, prod_code, prod_name, fam_code, fam_name,
        #   itemcode, itemname, price, cost
        [7, 14, 12, 16, 12, 9, 8, 16, 10, 18, 8, 14, 9, 34, 9, 9]
        + [10, 10, 10, 9, 10, 9]                     # 6 branch-100 cols (+in-transit)
        + [10, 10, 10, 9, 9, 10, 10, 9] * 5          # 40 (8 cols × 5 branches)
        + [11, 11, 11, 10, 11, 10]                   # 6 totals (+in-transit)
        + [9]  * 6                                   # 6 % stock
        + [7]  * 6                                   # 6 rank-rate
        + [8]  * 5                                   # 5 rank-coverage
        + [8]  * 5                                   # 5 rank-deficit
        + [13, 13, 13, 13, 16, 16, 13, 13]           # 8 summary
        + [5]  * 34                                  # 34 empty
    )
    assert len(_cw) == 132, f'Expected 132 cols, got {len(_cw)}'
    for ci, w in enumerate(_cw, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    # ── Helper closures ────────────────────────────────────────────────────────
    def _hdr(val, fill, font=HDR_FONT):
        c = WriteOnlyCell(ws, value=val)
        c.fill = fill; c.font = font; c.alignment = HDR_ALIGN; c.border = BORDER
        return c

    def _cell(val, fill, num_fmt=None, align=None):
        c = WriteOnlyCell(ws, value=val)
        c.font  = DATA_FONT
        c.fill  = fill
        c.border = BORDER
        c.alignment = align or (NUM_ALIGN if num_fmt else TEXT_ALIGN)
        if num_fmt:
            c.number_format = num_fmt
        return c

    def _blank():
        return WriteOnlyCell(ws)

    SFNT = Font(bold=True, color='FFFFFF', size=8, name='Calibri')   # section sub-header font

    # ── 5. Row 1 — Group headers ──────────────────────────────────────────────
    row1 = (
        [_hdr('بيانات الصنف', HDR_FILL)] * 16
        + [_hdr('100',          B100_HFILL)] * 6
    )
    for bi, b in enumerate(branches_no100):
        row1 += [_hdr(b.softech_branch_id, BGRP_HFILLS[bi % len(BGRP_HFILLS)])] * 8
    row1 += (
        [_hdr('الإجمالى',      TOT_HFILL)] * 6
        + [_hdr('% المخزون',  PCT_HFILL)] * 6
        + [_hdr('ترتيب المعدل',RNK_HFILL)] * 6
        + [_hdr('ترتيب التغطية', RNK_HFILL)] * 5
        + [_hdr('ترتيب الفجوة', RNK_HFILL)] * 5
        + [_hdr('مؤشرات محسوبة', SUM_HFILL)] * 8
        + [_blank()] * 34
    )
    ws.append(row1)

    # ── 6. Row 2 — Column sub-headers ────────────────────────────────────────
    ITEM_HDRS = [
        'Items_.الارشيف',
        'Items_.تصنيف-عام',          # نوع الدواء (main category) — LABEL
        'Items_.الشكل-الصيدلى',      # dosage form (category) — LABEL
        'Items_.الشكل-والوحدة',      # shape — LABEL
        'Items_.تصنيف-الخصم',        # store_classif (contract discount) — LABEL
        'Items_.امر-التوريد',        # itemnomoreuse flag (1=discontinued)
        'Items_.كود-المورد',          # supplier_code
        'Items_.المورد',              # supplier_name
        'Items_.كود-الشركة-المنتجة',   # producer_code
        'ItemsProducers_.الشركة-المنتجة',  # producer_name (manufacturer) — LABEL
        'Items_.كود-العائلة',         # family_code (numeric, kept)
        'Items_.العائلة',             # family_name — LABEL
        'itemcode',
        'Items_.itemname',
        'Items_.سعر-جمهور',
        'Items_.سعر-تكلفة',
    ]
    B100_HDRS = [
        '100.الرصيد-الحالى',
        '100.بضاعة-بالطريق',
        '100.معدل-البيع-الشهرى',
        '100.كمية-الأمان',
        '100.الفرق-مطلوب/راكد',
        '100.معدل-عدد-حركات-البيع-الشهرى',
    ]
    B7_TMPL = [
        '{sid}.الرصيد-الحالى',
        '{sid}.بضاعة-بالطريق',
        '{sid}.معدل-البيع-الشهرى',
        '{sid}.كمية-الأمان',
        '{sid}.معامل-التغطية-بالشهور',
        '{sid}.الفرق-مطلوب/راكد',
        '{sid}.معامل-أولوية-الطلب',
        '{sid}.معدل-عدد-حركات-البيع-الشهرى',
    ]
    TOT_HDRS = [
        'Total.الرصيد-الحالى',
        'Total.بضاعة-بالطريق',
        'Total.معدل-البيع-الشهرى',
        'Total.معامل-التغطية-بالشهور',
        'Total.الفرق-مطلوب/راكد',
        'Total.معامل-أولوية-الطلب',
    ]
    SUM_HDRS = [
        'Stock Value',
        'Gap Value',
        'الكمية الناقصة من بعض الفروع',
        'الكمية الزيادة فى بعض الفروع',
        'الفرع الأكثر إحتياجا',
        'الفرع الأكثر ركود',
        'الكمية المطلوب تحويلها للرئيسى',
        'مبلغ المطلوب تحويله',
    ]

    row2 = [_hdr(h, HDR_FILL,   SFNT) for h in ITEM_HDRS]
    row2 += [_hdr(h, B100_HFILL, SFNT) for h in B100_HDRS]
    for bi, b in enumerate(branches_no100):
        hfill = BGRP_HFILLS[bi % len(BGRP_HFILLS)]
        sid   = b.softech_branch_id
        row2 += [_hdr(tmpl.format(sid=sid), hfill, SFNT) for tmpl in B7_TMPL]
    row2 += [_hdr(h, TOT_HFILL, SFNT) for h in TOT_HDRS]
    for b in branches:
        row2.append(_hdr(f'{b.softech_branch_id}.%لإجمالى-مخزون', PCT_HFILL, SFNT))
    for b in branches:
        row2.append(_hdr(f'{b.softech_branch_id}.Rank',         RNK_HFILL, SFNT))
    for b in branches_no100:
        row2.append(_hdr(f'{b.softech_branch_id}.RankCoverage', RNK_HFILL, SFNT))
    for b in branches_no100:
        row2.append(_hdr(f'{b.softech_branch_id}.RankDeficit',  RNK_HFILL, SFNT))
    row2 += [_hdr(h, SUM_HFILL, SFNT) for h in SUM_HDRS]
    row2 += [_blank()] * 34
    ws.append(row2)

    # ── 7. Data rows ──────────────────────────────────────────────────────────
    def _fv(m, attr):
        """Safe float value from a metric attribute."""
        v = getattr(m, attr, None)
        return float(v) if v is not None else None

    for iid in item_order:
        item        = item_obj[iid]
        branch_data = pivot[iid]          # {branch_id: metric}
        pack_price  = float(item.pack_price or 0)

        # ABC class (first branch with data)
        abc = 'X'
        for b in branches:
            m0 = branch_data.get(b.id)
            if m0:
                abc = m0.abc_class or 'X'
                break
        item_fill = ABC_FILLS.get(abc, ABC_FILLS['X'])

        # ── Network totals ────────────────────────────────────────────────────
        stocks     = [_fv(m, 'current_stock') or 0 for m in branch_data.values()]
        intransits = [_fv(m, 'in_transit_qty') or 0 for m in branch_data.values()]
        rates      = [_fv(m, 'monthly_avg')   or 0 for m in branch_data.values()]
        gaps       = [_fv(m, 'gap')           or 0 for m in branch_data.values()]
        priorities = [_fv(m, 'priority')      or 0 for m in branch_data.values()]

        total_stock       = sum(stocks)
        total_in_transit  = sum(intransits)
        total_rate     = sum(rates)
        total_gap      = sum(gaps)
        max_priority   = max(priorities, default=0)
        total_coverage = (total_stock / total_rate) if total_rate > 0 else None

        # ── Summary calcs ─────────────────────────────────────────────────────
        deficit_qty  = sum(max(0,  g) for g in gaps)   # positive gaps only
        surplus_qty  = sum(max(0, -g) for g in gaps)   # negative gaps only (abs)

        most_needed_sid = ''
        most_needed_gap = 0.0
        most_surplus_sid = ''
        most_surplus_val  = 0.0
        for b in branches:
            m = branch_data.get(b.id)
            if m is None:
                continue
            g = _fv(m, 'gap') or 0
            if g > most_needed_gap:
                most_needed_gap = g
                most_needed_sid  = b.softech_branch_id
            if g < -most_surplus_val:
                most_surplus_val = -g
                most_surplus_sid = b.softech_branch_id

        # Qty / value to transfer TO branch 100 (main branch deficit)
        b100_gap = 0.0
        if branch_100 and branch_100.id in branch_data:
            b100_gap = max(0.0, _fv(branch_data[branch_100.id], 'gap') or 0)
        transfer_qty   = b100_gap
        transfer_value = b100_gap * pack_price

        # ── Cross-branch ranks (per item, max 6 values) ───────────────────────
        rate_vals = {b.id: (_fv(branch_data[b.id], 'monthly_avg') if b.id in branch_data else None)
                     for b in branches}
        rate_ranks = _build_rank_dict(rate_vals, ascending=False)  # DESC: high rate = rank 1

        cov_vals = {}
        def_vals = {}
        for b in branches_no100:
            if b.id in branch_data:
                m = branch_data[b.id]
                cov_vals[b.id] = _fv(m, 'coverage_months')
                def_vals[b.id] = _fv(m, 'gap')
        cov_ranks = _build_rank_dict(cov_vals, ascending=True)    # ASC: low coverage = rank 1
        def_ranks = _build_rank_dict(def_vals, ascending=False)   # DESC: high gap = rank 1

        # ── Build row cells ───────────────────────────────────────────────────
        row = []

        # [0-15] Item info — classifications shown as LABELS (not codes),
        # grouped supplier → producer → family.
        _cat = item.category
        # الارشيف = itemarchive. Archived items are excluded at sync, so this is
        # always 0. (Discontinued items are is_active=False but NOT archived —
        # they are flagged via the separate امر-التوريد column below.)
        row.append(_cell(0,                                                   item_fill, '#,##0'))
        # تصنيف عام = نوع الدواء (main category): Medicine / Cosmetics / Others…
        row.append(_cell(item.medicine_type_name_ar or item.medicine_type_name or '', item_fill))
        # الشكل الصيدلى = dosage form (catalog Category label)
        row.append(_cell((_cat.name_ar or _cat.name) if _cat else '',         item_fill))
        # الشكل/الوحدة = shape label
        row.append(_cell(item.shape_name_ar or item.shape_name or '',         item_fill))
        # تصنيف الخصم = contract discount classification label
        row.append(_cell(item.store_classif_name or '',                       item_fill))
        # امر التوريد = discontinued flag (itemnomoreuse): 1 = موقوف
        row.append(_cell(1 if item.no_more_use else 0,                        item_fill, '#,##0'))
        # المورد — supplier (code + name)
        row.append(_cell(item.supplier_code or '',                             item_fill))
        row.append(_cell(item.supplier_name or '',                             item_fill))
        # الشركة المنتجة — producer / manufacturer (code + name)
        row.append(_cell(item.producer_code or '',                             item_fill))
        row.append(_cell(item.producer_name or '',                             item_fill))
        # العائلة — family (numeric code kept + name LABEL)
        row.append(_cell(item.family_code   or '',                             item_fill))
        row.append(_cell(item.family_name_ar or item.family_name or '',        item_fill))
        row.append(_cell(item.softech_id,                                      item_fill))
        row.append(_cell(item.name,                                            item_fill))
        row.append(_cell(pack_price,                                           item_fill, '#,##0.00'))
        row.append(_cell(float(item.cost_price or 0),                          item_fill, '#,##0.00'))

        # [11-16] Branch 100 (6 cols — no coverage/priority)
        if branch_100 and branch_100.id in branch_data:
            m100 = branch_data[branch_100.id]
            row.append(_cell(_fv(m100, 'current_stock')    or 0, B100_DFILL, '#,##0.00'))
            row.append(_cell(_fv(m100, 'in_transit_qty')   or 0, B100_DFILL, '#,##0.00'))
            row.append(_cell(_fv(m100, 'monthly_avg')      or 0, B100_DFILL, '#,##0.00'))
            row.append(_cell(_fv(m100, 'safety_stock')     or 0, B100_DFILL, '#,##0.00'))
            row.append(_cell(_fv(m100, 'gap')              or 0, B100_DFILL, '#,##0.00'))
            row.append(_cell(_fv(m100, 'monthly_avg_trns') or 0, B100_DFILL, '#,##0.00'))
        else:
            row += [_cell(None, B100_DFILL)] * 6

        # [17-...] Branches 130-170 (8 cols each)
        for bi, b in enumerate(branches_no100):
            dfill = BGRP_DFILLS[bi % len(BGRP_DFILLS)]
            if b.id in branch_data:
                m = branch_data[b.id]
                cov = _fv(m, 'coverage_months')
                row.append(_cell(_fv(m, 'current_stock')    or 0, dfill, '#,##0.00'))
                row.append(_cell(_fv(m, 'in_transit_qty')   or 0, dfill, '#,##0.00'))
                row.append(_cell(_fv(m, 'monthly_avg')      or 0, dfill, '#,##0.00'))
                row.append(_cell(_fv(m, 'safety_stock')     or 0, dfill, '#,##0.00'))
                row.append(_cell(cov,                             dfill, '#,##0.0'))
                row.append(_cell(_fv(m, 'gap')              or 0, dfill, '#,##0.00'))
                row.append(_cell(_fv(m, 'priority')         or 0, dfill, '#,##0.000'))
                row.append(_cell(_fv(m, 'monthly_avg_trns') or 0, dfill, '#,##0.00'))
            else:
                row += [_cell(None, dfill)] * 8

        # Network totals (6 cols — stock, in-transit, rate, coverage, gap, priority)
        row.append(_cell(total_stock,      TOT_DFILL, '#,##0.00'))
        row.append(_cell(total_in_transit, TOT_DFILL, '#,##0.00'))
        row.append(_cell(total_rate,       TOT_DFILL, '#,##0.00'))
        row.append(_cell(total_coverage,   TOT_DFILL, '#,##0.0'))
        row.append(_cell(total_gap,        TOT_DFILL, '#,##0.00'))
        row.append(_cell(max_priority,     TOT_DFILL, '#,##0.000'))

        # [56-61] % of total stock (6 branches)
        for b in branches:
            if b.id in branch_data and total_stock > 0:
                pct = (_fv(branch_data[b.id], 'current_stock') or 0) / total_stock
            else:
                pct = None
            row.append(_cell(pct, PCT_DFILL, '0.00%'))

        # [62-67] Rank by rate DESC (6 branches)
        for b in branches:
            row.append(_cell(rate_ranks.get(b.id), RNK_DFILL, '#,##0'))

        # [68-72] Rank by coverage ASC (branches 130-170)
        for b in branches_no100:
            row.append(_cell(cov_ranks.get(b.id), RNK_DFILL, '#,##0'))

        # [73-77] Rank by deficit DESC (branches 130-170)
        for b in branches_no100:
            row.append(_cell(def_ranks.get(b.id), RNK_DFILL, '#,##0'))

        # [78-85] Summary (8 cols)
        row.append(_cell(total_stock * pack_price, SUM_DFILL, '#,##0.00'))
        row.append(_cell(total_gap   * pack_price, SUM_DFILL, '#,##0.00'))
        row.append(_cell(deficit_qty,              SUM_DFILL, '#,##0.00'))
        row.append(_cell(surplus_qty,              SUM_DFILL, '#,##0.00'))
        row.append(_cell(most_needed_sid,          SUM_DFILL))
        row.append(_cell(most_surplus_sid,         SUM_DFILL))
        row.append(_cell(transfer_qty,             SUM_DFILL, '#,##0.00'))
        row.append(_cell(transfer_value,           SUM_DFILL, '#,##0.00'))

        # [86-119] Empty (34 cols)
        row += [_blank()] * 34

        ws.append(row)

    # ── Serialise & return ────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    logger.info('[PIVOT-V2] exported %d items, 132 cols', len(item_order))
    return resp


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_purchasing(request):
    """
    Download purchasing data as Excel (.xlsx) or CSV.

    Query params:
      format=xlsx|csv                      (default: xlsx)
      view=metrics|aggregated|pivot        (default: metrics)
        metrics    — flat rows: one row per item × branch
        aggregated — flat rows: one row per item (network totals)
        pivot      — one row per item, branch metrics as columns (matches reference Excel)
      branch=<id>     filter (metrics / aggregated only)
      abc_class=A|B|C|X
      needs_purchase=1
      search=<text>
    """
    import traceback as _tb
    try:
        run = _latest_run()
        logger.info('[EXPORT] run=%s', run)
        if not run:
            return Response({'detail': 'لا توجد بيانات — شغّل المحرك أولاً'}, status=503)

        fmt  = request.GET.get('format', 'xlsx').lower()
        view = request.GET.get('view', 'metrics').lower()
        date = str(run.calc_date)
        logger.info('[EXPORT] fmt=%s view=%s date=%s', fmt, view, date)

        # ── Pivot view — one row per item, branches as column groups (120-col) ──
        if view == 'pivot':
            filename = f'purchasing-pivot-{date}.xlsx'
            return _export_xlsx_pivot_v2(run, request, filename)

        # ── Flat views ────────────────────────────────────────────────────────
        if view == 'aggregated':
            qs       = _build_agg_qs(request, run)
            columns  = _AGG_COLUMNS
            sheet    = 'الشبكة'
            filename = f'purchasing_network_{date}'
        else:
            qs       = _build_metrics_qs(request, run)
            columns  = _METRICS_COLUMNS
            sheet    = 'بالفرع'
            filename = f'purchasing_branch_{date}'

        row_count = qs.count()
        logger.info('[EXPORT] row_count=%s', row_count)

        # Safety cap: >100 k rows would cause an unacceptable wait; tell the user to filter.
        if row_count > 100_000:
            return Response(
                {'detail': f'البيانات كبيرة جداً ({row_count:,} صف) — استخدم فلاتر لتضييق النطاق'},
                status=400,
            )

        if fmt == 'csv':
            return _export_csv(qs, columns, f'{filename}.csv')
        return _export_xlsx(qs, columns, sheet, f'{filename}.xlsx', run)

    except Exception as exc:
        logger.error('[EXPORT] EXCEPTION: %s\n%s', exc, _tb.format_exc())
        return Response({'error': str(exc), 'type': type(exc).__name__}, status=500)


# ── Manual trigger (background thread) ───────────────────────────────────────

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def trigger_run(request):
    """
    Admin/pharmacist endpoint to trigger an immediate engine run.

    Runs in a background daemon thread so the HTTP response returns
    immediately (within ~1 second) without waiting for the 15–135s run.
    The client should poll GET /api/purchasing/runs/latest/ to track progress.

    Returns the newly-created DemandCalculationRun (status='running').
    """
    profile = getattr(request.user, 'staff_profile', None)
    if not profile or profile.role not in ('admin', 'pharmacist'):
        return Response({'detail': 'غير مصرح'}, status=403)

    # Guard: don't start a second run if one is already running
    already_running = DemandCalculationRun.objects.filter(status='running').exists()
    if already_running:
        running = DemandCalculationRun.objects.filter(status='running').last()
        return Response(
            {'detail': 'يوجد تشغيل جارٍ بالفعل', 'run': RunSerializer(running).data},
            status=409,
        )

    full_backfill    = request.data.get('full', False)
    param_overrides  = request.data.get('params', {})   # optional per-run overrides

    def _run_engine():
        try:
            from .engine import DemandEngine
            DemandEngine(param_overrides=param_overrides).run(full_backfill=bool(full_backfill))
        except Exception as exc:
            logger.exception('Background engine run failed: %s', exc)
        finally:
            # Background threads are NOT part of Django's request/response cycle,
            # so Django never auto-closes their DB connections.  Explicitly release
            # all connections this thread holds so PostgreSQL slots are freed.
            from django.db import connections as _dj_connections
            _dj_connections.close_all()

    thread = threading.Thread(target=_run_engine, daemon=True, name='demand-engine')
    thread.start()

    # Return the run object created by the engine (poll for completion)
    import time
    for _ in range(20):          # wait up to 2 s for the DB row to appear
        time.sleep(0.1)
        run = DemandCalculationRun.objects.filter(status='running').last()
        if run:
            return Response(RunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    return Response({'detail': 'تم بدء التشغيل في الخلفية'}, status=status.HTTP_202_ACCEPTED)


# ── Catch-up sync (manual override when scheduled 2 AM sync missed SOFTECH) ──

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def catchup_sync(request):
    """
    Manual override for when the scheduled sync didn't reach SOFTECH and sales
    went stale. Runs a robust CHUNKED sales backfill (any gap size, no timeout)
    then a normal engine run — in a background thread. Poll /runs/latest/ +
    /runs/active/ to track progress (same as the normal trigger).

    Fails fast (503) if SOFTECH is currently unreachable, so the user knows to
    retry later rather than waiting on a silent background failure.
    """
    profile = getattr(request.user, 'staff_profile', None)
    if not profile or profile.role not in ('admin', 'pharmacist'):
        return Response({'detail': 'غير مصرح'}, status=403)

    if DemandCalculationRun.objects.filter(status='running').exists():
        running = DemandCalculationRun.objects.filter(status='running').last()
        return Response(
            {'detail': 'يوجد تشغيل جارٍ بالفعل', 'run': RunSerializer(running).data},
            status=409,
        )

    # Fail fast if SOFTECH is down — the whole point is it may be unreachable.
    from .catchup import softech_reachable, run_catchup
    if not softech_reachable():
        return Response(
            {'detail': 'تعذّر الوصول إلى SOFTECH حالياً — أعد المحاولة عند توفّر الاتصال'},
            status=503,
        )

    # Create the run up front so the dashboard banner can track it immediately
    # (the frontend polls /runs/active/ which returns this row).
    from django.utils import timezone as _tz
    run = DemandCalculationRun.objects.create(
        status='running',
        calc_date=_tz.localdate(),
        progress={'phase': 'backfill', 'pct': 0, 'message': 'بدء مزامنة التعويض…'},
    )

    def _worker(run_id):
        try:
            run_catchup(run_id=run_id)
        except Exception as exc:
            logger.exception('[catchup] background catch-up failed: %s', exc)
        finally:
            from django.db import connections as _conns
            _conns.close_all()

    threading.Thread(target=_worker, args=(run.pk,), daemon=True,
                     name='purchasing-catchup').start()
    return Response(RunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


# ── Filter options (distinct values for filter dropdowns) ────────────────────

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def filter_options(request):
    """
    Return distinct filter option values for the purchasing dashboard dropdowns.

    Scoped to items that actually appear in the latest run's metrics, so the
    dropdowns only show values that are relevant to the current dataset.

    Response:
      {
        medicine_types: [{ code, name, name_ar }, ...],
        suppliers:      [{ code, name }, ...],
        producers:      [{ code, name }, ...],
        categories:     [{ id, softech_id, name, name_ar }, ...]
      }
    """
    from apps.catalog.models import Category, Item

    run = _latest_run()
    if run:
        item_ids = (
            ItemDemandMetrics.objects
            .filter(run=run)
            .values_list('item_id', flat=True)
            .distinct()
        )
        base_qs = Item.objects.filter(id__in=item_ids)
    else:
        base_qs = Item.objects.all()

    # ── Medicine types — grouped by code, first non-empty name wins ───────────
    med_rows = (
        base_qs
        .exclude(medicine_type='')
        .values('medicine_type', 'medicine_type_name', 'medicine_type_name_ar')
        .distinct()
        .order_by('medicine_type')
    )
    # Collapse to one entry per code (pick the best name)
    med_seen: dict = {}
    for r in med_rows:
        code = r['medicine_type']
        if code not in med_seen or not med_seen[code]['name']:
            med_seen[code] = {
                'code':    code,
                'name':    r['medicine_type_name'] or r['medicine_type_name_ar'] or code,
                'name_ar': r['medicine_type_name_ar'] or '',
            }
    medicine_types = sorted(med_seen.values(), key=lambda x: x['code'])

    # ── Suppliers ─────────────────────────────────────────────────────────────
    supp_rows = (
        base_qs
        .exclude(supplier_code='')
        .values('supplier_code', 'supplier_name')
        .distinct()
        .order_by('supplier_code')
    )
    supp_seen: dict = {}
    for r in supp_rows:
        code = r['supplier_code']
        if code not in supp_seen or not supp_seen[code]['name']:
            supp_seen[code] = {
                'code': code,
                'name': r['supplier_name'] or code,
            }
    suppliers = sorted(supp_seen.values(), key=lambda x: x['name'].lower())

    # ── Generic code→label list builder (dedup, ar-preferred sort) ────────────
    def _codelist(code_field, name_field, name_ar_field=None):
        fields = [code_field, name_field] + ([name_ar_field] if name_ar_field else [])
        seen: dict = {}
        for r in base_qs.exclude(**{code_field: ''}).values(*fields).distinct():
            code = r.get(code_field)
            if not code:
                continue
            nm   = r.get(name_field) or ''
            nmar = (r.get(name_ar_field) or '') if name_ar_field else ''
            if code not in seen or not seen[code]['name']:
                seen[code] = {'code': code, 'name': nm or code, 'name_ar': nmar or nm or code}
        return sorted(seen.values(), key=lambda x: (x['name_ar'] or x['name'] or '').lower())

    # العائلة (family), الشركة المنتجة (producer), المنشأ (origin),
    # الشكل الدوائى (shape), الاستخدام (effect) — all now distinct + correctly labelled.
    families  = _codelist('family_code',   'family_name',   'family_name_ar')
    producers = _codelist('producer_code', 'producer_name')
    origins   = _codelist('origin_code',   'origin_name',   'origin_name_ar')
    shapes    = _codelist('shape_code',    'shape_name',    'shape_name_ar')
    effects   = _codelist('effect_code',   'effect_name',   'effect_name_ar')

    # ── Categories ────────────────────────────────────────────────────────────
    category_ids = (
        base_qs
        .exclude(category__isnull=True)
        .values_list('category_id', flat=True)
        .distinct()
    )
    categories = list(
        Category.objects
        .filter(id__in=category_ids)
        .values('id', 'softech_id', 'name', 'name_ar')
        .order_by('name_ar')
    )

    # ── Store classif — dynamic from active items in run ─────────────────────
    store_rows = (
        base_qs.exclude(store_classif='')
        .values('store_classif', 'store_classif_name')
        .distinct()
        .order_by('store_classif')
    )
    store_seen: dict = {}
    for r in store_rows:
        code = r['store_classif']
        if code not in store_seen:
            store_seen[code] = {
                'code': code,
                'name': r['store_classif_name'] or code,
            }
    store_classif_options = sorted(store_seen.values(), key=lambda x: x['code'])

    # ── Static options (shared with catalog.filter_options) ───────────────────
    from apps.catalog.views import (
        INSURANCE_TYPE_OPTIONS, NOSALE_CLASSIF_OPTIONS,
        TRANS_OPTIONS, ITEM_LEVEL_OPTIONS,
    )

    return Response({
        'medicine_types':         medicine_types,   # تصنيف عام
        'categories':             categories,       # تصنيف (الشكل الصيدلى)
        'shapes':                 shapes,           # الشكل الدوائى / الخط
        'effects':                effects,          # الاستخدام
        'origins':                origins,          # المنشأ
        'suppliers':              suppliers,        # المورد
        'producers':              producers,        # الشركة المنتجة (real)
        'families':               families,         # العائلة
        # Operational / classification option lists:
        'insurance_types':        INSURANCE_TYPE_OPTIONS,
        'item_level_options':     ITEM_LEVEL_OPTIONS,
        'trans_options':          TRANS_OPTIONS,
        'nosale_classif_options': NOSALE_CLASSIF_OPTIONS,
        'store_classif_options':  store_classif_options,
    })


# ── Engine config (GET = read, PATCH = update) ────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def engine_config(request):
    """
    GET  — Return current engine calculation parameters.
    PATCH — Update parameters (admin only).

    Body (PATCH):
      {
        "weight_30d":      0.5,
        "weight_90d":      0.3,
        "weight_365d":     0.2,
        "abc_a_threshold": 70.0,
        "abc_b_threshold": 90.0
      }
    Any subset of fields may be provided; missing fields are unchanged.
    Validation: weights must each be in [0, 1]; thresholds must be in (0, 100).
    """
    from .models import EngineConfig

    if request.method == 'GET':
        cfg = EngineConfig.get()
        return Response(cfg.as_dict())

    # PATCH — admin only
    profile = getattr(request.user, 'staff_profile', None)
    if not profile or profile.role != 'admin':
        return Response({'detail': 'غير مصرح — للمدير فقط'}, status=403)

    cfg  = EngineConfig.get()
    data = request.data

    errors = {}
    FLOAT_FIELDS = {
        'weight_30d':         (0.0,   1.0),
        'weight_90d':         (0.0,   1.0),
        'weight_365d':        (0.0,   1.0),
        'ss_multiplier':      (0.5,   3.0),
        'ss_high_threshold':  (0.5,  10.0),
        'ss_tier_mid':        (0.0,  50.0),
        'ss_tier_low':        (0.0,  50.0),
        'ss_tier_vlow':       (0.0,  50.0),
        'abc_a_threshold':    (0.0, 100.0),
        'abc_b_threshold':    (0.0, 100.0),
        'coverage_months_a':  (0.1,   6.0),
        'coverage_months_b':  (0.1,   6.0),
        'coverage_months_c':  (0.1,   6.0),
        'in_transit_max_age_days': (0.0, 365.0),
    }
    for field, (lo, hi) in FLOAT_FIELDS.items():
        if field in data:
            try:
                val = float(data[field])
                if not (lo <= val <= hi):
                    errors[field] = f'يجب أن يكون بين {lo} و {hi}'
                else:
                    setattr(cfg, field, val)
            except (TypeError, ValueError):
                errors[field] = 'قيمة غير صالحة'

    if errors:
        return Response({'errors': errors}, status=400)

    # Basic weight sanity: sum should be close to 1.0
    weight_sum = cfg.weight_30d + cfg.weight_90d + cfg.weight_365d
    if abs(weight_sum - 1.0) > 0.01:
        return Response(
            {'errors': {'weights': f'مجموع الأوزان يجب أن يساوي 1 (الحالي: {weight_sum:.3f})'}},
            status=400,
        )

    if cfg.abc_a_threshold >= cfg.abc_b_threshold:
        return Response(
            {'errors': {'abc_a_threshold': 'حد A يجب أن يكون أقل من حد B'}},
            status=400,
        )

    # Safety stock tier ordering: mid >= low >= vlow (natural descending order)
    if cfg.ss_tier_mid < cfg.ss_tier_low:
        return Response(
            {'errors': {'ss_tier_mid': 'كمية أمان المتوسطة يجب أن تكون ≥ المنخفضة'}},
            status=400,
        )
    if cfg.ss_tier_low < cfg.ss_tier_vlow:
        return Response(
            {'errors': {'ss_tier_low': 'كمية أمان المنخفضة يجب أن تكون ≥ النادرة'}},
            status=400,
        )

    cfg.save()
    logger.info('[Config] Engine config updated by %s: %s', request.user, cfg.as_dict())
    return Response(cfg.as_dict())


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 2 — INTER-BRANCH TRANSFER RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════

from .models import TransferRecommendationRun, TransferRecommendation   # noqa: E402
from .serializers import (                                               # noqa: E402
    TransferRecommendationRunSerializer,
    TransferRecommendationSerializer,
)


def _latest_transfer_run(demand_run=None):
    """
    Return the most recent successful TransferRecommendationRun, optionally
    tied to a specific DemandCalculationRun.
    """
    qs = TransferRecommendationRun.objects.filter(status='success')
    if demand_run:
        qs = qs.filter(demand_run=demand_run)
    return qs.order_by('-started_at').first()


class TransferRecommendationListView(generics.ListAPIView):
    """
    Per-item × per-branch-pair transfer recommendations for the latest run.

    Filters:
      ?abc_class=A|B|C|X
      ?status=pending|approved|rejected|executed
      ?from_branch=<id>
      ?to_branch=<id>
      ?search=<item name or code>
      ?ordering=priority_score|-priority_score|estimated_value|-estimated_value|quantity|-quantity
    """
    serializer_class   = TransferRecommendationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['abc_class', 'status', 'from_branch', 'to_branch']
    search_fields      = ['item__name', 'item__softech_id']
    ordering_fields    = ['priority_score', 'estimated_value', 'quantity', 'to_gap']
    ordering           = ['-priority_score']

    def get_queryset(self):
        demand_run = _latest_run()
        if not demand_run:
            return TransferRecommendation.objects.none()

        rec_run = _latest_transfer_run(demand_run)
        if not rec_run:
            return TransferRecommendation.objects.none()

        qs = (
            TransferRecommendation.objects
            .filter(run=rec_run)
            .select_related('item', 'item__category', 'from_branch', 'to_branch')
            .prefetch_related('transfer_requests')   # prevents N+1 on is_actioned / count
        )
        qs = _apply_item_filters(qs, self.request.query_params)
        return qs


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def transfer_rec_latest_run(request):
    """
    Return the latest successful TransferRecommendationRun linked to the
    latest successful DemandCalculationRun.  404 if none exists yet.
    """
    demand_run = _latest_run()
    if not demand_run:
        return Response({'detail': 'لم يتم تشغيل المحرك بعد'}, status=404)

    rec_run = _latest_transfer_run(demand_run)
    if not rec_run:
        return Response({'detail': 'لا توجد توصيات تحويل بعد'}, status=404)

    return Response(TransferRecommendationRunSerializer(rec_run).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def transfer_rec_summary(request):
    """
    Summary stats for the latest transfer recommendation run.

    Response:
      {
        run_id, demand_run_id, status, started_at,
        total_recs, pending_recs, approved_recs, rejected_recs,
        total_value, items_covered,
        by_abc: { A: {count, value}, B: {...}, C: {...}, X: {...} },
        top_items: [ {item_name, item_code, total_value, branch_count}, ... ]  (top 10)
      }
    """
    demand_run = _latest_run()
    if not demand_run:
        return Response({'detail': 'لم يتم تشغيل المحرك بعد'}, status=404)

    rec_run = _latest_transfer_run(demand_run)
    if not rec_run:
        return Response({'detail': 'لا توجد توصيات بعد'}, status=404)

    qs = TransferRecommendation.objects.filter(run=rec_run)

    # Status counts
    from django.db.models import Sum as _Sum, Count as _Count
    status_agg = qs.values('status').annotate(cnt=_Count('id'))
    status_map = {row['status']: row['cnt'] for row in status_agg}

    # ABC breakdown
    abc_agg = (
        qs.values('abc_class')
          .annotate(cnt=_Count('id'), val=_Sum('estimated_value'))
    )
    by_abc = {
        row['abc_class']: {
            'count': row['cnt'],
            'value': float(row['val'] or 0),
        }
        for row in abc_agg
    }

    # Top 10 items by transfer value
    top_items_qs = (
        qs.values('item__name', 'item__softech_id')
          .annotate(
              total_value=_Sum('estimated_value'),
              branch_count=_Count('to_branch', distinct=True),
          )
          .order_by('-total_value')[:10]
    )
    top_items = [
        {
            'item_name':    row['item__name'],
            'item_code':    row['item__softech_id'],
            'total_value':  float(row['total_value'] or 0),
            'branch_count': row['branch_count'],
        }
        for row in top_items_qs
    ]

    # ── Adoption rate: how many recommendations became TransferRequests ─────────
    try:
        from apps.transfers.models import TransferRequest
        actioned_rec_ids = set(
            TransferRequest.objects
            .filter(source_recommendation__run=rec_run)
            .values_list('source_recommendation_id', flat=True)
            .distinct()
        )
        adoption_count = len(actioned_rec_ids)
        total_pending  = status_map.get('pending', 0) + status_map.get('approved', 0)
        adoption_rate  = round(adoption_count / max(total_pending, 1) * 100, 1)
    except Exception:
        adoption_count = 0
        adoption_rate  = 0.0

    return Response({
        'run_id':        rec_run.pk,
        'demand_run_id': demand_run.pk,
        'status':        rec_run.status,
        'started_at':    rec_run.started_at,
        'total_recs':    rec_run.total_recommendations,
        'pending_recs':  status_map.get('pending',  0),
        'approved_recs': status_map.get('approved', 0),
        'rejected_recs': status_map.get('rejected', 0),
        'executed_recs': status_map.get('executed', 0),
        'total_value':   float(rec_run.total_transfer_value or 0),
        'items_covered': rec_run.total_items_covered,
        'by_abc':        by_abc,
        'top_items':     top_items,
        # Adoption metrics — new
        'adoption_count': adoption_count,
        'adoption_rate':  adoption_rate,
    })


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def transfer_rec_update_status(request, pk):
    """
    PATCH /api/purchasing/transfer-recs/<pk>/status/

    Approve or reject a single transfer recommendation.
    Body: { "status": "approved" | "rejected", "notes": "..." }

    Restricted to admin and pharmacist roles.
    """
    profile = getattr(request.user, 'staff_profile', None)
    if not profile or profile.role not in ('admin', 'pharmacist'):
        return Response({'detail': 'غير مصرح'}, status=403)

    try:
        rec = TransferRecommendation.objects.get(pk=pk)
    except TransferRecommendation.DoesNotExist:
        return Response({'detail': 'التوصية غير موجودة'}, status=404)

    new_status = request.data.get('status', '').strip()
    allowed    = ('approved', 'rejected', 'executed')
    if new_status not in allowed:
        return Response(
            {'detail': f'الحالة يجب أن تكون إحدى: {", ".join(allowed)}'},
            status=400,
        )

    # Can only review pending items (guard against double-review)
    if rec.status not in ('pending', 'approved') and new_status != 'executed':
        return Response(
            {'detail': f'لا يمكن تغيير الحالة من "{rec.get_status_display()}"'},
            status=400,
        )

    from django.utils import timezone as _tz
    rec.status      = new_status
    rec.reviewed_by = request.user
    rec.reviewed_at = _tz.now()
    rec.notes       = request.data.get('notes', rec.notes)
    rec.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'notes'])

    logger.info(
        '[TransferRec] pk=%d → %s by %s', pk, new_status, request.user,
    )
    return Response(TransferRecommendationSerializer(rec).data)


# ── MODULE 13 — Lost Sales Intelligence ──────────────────────────────────────

from .models import LostSalesRun                                   # noqa: E402
from .serializers import LostSalesRunSerializer                    # noqa: E402


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def lost_sales_latest_run(request):
    """
    GET /api/purchasing/lost-sales/run/
    Returns the most recent LostSalesRun linked to the latest demand run.
    Returns 404 if no run exists yet.
    """
    demand_run = _latest_run()
    if demand_run is None:
        return Response({'detail': 'لا يوجد تشغيل سابق'}, status=404)
    try:
        ls_run = LostSalesRun.objects.get(demand_run=demand_run)
    except LostSalesRun.DoesNotExist:
        return Response({'detail': 'لم يتم تشغيل محرك المبيعات الضائعة بعد'}, status=404)
    return Response(LostSalesRunSerializer(ls_run).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def lost_sales_summary(request):
    """
    GET /api/purchasing/lost-sales/summary/
    Returns aggregate KPIs for the latest run.

    Response shape:
    {
        "run": {...},
        "total_lost_revenue_30d":  <Decimal>,
        "total_lost_margin_30d":   <Decimal>,
        "items_with_stockout":     <int>,
        "avg_availability_pct":    <float>,
        "root_cause_breakdown":    {<cause>: <count>, ...},
        "top_items": [
            {item_name, item_code, lost_revenue_30d, root_cause, branches_affected}, ...
        ]
    }
    """
    demand_run = _latest_run()
    if demand_run is None:
        return Response({'detail': 'لا يوجد تشغيل سابق'}, status=404)

    qs = (
        ItemDemandMetrics.objects
        .filter(run=demand_run, stockout_days_30d__gt=0)
        .select_related('item', 'branch')
    )

    # Aggregate KPIs
    agg = qs.aggregate(
        total_lost_rev    = Sum('lost_revenue_30d'),
        total_lost_margin = Sum('lost_margin_30d'),
        total_lost_qty    = Sum('lost_qty_30d'),
        items_count       = Count('item', distinct=True),
        avg_avail         = Sum('availability_rate_30d'),
    )

    row_count = qs.count()
    avg_avail = (agg['avg_avail'] or 0) / row_count if row_count else 100.0

    # Root cause breakdown
    root_cause_qs = (
        qs.values('root_cause')
        .annotate(
            cnt        = Count('id'),
            lost_rev   = Sum('lost_revenue_30d'),
        )
        .order_by('-lost_rev')
    )
    root_cause_breakdown = [
        {
            'root_cause': r['root_cause'],
            'count':      r['cnt'],
            'lost_revenue': str(r['lost_rev'] or 0),
        }
        for r in root_cause_qs
    ]

    # Top 20 items by lost revenue
    top_items_qs = (
        ItemDemandMetrics.objects
        .filter(run=demand_run, stockout_days_30d__gt=0)
        .select_related('item')
        .values('item__name', 'item__softech_id', 'root_cause')
        .annotate(
            total_lost_rev  = Sum('lost_revenue_30d'),
            branches_count  = Count('branch', distinct=True),
        )
        .order_by('-total_lost_rev')[:20]
    )
    top_items = [
        {
            'item_name':        t['item__name'],
            'item_code':        t['item__softech_id'],
            'lost_revenue_30d': str(t['total_lost_rev'] or 0),
            'root_cause':       t['root_cause'],
            'branches_affected': t['branches_count'],
        }
        for t in top_items_qs
    ]

    # LostSalesRun metadata
    try:
        ls_run = LostSalesRun.objects.get(demand_run=demand_run)
        run_data = LostSalesRunSerializer(ls_run).data
    except LostSalesRun.DoesNotExist:
        run_data = None

    return Response({
        'run':                    run_data,
        'total_lost_revenue_30d': str(agg['total_lost_rev']    or 0),
        'total_lost_margin_30d':  str(agg['total_lost_margin'] or 0),
        'total_lost_qty_30d':     str(agg['total_lost_qty']    or 0),
        'items_with_stockout':    agg['items_count'] or 0,
        'avg_availability_pct':   round(avg_avail, 1),
        'root_cause_breakdown':   root_cause_breakdown,
        'top_items':              top_items,
    })


# ── Advanced (experimental) replenishment — parallel-comparison export ───────

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def advanced_export(request):
    """
    Excel with CURRENT vs ADVANCED recommendation side-by-side (Phases A–D).
    Read-only, never touches stored metrics. Params: branch, abc_class.
    """
    import io as _io
    from openpyxl import Workbook
    from .advanced_engine import run_advanced_ranked, AdvancedConfig

    run = _latest_run()
    if not run:
        return Response({'detail': 'لا توجد بيانات — شغّل المحرك أولاً'}, status=503)

    qs = ItemDemandMetrics.objects.filter(run=run).select_related('item', 'branch')
    branch = request.GET.get('branch')
    if branch:
        qs = qs.filter(branch_id=branch)
    abc = request.GET.get('abc_class')
    if abc:
        qs = qs.filter(abc_class=abc)

    # Phase E — optional cash budget (EGP); 0/absent = unlimited (all funded).
    try:
        budget = float(request.GET.get('budget') or 0)
    except (TypeError, ValueError):
        budget = 0.0
    cfg = AdvancedConfig(cash_budget=budget)
    ranked_rows, e_summary = run_advanced_ranked(run, cfg, metrics_qs=qs)

    CLASS_AR = {
        'smooth': 'منتظم', 'erratic': 'متذبذب', 'intermittent': 'متقطع',
        'lumpy': 'متكتل', 'no_demand': 'بلا طلب',
    }
    FLAG_AR = {
        'overstock': 'فائض', 'dead_stock': 'راكد', 'order_on_demand': 'عند الطلب', 'lumpy': 'متكتل',
    }

    headers = [
        # identity
        'كود', 'الصنف', 'التصنيف العام', 'لا يُطلب (No More Use)', 'مؤرشف (Archive)',
        'ABC', 'الفرع', 'سعر', 'تكلفة',
        # CURRENT (الحالى)
        'C.معدل/شهر', 'C.كمية الأمان', 'C.الفجوة', 'C.المخزون', 'C.بالطريق',
        # ADVANCED A — cleansing + forecast
        'A.معدل منقّى', 'A.وحدات جملة', 'A.معامل الاتجاه', 'A.مؤشر موسمى', 'A.تنبؤ الطلب',
        # ADVANCED D — classification
        'D.نمط الطلب', 'D.ADI', 'D.CV²', 'D.معدل كروستون', 'D.طلب السياسة',
        # ADVANCED B — statistical safety
        'B.تباين', 'B.z الخدمة', 'B.أمان إحصائى',
        # ADVANCED C — ROP / JIT
        'C.مهلة(شهر)', 'C.مصدر المهلة', 'C.ROP', 'C.رفع حتى', 'C.المركز', 'C.اطلب الآن؟', 'C.كمية مقترحة', 'C.قيمة مقترحة', 'C.تغطية(شهر)',
        # flags
        'التنبيهات', 'قيمة الفائض',
        # ADVANCED E — ROI priority under cash budget
        'E.هامش %', 'E.هامش شهرى', 'E.إلحاح', 'E.عائد الاستثمار', 'E.أولوية الشراء',
        'E.ترتيب الشراء', 'E.ممول؟', 'E.تكلفة تراكمية',
    ]

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title='تحليل متقدم')
    ws.sheet_view.rightToLeft = True

    # ── Summary line — budget effect at a glance ─────────────────────────────
    es = e_summary
    if es['budget'] <= 0:
        summary_txt = (f"💰 بلا ميزانية محددة — كل الأصناف المطلوبة ممولة: "
                       f"{es['funded_count']:,} صنف بقيمة {es['funded_cost']:,.0f} ج.م")
    elif es['deferred_count'] == 0:
        summary_txt = (f"💰 الميزانية {es['budget']:,.0f} ج.م تكفى كل الاحتياج "
                       f"({es['total_need']:,.0f}) — كل الأصناف ({es['funded_count']:,}) ممولة")
    else:
        summary_txt = (f"💰 الميزانية {es['budget']:,.0f} من إجمالى احتياج {es['total_need']:,.0f} ج.م — "
                       f"ممول {es['funded_count']:,} صنف ({es['funded_cost']:,.0f}) · "
                       f"مؤجل {es['deferred_count']:,} صنف ({es['deferred_cost']:,.0f})")
    from openpyxl.cell import WriteOnlyCell as _WOC
    from openpyxl.styles import Font as _Font
    _sc = _WOC(ws, value=summary_txt)
    _sc.font = _Font(bold=True, size=11, color='7C3AED')
    ws.append([_sc])
    ws.append([])          # spacer row
    ws.append(headers)

    n = 0
    for m, a in ranked_rows:
        funded = a.get('funded')
        ws.append([
            m.item.softech_id, m.item.name,
            m.item.medicine_type_name_ar or m.item.medicine_type_name or '',
            'نعم' if m.item.no_more_use else 'لا',
            'نعم' if m.item.item_archive else 'لا',
            m.abc_class,
            (m.branch.name_ar or m.branch.name) if m.branch else '',
            float(m.pack_price or 0), float(m.item.cost_price or 0),
            float(m.monthly_avg or 0), float(m.safety_stock or 0), float(m.gap or 0),
            float(m.current_stock or 0), float(getattr(m, 'in_transit_qty', 0) or 0),
            a['cleansed_rate'], a['bulk_units'], a['trend_factor'], a['seasonal_index'], a['forecast_demand'],
            CLASS_AR.get(a['demand_class'], a['demand_class']), a['adi'], a['cv2'], a['croston_rate'], a['policy_demand'],
            a['demand_std'], a['service_z'], a['stat_safety'],
            a['lead_time_months'],
            'مورد' if a['lead_time_source'] == 'supplier' else 'افتراضى',
            a['rop'], a['order_up_to'], a['position'],
            'نعم' if a['order_now'] else '', a['rec_order_qty'], a['rec_order_value'], a['adv_coverage_months'],
            '، '.join(FLAG_AR.get(f, f) for f in a['flags']), a['excess_value'],
            round(a['gross_margin_pct'] * 100, 1), a['monthly_margin'], a['urgency'], a['roi'], a['priority_score'],
            a['rank'], ('ممول' if funded else 'مؤجل' if funded is False else ''), a['cum_cost'],
        ])
        n += 1

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    logger.info('[ADVANCED] exported %d rows (branch=%s abc=%s) | Phase E: %d buys, need %.0f, '
                'budget %.0f, funded %d (%.0f), deferred %d (%.0f)',
                n, branch, abc, e_summary['candidates'], e_summary['total_need'],
                e_summary['budget'], e_summary['funded_count'], e_summary['funded_cost'],
                e_summary['deferred_count'], e_summary['deferred_cost'])
    resp = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="purchasing-advanced-{run.calc_date}.xlsx"'
    return resp


# ── Advanced SUPPLIER pivot — one row per item, per-branch cols, pack rounding ─

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def advanced_pivot_export(request):
    """
    Supplier order sheet from the ADVANCED engine: ONE row per item, branches as
    columns. Per-branch need is whole UNITS (distribution); the purchase total is
    rounded UP to full PACKS (you buy whole packs). Includes a method/legend sheet.
    Read-only. Params: supplier (item.supplier_code), only_buy=1 (default).
    """
    import io as _io
    import math as _math
    from openpyxl import Workbook
    from apps.branches.models import Branch
    from .advanced_engine import run_advanced, AdvancedConfig

    run = _latest_run()
    if not run:
        return Response({'detail': 'لا توجد بيانات — شغّل المحرك أولاً'}, status=503)

    qs = ItemDemandMetrics.objects.filter(run=run).select_related('item', 'branch')
    supplier = request.GET.get('supplier')
    if supplier:
        qs = qs.filter(item__supplier_code=supplier)
    only_buy = request.GET.get('only_buy', '1') != '0'

    branch_ids = list(qs.values_list('branch_id', flat=True).distinct())
    branches = list(Branch.objects.filter(id__in=branch_ids).order_by('softech_branch_id'))

    CLASS_AR = {'smooth': 'منتظم', 'erratic': 'متذبذب', 'intermittent': 'متقطع',
                'lumpy': 'متكتل', 'no_demand': 'بلا طلب'}

    # Aggregate advanced per-branch whole-unit needs → per item.
    items = {}
    for m, a in run_advanced(run, AdvancedConfig(), metrics_qs=qs):
        d = items.setdefault(m.item_id, {
            'item': m.item, 'units': {}, 'pack_qty': a['pack_qty'],
            'best_class': a['demand_class'], 'best_units': -1.0, 'max_priority': 0.0,
        })
        u = a['rec_order_qty']
        d['units'][m.branch_id] = d['units'].get(m.branch_id, 0) + u
        if u > d['best_units']:
            d['best_units'] = u
            d['best_class'] = a['demand_class']
        d['max_priority'] = max(d['max_priority'], a['priority_score'])

    # Demand / stock / order are all in whole BOXES (= the pack you buy & distribute).
    # Each branch's need is already rounded UP to a whole box in the engine, so the
    # purchase is simply their sum (all integers). pack_qty = strips per box = INFO only.
    rows = []
    for _iid, d in items.items():
        total_boxes = int(round(sum(d['units'].values())))
        if only_buy and total_boxes <= 0:
            continue
        item = d['item']
        pval = round(total_boxes * float(item.cost_price or 0), 2)
        rows.append((item, d, total_boxes, pval))
    rows.sort(key=lambda r: r[3], reverse=True)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title='طلب الموردين')
    ws.sheet_view.rightToLeft = True
    headers = ['كود', 'الصنف', 'التصنيف العام', 'لا يُطلب (No More Use)', 'مؤرشف (Archive)',
               'المورد', 'الشركة المنتجة', 'وحدات العبوة (للعلم)', 'سعر جمهور', 'سعر تكلفة']
    headers += [f'فرع {b.softech_branch_id}' for b in branches]
    headers += ['إجمالى العبوات للشراء', 'قيمة الشراء (تكلفة)', 'نمط الطلب', 'أولوية']
    ws.append(headers)

    n = 0
    for item, d, total_boxes, pval in rows:
        row = [item.softech_id, item.name,
               item.medicine_type_name_ar or item.medicine_type_name or '',
               'نعم' if item.no_more_use else 'لا',
               'نعم' if item.item_archive else 'لا',
               item.supplier_name or item.supplier_code,
               item.producer_name or '', d['pack_qty'], float(item.pack_price or 0), float(item.cost_price or 0)]
        row += [(int(round(d['units'].get(b.id, 0))) or None) for b in branches]
        row += [total_boxes, pval,
                CLASS_AR.get(d['best_class'], d['best_class']), round(d['max_priority'], 3)]
        ws.append(row)
        n += 1

    # ── Method / legend sheet (embeds the explanation) ───────────────────────
    ws2 = wb.create_sheet(title='الشرح والطريقة')
    ws2.sheet_view.rightToLeft = True
    for line in [
        ['ورقة طلب الموردين — المحرك المتقدم (تجريبى، منفصل عن الحساب الحالى)'],
        [''],
        ['التقريب المعتمد (كل الكميات بالعبوات الكاملة — لا وحدات ولا كسور):'],
        ['• وحدة الطلب والمخزون والشراء هى «العبوة» — وهى ما يُشترى من المورد ويُوزَّع للفروع.'],
        ['• لكل فرع: الاحتياج يُقرَّب لأعلى لأقرب عبوة كاملة (لا عبوات جزئية).'],
        ['• الشراء من المورد = مجموع عبوات كل الفروع (كلها أعداد صحيحة).'],
        ['• «وحدات العبوة» = عدد الشرائط/الأمبولات داخل العبوة — للعلم فقط، لا يدخل حساب الطلب.'],
        [''],
        ['كيف يُحسب احتياج كل فرع (خطوات المحرك):'],
        ['A) تنقية الجملة: الشهور الشاذة (بيع جملة) تُقصّ عند وسيط×3 لاستخراج الطلب الأساسى.'],
        ['A) الاتجاه: ميل آخر 6 شهور (±75% كحد). الموسمية: مؤشر شهر التغطية القادم.'],
        ['A) تنبؤ الطلب = المعدل المنقّى × معامل الاتجاه × المؤشر الموسمى.'],
        ['D) تصنيف الطلب (ADI/CV²): منتظم/متذبذب/متقطع/متكتل. المتقطع يستخدم معدل كروستون (أقل) لمنع التكديس.'],
        ['B) كمية الأمان الإحصائية = z(مستوى الخدمة حسب ABC) × انحراف الطلب × جذر(مهلة التوريد).'],
        ['C) نقطة إعادة الطلب ROP = طلب×مهلة + أمان. الرفع حتى S = طلب×(مهلة+دورة المراجعة) + أمان.'],
        ['C) يُطلب فقط عندما (المخزون + بالطريق) ≤ ROP، والكمية = S − (المخزون + بالطريق).'],
        ['E) الأولوية = العائد(هامش شهرى/تكلفة الشراء) × الإلحاح × ثقة النمط × وزن ABC.'],
        [''],
        ['الأعمدة:'],
        ['فرع NNN = عدد العبوات المطلوب توزيعها لهذا الفرع (عدد صحيح).'],
        ['إجمالى العبوات للشراء = مجموع عبوات كل الفروع = ما يُطلب من المورد.'],
        ['قيمة الشراء = إجمالى العبوات × سعر التكلفة.'],
        ['نمط الطلب = تصنيف الفرع الأكبر احتياجاً. أولوية = أعلى درجة أولوية للصنف.'],
        [''],
        [f'التشغيل: {run.calc_date} — {n} صنف — بيانات المبيعات حتى: {run.data_through_date or "?"}'],
    ]:
        ws2.append(line)

    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    logger.info('[ADV-PIVOT] %d items, %d branches, supplier=%s', n, len(branches), supplier)
    resp = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="advanced-supplier-order-{run.calc_date}.xlsx"'
    return resp
