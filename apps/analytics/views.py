"""
apps/analytics/views.py

Comprehensive analytics — full filter set from stktrans / stktransm data.

Filters supported across all views:
  date_from, date_to      YYYY-MM-DD inclusive date range
  date_exact              single date (overrides range)
  hour_from, hour_to      0-23 inclusive hour range
  hour_exact              single hour (overrides range)
  days_of_week            comma-sep Django week_day: 1=Sun 2=Mon … 7=Sat
  branches                comma-sep Branch IDs  (OR: single 'branch')
  doc_codes               comma-sep: '115'=sales '30'=returns (default: both)
  person_codes            comma-sep softech_user codes (cashier filter)
  channels                comma-sep sales_channel values (personsdata.ptclassifcode)
  person_types            comma-sep sales_person_type values (personsdata.ptcode)
  medicine_types          comma-sep Item.medicine_type codes
  supplier_codes          comma-sep Item.supplier_code values
  producer_codes          comma-sep Item.producer_code values
  abc_class               comma-sep: A B C X  (inventory only)

Revenue convention:
  doccode 80 (SOFTECH reservation preview) is ALWAYS excluded — it is an
  internal booking step that does NOT represent a completed sale.
  Net revenue = SUM(115 total_amount) − SUM(30 total_amount).
  Returns (30) are stored with positive amounts in the DB; we subtract them.
"""

import datetime
import logging

from django.db.models import (
    Avg, Count, DecimalField, ExpressionWrapper, F, FloatField, Q, Sum,
)
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine

logger = logging.getLogger('elrezeiky.analytics')


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _parse_list(s):
    """'a,b, c' → ['a','b','c']"""
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def _parse_int_list(s):
    out = []
    for v in _parse_list(s):
        try:
            out.append(int(v))
        except ValueError:
            pass
    return out


def _safe_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _build_user_map():
    """
    Return {usercode: {'name': display_name, 'user_id': erp_user_id}}
    sourced from ERPUser (populated every sync).
    Falls back to StaffProfile for names when a full name is set.
    """
    try:
        from apps.users.models import ERPUser, StaffProfile
        result: dict = {}

        # Base from ERPUser — always present after sync
        for eu in ERPUser.objects.only('username', 'user_id', 'full_name'):
            result[eu.username] = {
                'name':    eu.full_name or eu.username,
                'user_id': eu.user_id or '',
            }

        # Overlay with StaffProfile full names (Arabic names entered by admin)
        for sp in (
            StaffProfile.objects
            .select_related('user')
            .exclude(softech_user_id='')
        ):
            if sp.softech_user_id in result:
                result[sp.softech_user_id]['name'] = sp.full_name or result[sp.softech_user_id]['name']
            else:
                result[sp.softech_user_id] = {
                    'name':    sp.full_name or sp.softech_user_id,
                    'user_id': '',
                }
        return result
    except Exception:
        return {}


def _user_name(user_map, code):
    """Extract a plain display-name string from the user_map dict-of-dicts.
    user_map values are {'name': str, 'user_id': str}; fall back to code itself."""
    entry = user_map.get(code)
    if isinstance(entry, dict):
        return entry.get('name') or code
    return entry or code


def _purchase_qs_filtered(params):
    """
    Build a fully-filtered PurchaseHistory queryset from request query params dict.

    doccode 80 (SOFTECH reservations / booking previews) is ALWAYS excluded —
    it is an internal SOFTECH step, not a completed sale or return, and it would
    otherwise double-count revenue with doccode 115.
    """
    # doccode 80 is permanently excluded — never a real sale or return.
    qs = PurchaseHistory.objects.exclude(doc_code='80')

    # ── Date ─────────────────────────────────────────────────────────────────
    date_exact = _parse_date(params.get('date_exact'))
    if date_exact:
        qs = qs.filter(invoice_date__date=date_exact)
    else:
        df = _parse_date(params.get('date_from'))
        dt = _parse_date(params.get('date_to'))
        if df:
            qs = qs.filter(invoice_date__date__gte=df)
        if dt:
            qs = qs.filter(invoice_date__date__lte=dt)

    # ── Hour ─────────────────────────────────────────────────────────────────
    # Use trans_time (stktrans.transtime) when available — it carries the actual
    # clock time of each transaction.  invoice_date comes from stktransm.docdate
    # which is date-only (stored as midnight) and is useless for hour filtering.
    # For records synced before trans_time was added (trans_time IS NULL), fall
    # back gracefully to invoice_date so old data still matches.
    hour_exact = _safe_int(params.get('hour_exact'))
    if hour_exact is not None:
        from django.db.models import Q as _Q
        qs = qs.filter(
            _Q(trans_time__isnull=False, trans_time__hour=hour_exact) |
            _Q(trans_time__isnull=True,  invoice_date__hour=hour_exact)
        )
    else:
        hf = _safe_int(params.get('hour_from'))
        ht = _safe_int(params.get('hour_to'))
        if hf is not None or ht is not None:
            from django.db.models import Q as _Q
            q_new = _Q(trans_time__isnull=False)
            q_old = _Q(trans_time__isnull=True)
            if hf is not None:
                q_new &= _Q(trans_time__hour__gte=hf)
                q_old &= _Q(invoice_date__hour__gte=hf)
            if ht is not None:
                q_new &= _Q(trans_time__hour__lte=ht)
                q_old &= _Q(invoice_date__hour__lte=ht)
            qs = qs.filter(q_new | q_old)

    # ── Day of week (Django week_day: 1=Sun … 7=Sat) ─────────────────────────
    dow = _parse_int_list(params.get('days_of_week'))
    if dow:
        qs = qs.filter(invoice_date__week_day__in=dow)

    # ── Branch ───────────────────────────────────────────────────────────────
    branches = _parse_list(params.get('branches'))
    if branches:
        qs = qs.filter(branch_id__in=branches)
    elif params.get('branch'):
        qs = qs.filter(branch_id=params.get('branch'))

    # ── Doc code (115=sale, 30=return; default both; 80 always excluded above) ─
    doc_codes = _parse_list(params.get('doc_codes'))
    if doc_codes:
        # User can further narrow; silently drop any '80' even if passed
        filtered = [c for c in doc_codes if c != '80']
        if filtered:
            qs = qs.filter(doc_code__in=filtered)

    # ── Cashier / person code ─────────────────────────────────────────────────
    person_codes = _parse_list(params.get('person_codes'))
    if person_codes:
        qs = qs.filter(softech_user__in=person_codes)

    # ── Sales channel (uses denormalized sales_channel field on PurchaseHistory)
    channels = _parse_list(params.get('channels'))
    if channels:
        qs = qs.filter(sales_channel__in=channels)

    # ── Person type (uses denormalized sales_person_type = personsdata.ptcode)
    person_types = _parse_list(params.get('person_types'))
    if person_types:
        qs = qs.filter(sales_person_type__in=person_types)

    # ── Store code (stktrans.storecode — warehouse/store within a branch)
    store_codes = _parse_list(params.get('store_codes'))
    if store_codes:
        qs = qs.filter(store_code__in=store_codes)

    # ── Customer branch code (stktransm.cust_branch_code — ordering/delivery branch)
    cust_branch_codes = _parse_list(params.get('cust_branch_codes'))
    if cust_branch_codes:
        qs = qs.filter(cust_branch_code__in=cust_branch_codes)

    # ── Specific customers (by Django Customer PK, from the customer search)
    customer_ids = _parse_int_list(params.get('customer_ids'))
    if customer_ids:
        qs = qs.filter(customer_id__in=customer_ids)

    # ── Customers by personcode / softech_id (العميل dropdown, from personsdata)
    person_main_codes = _parse_list(params.get('person_main_codes'))
    if person_main_codes:
        qs = qs.filter(customer__softech_id__in=person_main_codes)

    return qs


def _line_qs_for(purchase_qs, params=None):
    """
    Build PurchaseHistoryLine queryset with optional item-level filters.
    Supports: medicine_types, supplier_codes, producer_codes,
              insurance_types, store_classifs, nosale_classifs,
              is_fast_moving, has_points, item_level,
              branch_trans, supplier_trans, customer_trans.
    """
    qs = PurchaseHistoryLine.objects.filter(purchase__in=purchase_qs)
    if params:
        med_types = _parse_list(params.get('medicine_types'))
        if med_types:
            qs = qs.filter(item__medicine_type__in=med_types)

        supplier_codes = _parse_list(params.get('supplier_codes'))
        if supplier_codes:
            qs = qs.filter(item__supplier_code__in=supplier_codes)

        producer_codes = _parse_list(params.get('producer_codes'))
        if producer_codes:
            qs = qs.filter(item__producer_code__in=producer_codes)

        # ── Operational item filters ─────────────────────────────────────────
        insurance_types = _parse_list(params.get('insurance_types'))
        if insurance_types:
            qs = qs.filter(item__insurance_type__in=insurance_types)

        store_classifs = _parse_list(params.get('store_classifs'))
        if store_classifs:
            qs = qs.filter(item__store_classif__in=store_classifs)

        nosale_classifs = _parse_list(params.get('nosale_classifs'))
        if nosale_classifs:
            qs = qs.filter(item__nosale_classif__in=nosale_classifs)

        if params.get('is_fast_moving') == '1':
            qs = qs.filter(item__is_fast_moving=True)
        if params.get('has_points') == '1':
            qs = qs.filter(item__has_points=True)

        item_level = params.get('item_level')
        if item_level not in (None, ''):
            try:
                qs = qs.filter(item__item_level=int(item_level))
            except (ValueError, TypeError):
                pass

        branch_trans = params.get('branch_trans')
        if branch_trans not in (None, ''):
            qs = qs.filter(item__branch_trans=branch_trans)

        supplier_trans = params.get('supplier_trans')
        if supplier_trans not in (None, ''):
            qs = qs.filter(item__supplier_trans=supplier_trans)

        customer_trans = params.get('customer_trans')
        if customer_trans not in (None, ''):
            qs = qs.filter(item__customer_trans=customer_trans)

    return qs


# Profit  = sale revenue - (cost_at_sale × quantity)
# Uses cost_at_sale (stktrans.itemcostprice) — cost recorded at time of each
# transaction. This matches SOFTECH exactly. Item.cost_price is the CURRENT
# catalog cost (updated every sync) and diverges from historic transaction costs,
# causing COGS / profit discrepancies vs ERP reports.
_PROFIT = ExpressionWrapper(
    F('line_total') - F('cost_at_sale') * F('quantity'),
    output_field=FloatField(),
)

# COGS = cost_at_sale × quantity  (cost of goods sold per line)
_COGS = ExpressionWrapper(
    F('cost_at_sale') * F('quantity'),
    output_field=FloatField(),
)

# Discount = (pack_price × quantity) - sale revenue  [positive = discount given]
_DISCOUNT = ExpressionWrapper(
    F('item__pack_price') * F('quantity') - F('line_total'),
    output_field=FloatField(),
)

_DOW_LABELS = {
    1: 'الأحد', 2: 'الاثنين', 3: 'الثلاثاء',
    4: 'الأربعاء', 5: 'الخميس', 6: 'الجمعة', 7: 'السبت',
}


def _margin(profit, revenue):
    return round(profit / revenue * 100, 2) if revenue else 0.0


# Module-level caches — invalidated by sync task after every run.
_channel_label_cache: dict | None = None
_person_type_label_cache: dict | None = None


def _get_channel_label_map() -> dict:
    """
    ptclassifcode → Arabic label.

    Primary source: SoftechPersonClassif (populated on every sync from persontypesclassif).
    Fallback: Customer.person_classif_label (populated during customer sync).
    Cached per process; invalidated by sync task.
    """
    global _channel_label_cache
    if _channel_label_cache is not None:
        return _channel_label_cache

    m: dict = {'': 'غير مصنّف'}

    # 1. Primary — SoftechPersonClassif label cache (most reliable, synced independently)
    # Priority order: ptcode='10' (Corporate Customer) first, then ptcode='11' (Individual),
    # then everything else.  This ensures customer-channel labels win over supplier labels
    # when the same ptclassifcode appears under multiple person types.
    try:
        from apps.sync.models import SoftechPersonClassif
        # Pass 1 — all non-customer ptcodes (lower priority, may be overwritten)
        for row in (SoftechPersonClassif.objects
                    .exclude(ptclassifdescr='')
                    .exclude(ptcode__in=['10', '11'])
                    .values('ptclassifcode', 'ptclassifdescr')):
            code  = row['ptclassifcode']
            label = row['ptclassifdescr']
            if code and label:
                m[code] = label
        # Pass 2 — customer ptcodes overwrite any supplier labels for the same code
        for row in (SoftechPersonClassif.objects
                    .exclude(ptclassifdescr='')
                    .filter(ptcode__in=['10', '11'])
                    .values('ptclassifcode', 'ptclassifdescr')):
            code  = row['ptclassifcode']
            label = row['ptclassifdescr']
            if code and label:
                m[code] = label
    except Exception:
        pass

    # 2. Fallback — Customer.person_classif_label (populated after customer sync)
    if len(m) <= 1:
        rows = (
            Customer.objects
            .exclude(softech_ptclassifcode='')
            .exclude(person_classif_label='')
            .values('softech_ptclassifcode', 'person_classif_label')
            .distinct()
        )
        for r in rows:
            code  = r['softech_ptclassifcode']
            label = r['person_classif_label']
            if code and label:
                m[code] = label

    if len(m) > 1:
        _channel_label_cache = m
    return m


def _get_person_type_label_map() -> dict:
    """
    ptcode → Arabic label.

    Primary source: SoftechPersonType cache; fallback: Customer.person_type_label.
    """
    global _person_type_label_cache
    if _person_type_label_cache is not None:
        return _person_type_label_cache

    m: dict = {}

    try:
        from apps.sync.models import SoftechPersonType
        for row in SoftechPersonType.objects.exclude(ptdescr='').values('ptcode', 'ptdescr'):
            if row['ptcode'] and row['ptdescr']:
                m[row['ptcode']] = row['ptdescr']
    except Exception:
        pass

    if not m:
        rows = (
            Customer.objects
            .exclude(softech_ptcode='')
            .exclude(person_type_label='')
            .values('softech_ptcode', 'person_type_label')
            .distinct()
        )
        for r in rows:
            if r['softech_ptcode'] and r['person_type_label']:
                m[r['softech_ptcode']] = r['person_type_label']

    if m:
        _person_type_label_cache = m
    return m


def _channel_label(code):
    """Return Arabic label for a channel code, falling back to the code itself."""
    if code is None or code == '':
        return 'غير مصنّف'
    m = _get_channel_label_map()
    return m.get(str(code), str(code))


def _person_type_label(code):
    """Return Arabic label for a person-type code."""
    if not code:
        return code or ''
    m = _get_person_type_label_map()
    return m.get(str(code), str(code))


# ═══════════════════════════════════════════════════════════════════════════════
#  NET REVENUE HELPER — sales (115) minus returns (30)
# ═══════════════════════════════════════════════════════════════════════════════

def _net_revenue_from_qs(qs):
    """
    Compute net_revenue = SUM(115) - SUM(30) from a PurchaseHistory queryset.
    Returns (net_revenue, sales_revenue, returns_revenue, sales_count, returns_count).
    """
    sales_rev = float(
        qs.filter(doc_code='115').aggregate(t=Sum('total_amount'))['t'] or 0
    )
    returns_rev = float(
        qs.filter(doc_code='30').aggregate(t=Sum('total_amount'))['t'] or 0
    )
    sales_cnt   = qs.filter(doc_code='115').count()
    returns_cnt = qs.filter(doc_code='30').count()
    net = sales_rev - returns_rev
    return net, sales_rev, returns_rev, sales_cnt, returns_cnt


# ═══════════════════════════════════════════════════════════════════════════════
#  0. FILTER OPTIONS  (single call, populates all dashboards)
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def filter_options(request):
    """
    GET /api/analytics/filter-options/
    Returns all available values for every filter across all dashboards.
    """
    # Branches
    branches = [
        {'id': str(b.id), 'name': b.name_ar or b.name}
        for b in Branch.objects.filter(is_active=True).order_by('name_ar', 'name')
    ]

    # Users/cashiers — show usercode + ERP userid + full name
    user_map = _build_user_map()   # {usercode: {'name': ..., 'user_id': ...}}
    active_codes = set(
        PurchaseHistory.objects
        .exclude(softech_user='')
        .values_list('softech_user', flat=True)
        .distinct()
    )
    users = sorted(
        [
            {
                'code':    c,
                'user_id': user_map.get(c, {}).get('user_id', '') if isinstance(user_map.get(c), dict) else '',
                'name':    user_map.get(c, {}).get('name', c)     if isinstance(user_map.get(c), dict) else (user_map.get(c) or c),
            }
            for c in active_codes
        ],
        key=lambda x: x['name'],
    )

    # Doc types
    doc_types = [
        {'code': '115', 'label': 'مبيعات'},
        {'code': '30',  'label': 'مردودات'},
    ]

    # Sales channels (= نوع العميل in SOFTECH) — from actual PurchaseHistory.sales_channel
    # values, labelled via SoftechPersonClassif cache → persontypesclassif.ptclassifdescr.
    raw_channels = (
        PurchaseHistory.objects
        .exclude(sales_channel='')
        .values_list('sales_channel', flat=True)
        .distinct()
        .order_by('sales_channel')
    )
    channels = [
        {'code': c, 'label': _channel_label(c)}
        for c in raw_channels
        if c
    ]
    # Sort by label (Arabic) for readability
    channels.sort(key=lambda x: x['label'])
    # Add "unclassified" if there are records without a channel
    if PurchaseHistory.objects.filter(sales_channel='').exists():
        channels.append({'code': '', 'label': 'غير مصنّف'})

    # Medicine types (itemmedicine codes)
    med_rows = (
        Item.objects
        .exclude(medicine_type='')
        .values('medicine_type', 'medicine_type_name_ar', 'medicine_type_name')
        .distinct()
        .order_by('medicine_type_name_ar')
    )
    medicine_types = [
        {
            'code':  m['medicine_type'],
            'label': m['medicine_type_name_ar'] or m['medicine_type_name'] or m['medicine_type'],
        }
        for m in med_rows
    ]

    # ABC classes
    abc_classes = [
        {'code': 'A', 'label': 'فئة A — دوران عالٍ'},
        {'code': 'B', 'label': 'فئة B — دوران متوسط'},
        {'code': 'C', 'label': 'فئة C — دوران منخفض'},
        {'code': 'X', 'label': 'فئة X — غير محدد'},
    ]

    # Days of week (ordered Mon → Sun for Arabic week)
    days_of_week = [
        {'code': 2, 'label': 'الاثنين'},
        {'code': 3, 'label': 'الثلاثاء'},
        {'code': 4, 'label': 'الأربعاء'},
        {'code': 5, 'label': 'الخميس'},
        {'code': 6, 'label': 'الجمعة'},
        {'code': 7, 'label': 'السبت'},
        {'code': 1, 'label': 'الأحد'},
    ]

    # Person types (personsdata.ptcode) — unique codes from PurchaseHistory,
    # labelled via SoftechPersonType cache → persontypes.ptdescr.
    raw_pt_codes = (
        PurchaseHistory.objects
        .exclude(sales_person_type='')
        .values_list('sales_person_type', flat=True)
        .distinct()
        .order_by('sales_person_type')
    )
    person_types = [
        {
            'code':  c,
            'label': _person_type_label(c),
        }
        for c in raw_pt_codes
        if c
    ]

    # Person classifs — same as channels but also surfaced from Customer master data.
    # Useful as a separate filter to distinguish "نوع العميل" by classification code.
    pc_codes = (
        Customer.objects
        .exclude(softech_ptclassifcode='')
        .values_list('softech_ptclassifcode', flat=True)
        .distinct()
        .order_by('softech_ptclassifcode')
    )
    person_classifs = sorted(
        [
            {
                'code':  c,
                'label': _channel_label(c),
            }
            for c in pc_codes
            if c
        ],
        key=lambda x: x['label'],
    )

    # Suppliers — from Item.supplier_code (synced from SOFTECH itemssuppliers)
    sup_rows = (
        Item.objects
        .exclude(supplier_code='')
        .values('supplier_code', 'supplier_name')
        .distinct()
        .order_by('supplier_name')
    )
    suppliers = [
        {
            'code':  r['supplier_code'],
            'label': r['supplier_name'] or r['supplier_code'],
        }
        for r in sup_rows
        if r['supplier_code']
    ]

    # Producers — from Item.producer_code (synced from SOFTECH itemsproducers)
    prod_rows = (
        Item.objects
        .exclude(producer_code='')
        .values('producer_code', 'producer_name')
        .distinct()
        .order_by('producer_name')
    )
    producers = [
        {
            'code':  r['producer_code'],
            'label': r['producer_name'] or r['producer_code'],
        }
        for r in prod_rows
        if r['producer_code']
    ]

    # Store codes — distinct storecode values from PurchaseHistory
    # These are warehouse/store identifiers within branches (e.g. '01', '02').
    raw_store_codes = (
        PurchaseHistory.objects
        .exclude(store_code='')
        .values_list('store_code', flat=True)
        .distinct()
        .order_by('store_code')
    )
    store_codes = [
        {'code': sc, 'label': f'مخزن {sc}'}
        for sc in raw_store_codes
        if sc
    ]

    # Customer branch codes — kept for backward compat but no longer shown in UI.
    cust_branch_codes = []

    # Persons (العميل) — top 800 customers from PurchaseHistory by invoice count,
    # labelled by their name from Customer (synced from personsdata.personname).
    # Excludes anonymous walk-in (1500) and home-delivery (1510) person codes.
    from django.db.models import Count as _Count
    persons_qs = (
        PurchaseHistory.objects
        .exclude(customer__softech_id__in=['1500', '1510'])
        .exclude(customer__name='')
        .values('customer__softech_id', 'customer__name')
        .annotate(_cnt=_Count('id'))
        .order_by('-_cnt')[:800]
    )
    persons = sorted(
        [
            {'code': row['customer__softech_id'], 'label': row['customer__name']}
            for row in persons_qs
            if row['customer__softech_id'] and row['customer__name']
        ],
        key=lambda x: x['label'],
    )

    return Response({
        'branches':          branches,
        'users':             users,
        'doc_types':         doc_types,
        'channels':          channels,
        'person_types':      person_types,
        'person_classifs':   person_classifs,
        'medicine_types':    medicine_types,
        'suppliers':         suppliers,
        'producers':         producers,
        'store_codes':       store_codes,
        'cust_branch_codes': cust_branch_codes,
        'persons':           persons,
        'abc_classes':       abc_classes,
        'days_of_week':      days_of_week,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  1. SALES OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_overview(request):
    """
    GET /api/analytics/sales/
    Full filter set — see module docstring.

    Net revenue = SUM(115) − SUM(30).  doccode 80 always excluded.
    """
    p = request.query_params
    qs      = _purchase_qs_filtered(p)
    line_qs = _line_qs_for(qs, p)
    user_map = _build_user_map()

    # ── Sales vs returns split ────────────────────────────────────────────────
    net_rev, sales_rev, returns_rev, sales_cnt, returns_cnt = _net_revenue_from_qs(qs)
    return_rate = round(returns_rev / sales_rev * 100, 2) if sales_rev else 0.0

    # ── Top-level summary ────────────────────────────────────────────────────
    total_transactions = qs.count()
    distinct_customers = qs.aggregate(d=Count('customer', distinct=True))['d'] or 0
    # Count distinct PICs from SALES invoices only (doc_code='115'), matching
    # how SOFTECH counts "unique customers" in its daily reports.
    # Returns (doc_code='30') are excluded to avoid inflating the count.
    distinct_piccodes  = (
        qs.filter(doc_code='115').exclude(softech_phcode='')
          .aggregate(d=Count('softech_phcode', distinct=True))['d'] or 0
    )

    # Net profit and net COGS must subtract return-line contributions.
    # Return invoices are stored with POSITIVE quantities and amounts — without
    # this correction, summing all lines overstates COGS and understates profit.
    #
    # net_profit = Σ(profit on sales lines) − Σ(profit on return lines)
    # net_cogs   = Σ(cogs   on sales lines) − Σ(cogs   on return lines)
    #
    # Using conditional Sum in a single aggregate query (one DB round-trip).
    lines_agg = line_qs.aggregate(
        profit_s     = Sum(_PROFIT,   filter=Q(purchase__doc_code='115')),
        profit_r     = Sum(_PROFIT,   filter=Q(purchase__doc_code='30')),
        cogs_s       = Sum(_COGS,     filter=Q(purchase__doc_code='115')),
        cogs_r       = Sum(_COGS,     filter=Q(purchase__doc_code='30')),
        total_discount  = Sum(_DISCOUNT,  filter=Q(purchase__doc_code='115')),
        total_qty       = Sum('quantity', filter=Q(purchase__doc_code='115')),
        total_line_count= Count('id',     filter=Q(purchase__doc_code='115')),
        distinct_items  = Count('item', distinct=True,
                                filter=Q(purchase__doc_code='115')),
    )
    total_profit   = float(lines_agg['profit_s'] or 0) - float(lines_agg['profit_r'] or 0)
    total_cogs     = float(lines_agg['cogs_s']   or 0) - float(lines_agg['cogs_r']   or 0)
    total_discount = float(lines_agg['total_discount']  or 0)
    total_qty      = float(lines_agg['total_qty']       or 0)
    total_line_count = lines_agg['total_line_count']    or 0
    distinct_items   = lines_agg['distinct_items']      or 0

    # Use net_revenue (sales - returns) everywhere as the primary revenue metric.
    avg_basket    = round(net_rev / total_transactions, 2) if total_transactions else 0.0
    items_per_trx = round(total_line_count / total_transactions, 2) if total_transactions else 0.0
    profit_margin = _margin(total_profit, net_rev)

    # ── By branch ────────────────────────────────────────────────────────────
    by_branch = []
    for row in (
        qs.values('branch__id', 'branch__name', 'branch__name_ar')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              distinct_cust  = Count('customer', distinct=True),
          )
          .order_by('-sales_amount')
    ):
        bid      = row['branch__id']
        s_rev    = float(row['sales_amount'] or 0)
        r_rev    = float(row['returns_amount'] or 0)
        b_net    = s_rev - r_rev
        bl  = line_qs.filter(purchase__branch_id=bid)
        ba  = bl.aggregate(
            ps  = Sum(_PROFIT,   filter=Q(purchase__doc_code='115')),
            pr  = Sum(_PROFIT,   filter=Q(purchase__doc_code='30')),
            disc= Sum(_DISCOUNT, filter=Q(purchase__doc_code='115')),
            qty = Sum('quantity',filter=Q(purchase__doc_code='115')),
            items=Count('item', distinct=True, filter=Q(purchase__doc_code='115')),
        )
        pft = float(ba['ps'] or 0) - float(ba['pr'] or 0)
        by_branch.append({
            'branch_id':          bid,
            'branch_name':        row['branch__name_ar'] or row['branch__name'],
            'revenue':            b_net,
            'sales_revenue':      s_rev,
            'returns_revenue':    r_rev,
            'transactions':       row['transactions'],
            'distinct_customers': row['distinct_cust'],
            'profit':             pft,
            'margin_pct':         _margin(pft, b_net),
            'discount':           float(ba['disc'] or 0),
            'total_qty':          float(ba['qty']  or 0),
            'distinct_items':     ba['items'] or 0,
        })

    # ── By day ───────────────────────────────────────────────────────────────
    by_day = []
    for row in (
        qs.annotate(day=TruncDate('invoice_date'))
          .values('day')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('day')
    ):
        if not row['day']:
            continue
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        b_net = s_rev - r_rev
        dl  = line_qs.filter(purchase__invoice_date__date=row['day'])
        da  = dl.aggregate(
            ps=Sum(_PROFIT, filter=Q(purchase__doc_code='115')),
            pr=Sum(_PROFIT, filter=Q(purchase__doc_code='30')),
        )
        pft = float(da['ps'] or 0) - float(da['pr'] or 0)
        by_day.append({
            'date':            row['day'].isoformat(),
            'revenue':         b_net,
            'sales_revenue':   s_rev,
            'returns_revenue': r_rev,
            'transactions':    row['transactions'],
            'profit':          pft,
            'margin_pct':      _margin(pft, b_net),
        })

    # ── By hour ──────────────────────────────────────────────────────────────
    by_hour = []
    for row in (
        qs.annotate(hr=ExtractHour('invoice_date'))
          .values('hr')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('hr')
    ):
        if row['hr'] is None:
            continue
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        by_hour.append({
            'hour':            row['hr'],
            'revenue':         s_rev - r_rev,
            'sales_revenue':   s_rev,
            'returns_revenue': r_rev,
            'transactions':    row['transactions'],
        })

    # ── By day of week ───────────────────────────────────────────────────────
    by_weekday = []
    for row in (
        qs.annotate(dow=ExtractWeekDay('invoice_date'))
          .values('dow')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('dow')
    ):
        d = row['dow']
        if d is None:
            continue
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        by_weekday.append({
            'day_code':        d,
            'day_label':       _DOW_LABELS.get(d, str(d)),
            'revenue':         s_rev - r_rev,
            'sales_revenue':   s_rev,
            'returns_revenue': r_rev,
            'transactions':    row['transactions'],
        })

    # ── By sales channel (uses denormalized sales_channel field) ─────────────
    by_channel = []
    for row in (
        qs.values('sales_channel')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              distinct_cust  = Count('customer', distinct=True),
              distinct_pics  = Count(
                  'softech_phcode', distinct=True,
                  filter=Q(softech_phcode__gt=''),
              ),
          )
          .order_by('-sales_amount')
    ):
        code  = row['sales_channel'] or ''
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        b_net = s_rev - r_rev
        cl  = line_qs.filter(purchase__sales_channel=row['sales_channel'])
        ca  = cl.aggregate(
            ps  = Sum(_PROFIT,   filter=Q(purchase__doc_code='115')),
            pr  = Sum(_PROFIT,   filter=Q(purchase__doc_code='30')),
            disc= Sum(_DISCOUNT, filter=Q(purchase__doc_code='115')),
        )
        pft = float(ca['ps'] or 0) - float(ca['pr'] or 0)
        by_channel.append({
            'channel_code':       code,
            'channel_label':      _channel_label(code),
            'revenue':            b_net,
            'sales_revenue':      s_rev,
            'returns_revenue':    r_rev,
            'transactions':       row['transactions'],
            'distinct_customers': row['distinct_cust'],
            'distinct_piccodes':  row['distinct_pics'],
            'profit':             pft,
            'margin_pct':         _margin(pft, b_net),
            'discount':           float(ca['disc'] or 0),
        })

    # ── By cashier / user ─────────────────────────────────────────────────────
    by_user = []
    for row in (
        qs.exclude(softech_user='')
          .values('softech_user')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              distinct_cust  = Count('customer', distinct=True),
              distinct_pics  = Count(
                  'softech_phcode', distinct=True,
                  filter=Q(softech_phcode__gt=''),
              ),
          )
          .order_by('-sales_amount')[:30]
    ):
        code  = row['softech_user']
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        u_net = s_rev - r_rev
        txns  = row['transactions'] or 0
        ul  = line_qs.filter(purchase__softech_user=code)
        ua  = ul.aggregate(
            ps   = Sum(_PROFIT,   filter=Q(purchase__doc_code='115')),
            pr   = Sum(_PROFIT,   filter=Q(purchase__doc_code='30')),
            disc = Sum(_DISCOUNT, filter=Q(purchase__doc_code='115')),
            qty  = Sum('quantity',filter=Q(purchase__doc_code='115')),
            items= Count('item', distinct=True, filter=Q(purchase__doc_code='115')),
            lines= Count('id',   filter=Q(purchase__doc_code='115')),
        )
        pft   = float(ua['ps']   or 0) - float(ua['pr'] or 0)
        disc  = float(ua['disc'] or 0)
        lines = ua['lines'] or 0
        by_user.append({
            'user_code':          code,
            'user_name':          _user_name(user_map, code),
            'revenue':            u_net,
            'sales_revenue':      s_rev,
            'returns_revenue':    r_rev,
            'transactions':       txns,
            'avg_basket':         round(u_net / txns, 2) if txns else 0.0,
            'profit':             pft,
            'margin_pct':         _margin(pft, u_net),
            'discount':           disc,
            'total_qty':          float(ua['qty'] or 0),
            'distinct_items':     ua['items'] or 0,
            'items_per_trx':      round(lines / txns, 2) if txns else 0.0,
            'distinct_customers': row['distinct_cust'],
            'distinct_piccodes':  row['distinct_pics'],
        })

    # ── By medicine type ─────────────────────────────────────────────────────
    by_medicine_type = []
    for row in (
        line_qs.filter(item__isnull=False)
        .values('item__medicine_type', 'item__medicine_type_name_ar', 'item__medicine_type_name')
        .annotate(
            revenue   = Sum('line_total', filter=Q(purchase__doc_code='115')),
            qty       = Sum('quantity',   filter=Q(purchase__doc_code='115')),
            profit_s  = Sum(_PROFIT,      filter=Q(purchase__doc_code='115')),
            profit_r  = Sum(_PROFIT,      filter=Q(purchase__doc_code='30')),
            discount  = Sum(_DISCOUNT,    filter=Q(purchase__doc_code='115')),
            trx_count = Count('purchase', distinct=True,
                              filter=Q(purchase__doc_code='115')),
            item_count= Count('item', distinct=True),
        )
        .order_by('-revenue')[:25]
    ):
        rev = float(row['revenue'] or 0)
        pft = float(row['profit_s'] or 0) - float(row['profit_r'] or 0)
        by_medicine_type.append({
            'type_code':   row['item__medicine_type'] or '',
            'type_label':  row['item__medicine_type_name_ar'] or row['item__medicine_type_name'] or 'غير محدد',
            'revenue':     rev,
            'qty':         float(row['qty'] or 0),
            'profit':      pft,
            'margin_pct':  _margin(pft, rev),
            'discount':    float(row['discount'] or 0),
            'trx_count':   row['trx_count'],
            'item_count':  row['item_count'],
        })

    # ── By item category ─────────────────────────────────────────────────────
    by_category = []
    for row in (
        line_qs.filter(item__category__isnull=False)
        .values('item__category__name_ar', 'item__category__name')
        .annotate(
            revenue  = Sum('line_total', filter=Q(purchase__doc_code='115')),
            qty      = Sum('quantity',   filter=Q(purchase__doc_code='115')),
            profit_s = Sum(_PROFIT,      filter=Q(purchase__doc_code='115')),
            profit_r = Sum(_PROFIT,      filter=Q(purchase__doc_code='30')),
        )
        .order_by('-revenue')[:15]
    ):
        rev = float(row['revenue'] or 0)
        pft = float(row['profit_s'] or 0) - float(row['profit_r'] or 0)
        by_category.append({
            'category_name': row['item__category__name_ar'] or row['item__category__name'],
            'revenue':       rev,
            'qty':           float(row['qty'] or 0),
            'profit':        pft,
            'margin_pct':    _margin(pft, rev),
        })

    # ── Top items ─────────────────────────────────────────────────────────────
    top_items = []
    for row in (
        line_qs.filter(item__isnull=False)
        .values('item__softech_id', 'item__name',
                'item__medicine_type_name_ar', 'item__medicine_type_name',
                'item__supplier_name', 'item__producer_name', 'item__family_name_ar')
        .annotate(
            revenue   = Sum('line_total', filter=Q(purchase__doc_code='115')),
            qty       = Sum('quantity',   filter=Q(purchase__doc_code='115')),
            profit_s  = Sum(_PROFIT,      filter=Q(purchase__doc_code='115')),
            profit_r  = Sum(_PROFIT,      filter=Q(purchase__doc_code='30')),
            discount  = Sum(_DISCOUNT,    filter=Q(purchase__doc_code='115')),
            trx_count = Count('purchase', distinct=True,
                              filter=Q(purchase__doc_code='115')),
        )
        .order_by('-revenue')[:30]
    ):
        rev = float(row['revenue'] or 0)
        pft = float(row['profit_s'] or 0) - float(row['profit_r'] or 0)
        top_items.append({
            'item_code':     row['item__softech_id'],
            'item_name':     row['item__name'],
            'medicine_type': row['item__medicine_type_name_ar'] or row['item__medicine_type_name'] or '',
            'supplier':      row['item__supplier_name'] or '',
            'producer':      row['item__producer_name'] or '',
            'family':        row['item__family_name_ar'] or '',
            'revenue':       rev,
            'qty':           float(row['qty'] or 0),
            'profit':        pft,
            'margin_pct':    _margin(pft, rev),
            'discount':      float(row['discount'] or 0),
            'trx_count':     row['trx_count'],
        })

    return Response({
        'summary': {
            'total_revenue':      net_rev,          # net = sales - returns
            'sales_revenue':      sales_rev,
            'returns_revenue':    returns_rev,
            'return_rate_pct':    return_rate,
            'total_transactions': total_transactions,
            'sales_count':        sales_cnt,
            'returns_count':      returns_cnt,
            'distinct_customers': distinct_customers,
            'distinct_piccodes':  distinct_piccodes,
            'total_profit':       total_profit,
            'total_cogs':         total_cogs,        # cost of goods sold = Σ(cost_price × qty)
            'profit_margin_pct':  profit_margin,
            'total_discount':     total_discount,
            'avg_basket':         avg_basket,
            'total_qty':          total_qty,
            'distinct_items':     distinct_items,
            'items_per_trx':      items_per_trx,
        },
        'by_branch':        by_branch,
        'by_day':           by_day,
        'by_hour':          by_hour,
        'by_weekday':       by_weekday,
        'by_channel':       by_channel,
        'by_user':          by_user,
        'by_medicine_type': by_medicine_type,
        'by_category':      by_category,
        'top_items':        top_items,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  2. CUSTOMER ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_analytics(request):
    """GET /api/analytics/customers/"""
    p  = request.query_params
    qs = _purchase_qs_filtered(p)

    now_date = timezone.localdate()
    d30  = now_date - datetime.timedelta(days=30)
    d90  = now_date - datetime.timedelta(days=90)

    total_customers = Customer.objects.count()
    active_30d = Customer.objects.filter(purchases__invoice_date__date__gte=d30).distinct().count()
    active_90d = Customer.objects.filter(purchases__invoice_date__date__gte=d90).distinct().count()
    new_30d    = Customer.objects.filter(created_at__date__gte=d30).count()

    net_rev, sales_rev, returns_rev, _, _ = _net_revenue_from_qs(qs)
    total_txn   = qs.count()
    unique_cu   = qs.aggregate(d=Count('customer', distinct=True))['d'] or 0
    unique_pics = (
        qs.exclude(softech_phcode='')
          .aggregate(d=Count('softech_phcode', distinct=True))['d'] or 0
    )

    avg_basket  = round(net_rev / total_txn, 2) if total_txn else 0.0
    avg_txns    = round(total_txn / unique_cu, 2) if unique_cu else 0.0
    repeat_cust = qs.values('customer').annotate(cnt=Count('id')).filter(cnt__gt=1).count()
    repeat_rate = round(repeat_cust / unique_cu * 100, 1) if unique_cu else 0.0

    # By channel — use denormalized sales_channel field
    by_channel = []
    for row in (
        qs.values('sales_channel')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              cust_count     = Count('customer', distinct=True),
              pic_count      = Count(
                  'softech_phcode', distinct=True,
                  filter=Q(softech_phcode__gt=''),
              ),
          )
          .order_by('-sales_amount')
    ):
        code  = row['sales_channel'] or ''
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        by_channel.append({
            'channel_code':      code,
            'channel_label':     _channel_label(code),
            'revenue':           s_rev - r_rev,
            'sales_revenue':     s_rev,
            'returns_revenue':   r_rev,
            'transactions':      row['transactions'],
            'cust_count':        row['cust_count'],
            'distinct_piccodes': row['pic_count'],
        })

    # Top customers
    top_customers = []
    for row in (
        qs.values('customer__id', 'customer__name', 'customer__phone',
                  'customer__softech_pic', 'sales_channel')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('-sales_amount')[:20]
    ):
        code  = row['sales_channel'] or ''
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        top_customers.append({
            'name':         row['customer__name'],
            'phone':        row['customer__phone'],
            'softech_pic':  row['customer__softech_pic'] or '',
            'channel':      _channel_label(code),
            'revenue':      s_rev - r_rev,
            'transactions': row['transactions'],
        })

    # Segmentation (last 90 days, unfiltered)
    last90 = PurchaseHistory.objects.exclude(doc_code='80').filter(
        invoice_date__date__gte=d90
    )
    seg = {'vip': 0, 'frequent': 0, 'regular': 0, 'inactive': total_customers - active_90d}
    for row in last90.values('customer').annotate(cnt=Count('id'), rev=Sum('total_amount')):
        if float(row['rev'] or 0) > 5000:
            seg['vip'] += 1
        elif row['cnt'] > 5:
            seg['frequent'] += 1
        else:
            seg['regular'] += 1

    return Response({
        'total_customers':               total_customers,
        'active_30d':                    active_30d,
        'active_90d':                    active_90d,
        'inactive':                      total_customers - active_90d,
        'new_30d':                       new_30d,
        'unique_piccodes':               unique_pics,
        'avg_basket_size':               avg_basket,
        'avg_transactions_per_customer': avg_txns,
        'repeat_rate':                   repeat_rate,
        'top_customers':                 top_customers,
        'by_channel':                    by_channel,
        'segmentation':                  seg,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  3. PERFORMANCE ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def performance_analytics(request):
    """GET /api/analytics/performance/"""
    p        = request.query_params
    qs       = _purchase_qs_filtered(p)
    line_qs  = _line_qs_for(qs, p)
    user_map = _build_user_map()

    # Summary
    net_rev, sales_rev, returns_rev, _, _ = _net_revenue_from_qs(qs)
    total_transactions = qs.count()
    distinct_customers = qs.aggregate(d=Count('customer', distinct=True))['d'] or 0
    distinct_piccodes  = (
        qs.filter(doc_code='115').exclude(softech_phcode='')
          .aggregate(d=Count('softech_phcode', distinct=True))['d'] or 0
    )
    la = line_qs.aggregate(
        ps = Sum(_PROFIT,   filter=Q(purchase__doc_code='115')),
        pr = Sum(_PROFIT,   filter=Q(purchase__doc_code='30')),
        ds = Sum(_DISCOUNT, filter=Q(purchase__doc_code='115')),
    )
    total_profit   = float(la['ps'] or 0) - float(la['pr'] or 0)
    total_discount = float(la['ds'] or 0)

    # Per-employee breakdown
    by_employee = []
    best = {'user_code': '', 'user_name': '', 'revenue': 0.0}

    for row in (
        qs.exclude(softech_user='')
          .values('softech_user')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              distinct_cust  = Count('customer', distinct=True),
              distinct_pics  = Count(
                  'softech_phcode', distinct=True,
                  filter=Q(softech_phcode__gt='', doc_code='115'),
              ),
          )
          .order_by('-sales_amount')
    ):
        code  = row['softech_user']
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        u_net = s_rev - r_rev
        txns  = row['transactions'] or 0

        ul = line_qs.filter(purchase__softech_user=code)
        ua = ul.aggregate(
            qty   = Sum('quantity',   filter=Q(purchase__doc_code='115')),
            ps    = Sum(_PROFIT,      filter=Q(purchase__doc_code='115')),
            pr    = Sum(_PROFIT,      filter=Q(purchase__doc_code='30')),
            disc  = Sum(_DISCOUNT,    filter=Q(purchase__doc_code='115')),
            items = Count('item', distinct=True, filter=Q(purchase__doc_code='115')),
            lines = Count('id',   filter=Q(purchase__doc_code='115')),
        )
        pft   = float(ua['ps']   or 0) - float(ua['pr'] or 0)
        disc  = float(ua['disc'] or 0)
        lines = ua['lines'] or 0

        by_employee.append({
            'user_code':          code,
            'user_name':          _user_name(user_map, code),
            'revenue':            u_net,
            'sales_revenue':      s_rev,
            'returns_revenue':    r_rev,
            'transactions':       txns,
            'avg_basket':         round(u_net / txns, 2) if txns else 0.0,
            'profit':             pft,
            'margin_pct':         _margin(pft, u_net),
            'discount':           disc,
            'items_sold':         float(ua['qty'] or 0),
            'distinct_items':     ua['items'] or 0,
            'items_per_trx':      round(lines / txns, 2) if txns else 0.0,
            'distinct_customers': row['distinct_cust'],
            'distinct_piccodes':  row['distinct_pics'],
        })
        if u_net > best['revenue']:
            best = {'user_code': code, 'user_name': _user_name(user_map, code), 'revenue': u_net}

    # By branch
    by_branch = []
    for row in (
        qs.values('branch__id', 'branch__name', 'branch__name_ar')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
              distinct_users = Count('softech_user', distinct=True),
          )
          .order_by('-sales_amount')
    ):
        bid   = row['branch__id']
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        b_net = s_rev - r_rev
        bl  = line_qs.filter(purchase__branch_id=bid)
        ba  = bl.aggregate(
            ps=Sum(_PROFIT, filter=Q(purchase__doc_code='115')),
            pr=Sum(_PROFIT, filter=Q(purchase__doc_code='30')),
        )
        pft = float(ba['ps'] or 0) - float(ba['pr'] or 0)
        by_branch.append({
            'branch_id':      bid,
            'branch_name':    row['branch__name_ar'] or row['branch__name'],
            'revenue':        b_net,
            'sales_revenue':  s_rev,
            'returns_revenue': r_rev,
            'transactions':   row['transactions'],
            'distinct_users': row['distinct_users'],
            'profit':         pft,
            'margin_pct':     _margin(pft, b_net),
        })

    # By day-of-week (performance heatmap)
    by_weekday = []
    for row in (
        qs.annotate(dow=ExtractWeekDay('invoice_date'))
          .values('dow')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('dow')
    ):
        d = row['dow']
        if d is None:
            continue
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        by_weekday.append({
            'day_code':        d,
            'day_label':       _DOW_LABELS.get(d, str(d)),
            'revenue':         s_rev - r_rev,
            'transactions':    row['transactions'],
        })

    # By hour
    by_hour = []
    for row in (
        qs.annotate(hr=ExtractHour('invoice_date'))
          .values('hr')
          .annotate(
              sales_amount   = Sum('total_amount', filter=Q(doc_code='115')),
              returns_amount = Sum('total_amount', filter=Q(doc_code='30')),
              transactions   = Count('id'),
          )
          .order_by('hr')
    ):
        if row['hr'] is None:
            continue
        s_rev = float(row['sales_amount'] or 0)
        r_rev = float(row['returns_amount'] or 0)
        by_hour.append({
            'hour':         row['hr'],
            'revenue':      s_rev - r_rev,
            'transactions': row['transactions'],
        })

    return Response({
        'summary': {
            'total_revenue':      net_rev,
            'sales_revenue':      sales_rev,
            'returns_revenue':    returns_rev,
            'total_transactions': total_transactions,
            'total_profit':       total_profit,
            'profit_margin_pct':  _margin(total_profit, net_rev),
            'total_discount':     total_discount,
            'distinct_customers': distinct_customers,
            'distinct_piccodes':  distinct_piccodes,
        },
        'by_employee': by_employee,
        'by_branch':   by_branch,
        'by_weekday':  by_weekday,
        'by_hour':     by_hour,
        'best_performer': best,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  4. INVENTORY ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inventory_analytics(request):
    """
    GET /api/analytics/inventory/
    Uses ItemDemandMetrics from the latest successful demand engine run.
    Returns immediately with empty data if no run exists.
    """
    # Lazy imports — keep purchasing models off module-level to avoid import
    # errors breaking ALL analytics endpoints if purchasing is not yet set up.
    try:
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
    except ImportError as exc:
        logger.error(f"[inventory_analytics] Cannot import purchasing models: {exc}")
        return Response({'error': 'وحدة المشتريات غير متاحة'}, status=503)

    p = request.query_params

    empty = {
        'total_items': 0, 'shortage_items': 0, 'overstock_items': 0,
        'dead_stock_items': 0, 'shortage_value': 0.0, 'overstock_value': 0.0,
        'top_shortages': [], 'top_overstock': [], 'by_branch': [],
        'by_medicine_type': [], 'run_date': None,
    }

    try:
        latest_run = (
            DemandCalculationRun.objects
            .filter(status='success')
            .order_by('-started_at')
            .first()
        )
        if not latest_run:
            return Response(empty)

        # Base queryset — do NOT select_related here to avoid loading a huge
        # join for the entire metrics table when we only need aggregates.
        mqs = ItemDemandMetrics.objects.filter(run=latest_run)

        # ── Filters ─────────────────────────────────────────────────────────
        branches  = _parse_list(p.get('branches'))
        med_types = _parse_list(p.get('medicine_types'))
        abc_class = _parse_list(p.get('abc_class'))

        if branches:
            mqs = mqs.filter(branch_id__in=branches)
        if med_types:
            mqs = mqs.filter(item__medicine_type__in=med_types)
        if abc_class:
            mqs = mqs.filter(abc_class__in=abc_class)

        # ── Item operational filters (new fields) ────────────────────────────
        insurance_types = _parse_list(p.get('insurance_types'))
        if insurance_types:
            mqs = mqs.filter(item__insurance_type__in=insurance_types)

        store_classifs = _parse_list(p.get('store_classifs'))
        if store_classifs:
            mqs = mqs.filter(item__store_classif__in=store_classifs)

        nosale_classifs = _parse_list(p.get('nosale_classifs'))
        if nosale_classifs:
            mqs = mqs.filter(item__nosale_classif__in=nosale_classifs)

        if p.get('is_fast_moving') == '1':
            mqs = mqs.filter(item__is_fast_moving=True)
        if p.get('has_points') == '1':
            mqs = mqs.filter(item__has_points=True)
        if p.get('item_level') not in (None, ''):
            try:
                mqs = mqs.filter(item__item_level=int(p['item_level']))
            except (ValueError, TypeError):
                pass

        branch_trans = p.get('branch_trans')
        if branch_trans not in (None, ''):
            mqs = mqs.filter(item__branch_trans=branch_trans)
        supplier_trans = p.get('supplier_trans')
        if supplier_trans not in (None, ''):
            mqs = mqs.filter(item__supplier_trans=supplier_trans)
        customer_trans = p.get('customer_trans')
        if customer_trans not in (None, ''):
            mqs = mqs.filter(item__customer_trans=customer_trans)

        shortage_qs   = mqs.filter(gap__gt=0)
        overstock_qs  = mqs.filter(gap__lt=0)
        dead_stock_qs = mqs.filter(monthly_avg__lte=0, current_stock__gt=0)

        # ── Gap values (use explicit output_field to avoid type inference errors)
        _DECIMAL = DecimalField(max_digits=18, decimal_places=3)
        _gap_x_price = ExpressionWrapper(F('gap') * F('pack_price'), output_field=_DECIMAL)

        shortage_value  = float(shortage_qs.aggregate(v=Sum(_gap_x_price))['v'] or 0)
        overstock_value = abs(float(overstock_qs.aggregate(v=Sum(_gap_x_price))['v'] or 0))

        # ── Top shortages (with item + branch names) ─────────────────────────
        top_shortages = []
        for m in (
            shortage_qs
            .select_related('item', 'branch')
            .order_by('-priority')[:30]
        ):
            top_shortages.append({
                'item_name':       m.item.name,
                'item_code':       m.item.softech_id,
                'medicine_type':   m.item.medicine_type_name_ar or m.item.medicine_type_name or '',
                'supplier':        m.item.supplier_name or '',
                'producer':        m.item.producer_name or '',
                'family':          m.item.family_name_ar or m.item.family_name or '',
                'branch':          m.branch.name_ar or m.branch.name,
                'gap':             float(m.gap),
                'priority':        float(m.priority),
                'monthly_avg':     float(m.monthly_avg),
                'coverage_months': float(m.coverage_months or 0),
                'current_stock':   float(m.current_stock),
                'safety_stock':    float(m.safety_stock),
                'abc_class':       m.abc_class,
            })

        # ── Top overstock ────────────────────────────────────────────────────
        top_overstock = []
        for m in (
            overstock_qs
            .select_related('item', 'branch')
            .order_by('gap')[:30]
        ):
            surplus = abs(float(m.gap))
            top_overstock.append({
                'item_name':     m.item.name,
                'item_code':     m.item.softech_id,
                'medicine_type': m.item.medicine_type_name_ar or m.item.medicine_type_name or '',
                'supplier':      m.item.supplier_name or '',
                'producer':      m.item.producer_name or '',
                'family':        m.item.family_name_ar or m.item.family_name or '',
                'branch':        m.branch.name_ar or m.branch.name,
                'surplus':       surplus,
                'value':         round(surplus * float(m.pack_price), 2),
                'monthly_avg':   float(m.monthly_avg),
                'abc_class':     m.abc_class,
            })

        # ── By branch — single annotate query, no N+1 loop ──────────────────
        by_branch_raw = (
            mqs
            .values('branch__id', 'branch__name', 'branch__name_ar')
            .annotate(
                shortage_count  = Count('id', filter=Q(gap__gt=0)),
                overstock_count = Count('id', filter=Q(gap__lt=0)),
                dead_count      = Count('id', filter=Q(monthly_avg__lte=0, current_stock__gt=0)),
                shortage_value  = Sum(
                    ExpressionWrapper(F('gap') * F('pack_price'), output_field=_DECIMAL),
                    filter=Q(gap__gt=0),
                ),
            )
            .order_by('-shortage_count')
        )
        by_branch = [
            {
                'branch':          row['branch__name_ar'] or row['branch__name'],
                'shortage_count':  row['shortage_count'],
                'overstock_count': row['overstock_count'],
                'dead_count':      row['dead_count'],
                'shortage_value':  float(row['shortage_value'] or 0),
            }
            for row in by_branch_raw
        ]

        # ── By medicine type ─────────────────────────────────────────────────
        by_medicine_type = []
        for row in (
            mqs.exclude(item__medicine_type='')
            .values('item__medicine_type', 'item__medicine_type_name_ar', 'item__medicine_type_name')
            .annotate(
                item_count      = Count('item', distinct=True),
                shortage_count  = Count('id', filter=Q(gap__gt=0)),
                overstock_count = Count('id', filter=Q(gap__lt=0)),
                shortage_value  = Sum(
                    ExpressionWrapper(F('gap') * F('pack_price'), output_field=_DECIMAL),
                    filter=Q(gap__gt=0),
                ),
            )
            .order_by('-shortage_count')[:20]
        ):
            by_medicine_type.append({
                'type_code':       row['item__medicine_type'],
                'type_label':      (
                    row['item__medicine_type_name_ar']
                    or row['item__medicine_type_name']
                    or row['item__medicine_type']
                ),
                'item_count':      row['item_count'],
                'shortage_count':  row['shortage_count'],
                'overstock_count': row['overstock_count'],
                'shortage_value':  float(row['shortage_value'] or 0),
            })

        return Response({
            'run_date':         latest_run.started_at.date().isoformat(),
            'total_items':      mqs.count(),
            'shortage_items':   shortage_qs.count(),
            'overstock_items':  overstock_qs.count(),
            'dead_stock_items': dead_stock_qs.count(),
            'shortage_value':   shortage_value,
            'overstock_value':  overstock_value,
            'top_shortages':    top_shortages,
            'top_overstock':    top_overstock,
            'by_branch':        by_branch,
            'by_medicine_type': by_medicine_type,
        })

    except Exception as exc:
        logger.error(f"[inventory_analytics] Unexpected error: {exc}", exc_info=True)
        return Response(
            {'error': f'خطأ في تحليل المخزون: {str(exc)}'},
            status=500,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  5. CUSTOMER SEARCH  (typeahead for the analytics customer filter)
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_search(request):
    """
    GET /api/analytics/customer-search/?q=term&limit=20

    Full-text search across name, phone, softech_pic (PIC code).
    Returns a short list of matching customers for the analytics customer filter.
    The 'id' returned is the Django Customer PK — pass it as customer_ids param
    to the analytics endpoints.
    """
    q     = (request.query_params.get('q') or '').strip()
    limit = min(_safe_int(request.query_params.get('limit'), 20), 50)

    if not q or len(q) < 2:
        return Response([])

    qs = (
        Customer.objects
        .filter(
            Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(phone_alt__icontains=q)
            | Q(softech_pic__icontains=q)
            | Q(softech_id__icontains=q)
        )
        .only(
            'id', 'name', 'phone', 'softech_pic',
            'softech_ptclassifcode', 'person_classif_label',
        )
        .order_by('name')[:limit]
    )

    results = []
    for c in qs:
        results.append({
            'id':            c.id,
            'name':          c.name,
            'phone':         c.phone,
            'softech_pic':   c.softech_pic or '',
            'channel_label': (
                c.person_classif_label
                or _channel_label(c.softech_ptclassifcode)
            ),
        })

    return Response(results)


# ═══════════════════════════════════════════════════════════════════════════════
#  6. CUSTOMER CHURN DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_churn(request):
    """
    GET /api/analytics/churn/

    Identifies customers who have gone silent based on their last purchase date.
    Uses current date (no date filter) because churn is about recency relative to TODAY.

    Optional params:
        branches      — comma-sep Branch IDs (filter to customers of those branches)
        channels      — comma-sep sales_channel values
        min_purchases — minimum historic purchase count to be included (default: 1)
    """
    p         = request.query_params
    today     = timezone.localdate()

    # Sub-query: last purchase date per customer (sales only, doc_code=115)
    from django.db.models import Max, Subquery, OuterRef

    # Build base customer queryset for last-purchase annotation
    ph_base = (
        PurchaseHistory.objects
        .filter(doc_code='115')
        .exclude(doc_code='80')
    )

    # Optional branch / channel filters
    branch_ids = _parse_list(p.get('branches'))
    if branch_ids:
        try:
            ph_base = ph_base.filter(branch_id__in=[int(b) for b in branch_ids])
        except (ValueError, TypeError):
            pass

    channels = _parse_list(p.get('channels'))
    if channels:
        ph_base = ph_base.filter(sales_channel__in=channels)

    min_pur = max(1, _safe_int(p.get('min_purchases'), 1))

    # Per-customer aggregation: last_purchase_date, count, total spend
    customer_stats = (
        ph_base
        .values('customer_id', 'customer__name', 'customer__phone',
                'customer__softech_pic', 'sales_channel')
        .annotate(
            last_purchase   = Max('invoice_date__date'),
            purchase_count  = Count('id'),
            total_spend     = Sum('total_amount'),
        )
        .filter(purchase_count__gte=min_pur)
        .order_by('last_purchase')
    )

    TIERS = [
        (30,  60,  '30-59 يوم'),
        (60,  90,  '60-89 يوم'),
        (90,  180, '90-179 يوم'),
        (180, 365, '180-364 يوم'),
        (365, None,'365+ يوم'),
    ]

    by_tier       = []
    top_churned   = []
    total_at_risk = 0
    revenue_at_risk = 0.0

    all_silent = []
    for row in customer_stats:
        lp = row['last_purchase']
        if lp is None:
            continue
        days_silent = (today - lp).days
        if days_silent < 30:
            continue
        spend = float(row['total_spend'] or 0)
        avg_monthly = round(spend / max(row['purchase_count'], 1), 2)
        all_silent.append({
            'customer_id':       row['customer_id'],
            'name':              row['customer__name'],
            'phone':             row['customer__phone'] or '',
            'softech_pic':       row['customer__softech_pic'] or '',
            'channel':           _channel_label(row['sales_channel'] or ''),
            'last_purchase':     lp.isoformat(),
            'days_silent':       days_silent,
            'purchase_count':    row['purchase_count'],
            'avg_monthly_spend': avg_monthly,
            'estimated_annual_loss': round(avg_monthly * 12, 2),
        })
        total_at_risk += 1
        revenue_at_risk += avg_monthly * 12

    # Build tier buckets
    for t_from, t_to, label in TIERS:
        bucket = [r for r in all_silent
                  if r['days_silent'] >= t_from and (t_to is None or r['days_silent'] < t_to)]
        by_tier.append({
            'label':         label,
            'days_from':     t_from,
            'days_to':       t_to,
            'count':         len(bucket),
            'annual_loss':   round(sum(r['estimated_annual_loss'] for r in bucket), 2),
        })

    # Top 20 by estimated annual loss
    top_churned = sorted(all_silent, key=lambda r: -r['estimated_annual_loss'])[:20]

    return Response({
        'total_at_risk':     total_at_risk,
        'revenue_at_risk':   round(revenue_at_risk, 2),
        'by_tier':           by_tier,
        'top_churned':       top_churned,
        'as_of_date':        today.isoformat(),
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  7. BRANCH CONTRIBUTION MARGIN
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_contribution(request):
    """
    GET /api/analytics/branch-contribution/

    True branch-level contribution margin:
        Contribution = Gross Revenue − COGS − Branch Expenses

    Params: date_from, date_to (default: last 30 days)
    """
    try:
        from apps.finance.models import ExpenseRecord
    except ImportError:
        ExpenseRecord = None

    p         = request.query_params
    today     = timezone.localdate()
    date_from = _parse_date(p.get('date_from')) or (today - datetime.timedelta(days=30))
    date_to   = _parse_date(p.get('date_to'))   or today

    # Revenue + COGS from PurchaseHistory × PurchaseHistoryLine
    sales_ph = (
        PurchaseHistory.objects
        .filter(invoice_date__date__range=(date_from, date_to))
        .exclude(doc_code='80')
        .select_related('branch')
    )

    # Per-branch revenue + COGS aggregation from lines
    from apps.customers.models import PurchaseHistoryLine as PHL

    lines_qs = (
        PHL.objects
        .filter(
            purchase__invoice_date__date__range=(date_from, date_to),
        )
        .exclude(purchase__doc_code='80')
        .select_related('purchase__branch')
    )

    branch_metrics = {}

    for row in (
        lines_qs
        .values('purchase__branch_id', 'purchase__doc_code')
        .annotate(
            revenue_sum  = Sum('line_total'),
            cogs_sum     = Sum(
                ExpressionWrapper(F('quantity') * F('cost_at_sale'), output_field=DecimalField())
            ),
            qty_sum      = Sum('quantity'),
            txn_count    = Count('purchase_id', distinct=True),
            item_count   = Count('item_id', distinct=True),
        )
    ):
        bid     = row['purchase__branch_id']
        dc      = row['purchase__doc_code']
        rev     = float(row['revenue_sum'] or 0)
        cogs    = float(row['cogs_sum']    or 0)
        if bid not in branch_metrics:
            branch_metrics[bid] = {
                'gross_revenue': 0.0,
                'returns':       0.0,
                'cogs':          0.0,
                'transactions':  0,
                'items':         0,
            }
        if dc == '115':
            branch_metrics[bid]['gross_revenue'] += rev
            branch_metrics[bid]['cogs']          += cogs
            branch_metrics[bid]['transactions']  += row['txn_count']
            branch_metrics[bid]['items']         += row['item_count']
        elif dc == '30':
            branch_metrics[bid]['returns']       += rev
            branch_metrics[bid]['cogs']          -= cogs  # return reverses COGS

    # Expenses per branch in the period
    expense_by_branch = {}
    if ExpenseRecord is not None:
        for row in (
            ExpenseRecord.objects
            .filter(expense_date__range=(date_from, date_to))
            .values('branch_id')
            .annotate(total=Sum('amount'))
        ):
            if row['branch_id']:
                expense_by_branch[row['branch_id']] = float(row['total'] or 0)

    branches = {b.id: b for b in Branch.objects.filter(is_active=True)}
    result   = []

    for branch in Branch.objects.filter(is_active=True).order_by('name'):
        m        = branch_metrics.get(branch.id, {})
        gross    = m.get('gross_revenue', 0.0)
        ret      = m.get('returns', 0.0)
        cogs     = m.get('cogs', 0.0)
        net_rev  = gross - ret
        gp       = net_rev - cogs
        expenses = expense_by_branch.get(branch.id, 0.0)
        contrib  = gp - expenses
        result.append({
            'branch_id':            branch.id,
            'branch_name':          branch.name_ar or branch.name,
            'gross_revenue':        round(gross, 2),
            'returns_value':        round(ret, 2),
            'net_revenue':          round(net_rev, 2),
            'cogs':                 round(cogs, 2),
            'gross_margin':         round(gp, 2),
            'gross_margin_pct':     round(gp / net_rev * 100, 1) if net_rev else 0.0,
            'branch_expenses':      round(expenses, 2),
            'contribution_margin':  round(contrib, 2),
            'contribution_pct':     round(contrib / net_rev * 100, 1) if net_rev else 0.0,
            'transactions':         m.get('transactions', 0),
            'distinct_items':       m.get('items', 0),
        })

    result.sort(key=lambda r: -r['net_revenue'])

    return Response({
        'date_from':   date_from.isoformat(),
        'date_to':     date_to.isoformat(),
        'branches':    result,
        'totals': {
            'net_revenue':         round(sum(r['net_revenue'] for r in result), 2),
            'gross_margin':        round(sum(r['gross_margin'] for r in result), 2),
            'branch_expenses':     round(sum(r['branch_expenses'] for r in result), 2),
            'contribution_margin': round(sum(r['contribution_margin'] for r in result), 2),
        },
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  8. INVENTORY INVESTMENT (Capital Tied + Liquidation Candidates)
# ═══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inventory_investment(request):
    """
    GET /api/analytics/inventory-investment/

    Computes capital tied in inventory using the latest demand engine run.
        stock_value   = current_stock × pack_price
        surplus_value = max(0, current_stock − safety_stock) × pack_price
        gap_value     = max(0, gap) × pack_price

    Liquidation candidates: items where surplus_stock > 0 AND coverage_months > threshold.

    Optional params:
        coverage_threshold  — months above which item is a liquidation candidate (default: 6)
        abc_class           — filter to specific ABC class(es)
    """
    try:
        from apps.purchasing.models import ItemDemandMetrics, DemandCalculationRun
    except ImportError:
        return Response({'error': 'Purchasing module not available'}, status=503)

    p = request.query_params

    # Latest successful demand run
    latest_run = (
        DemandCalculationRun.objects
        .filter(status='success')
        .order_by('-started_at')
        .first()
    )
    if not latest_run:
        return Response({
            'error':           'no_run',
            'message':         'لم يتم تشغيل محرك الطلب بعد',
            'total_capital':   0,
            'surplus_capital': 0,
            'by_abc':          [],
            'by_branch':       [],
            'liquidation':     [],
        })

    coverage_threshold = max(1, _safe_int(p.get('coverage_threshold'), 6))
    abc_filter         = _parse_list(p.get('abc_class'))

    mqs = ItemDemandMetrics.objects.filter(demand_run=latest_run)
    if abc_filter:
        mqs = mqs.filter(abc_class__in=abc_filter)

    # ── Per-ABC aggregation ──────────────────────────────────────────────────
    from django.db.models import FloatField as FF
    from django.db.models.functions import Greatest

    by_abc_raw = (
        mqs
        .values('abc_class')
        .annotate(
            item_count    = Count('item_id', distinct=True),
            total_stock   = Sum(ExpressionWrapper(F('current_stock') * F('pack_price'),
                                                  output_field=DecimalField())),
            total_surplus = Sum(ExpressionWrapper(
                Greatest(F('current_stock') - F('safety_stock'), 0) * F('pack_price'),
                output_field=DecimalField()
            )),
            total_gap_val = Sum(ExpressionWrapper(
                Greatest(F('gap'), 0) * F('pack_price'),
                output_field=DecimalField()
            )),
        )
        .order_by('abc_class')
    )

    by_abc = []
    for row in by_abc_raw:
        by_abc.append({
            'abc_class':      row['abc_class'],
            'item_count':     row['item_count'],
            'stock_value':    round(float(row['total_stock']   or 0), 2),
            'surplus_value':  round(float(row['total_surplus'] or 0), 2),
            'gap_value':      round(float(row['total_gap_val'] or 0), 2),
        })

    # ── Per-branch aggregation ───────────────────────────────────────────────
    by_branch_raw = (
        mqs
        .values('branch_id', 'branch__name_ar', 'branch__name')
        .annotate(
            item_count    = Count('item_id', distinct=True),
            shortage_count = Count('id', filter=Q(gap__gt=0)),
            total_stock   = Sum(ExpressionWrapper(F('current_stock') * F('pack_price'),
                                                  output_field=DecimalField())),
            total_surplus = Sum(ExpressionWrapper(
                Greatest(F('current_stock') - F('safety_stock'), 0) * F('pack_price'),
                output_field=DecimalField()
            )),
        )
        .order_by('-total_stock')
    )

    by_branch = []
    for row in by_branch_raw:
        by_branch.append({
            'branch_id':      row['branch_id'],
            'branch_name':    row['branch__name_ar'] or row['branch__name'],
            'item_count':     row['item_count'],
            'shortage_count': row['shortage_count'],
            'stock_value':    round(float(row['total_stock']   or 0), 2),
            'surplus_value':  round(float(row['total_surplus'] or 0), 2),
        })

    # ── Liquidation candidates ───────────────────────────────────────────────
    liq_qs = (
        mqs
        .filter(current_stock__gt=F('safety_stock'))
        .filter(coverage_months__gt=coverage_threshold)
        .select_related('item', 'branch')
        .order_by('-coverage_months')[:50]
    )

    liquidation = []
    for m in liq_qs:
        surplus_stock = max(0.0, float(m.current_stock) - float(m.safety_stock))
        surplus_val   = round(surplus_stock * float(m.pack_price), 2)
        liquidation.append({
            'item_id':       m.item_id,
            'item_name':     m.item.name if m.item else '',
            'item_code':     m.item.softech_id if m.item else '',
            'branch':        m.branch.name_ar or m.branch.name if m.branch else '',
            'abc_class':     m.abc_class,
            'current_stock': float(m.current_stock),
            'safety_stock':  float(m.safety_stock),
            'surplus_stock': round(surplus_stock, 2),
            'surplus_value': surplus_val,
            'coverage_months': float(m.coverage_months or 0),
            'pack_price':    float(m.pack_price),
        })

    total_capital   = sum(r['stock_value']   for r in by_abc)
    surplus_capital = sum(r['surplus_value'] for r in by_abc)

    return Response({
        'run_date':           latest_run.calc_date.isoformat() if latest_run.calc_date else None,
        'coverage_threshold': coverage_threshold,
        'total_capital':      round(total_capital, 2),
        'surplus_capital':    round(surplus_capital, 2),
        'surplus_pct':        round(surplus_capital / total_capital * 100, 1) if total_capital else 0.0,
        'by_abc':             by_abc,
        'by_branch':          by_branch,
        'liquidation':        liquidation,
    })
