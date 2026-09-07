from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models
from .models import Category, Item, ItemStock, EXCLUDED_STORE_CODES
from .serializers import CategorySerializer, ItemSerializer, ItemStockSerializer, ItemSearchSerializer

# ── Static filter option lists (reused by both ItemViewSet and purchasing.filter_options) ──

INSURANCE_TYPE_OPTIONS = [
    {'code': '0', 'name': 'Not covered',  'name_ar': 'غير خاضع للتأمين'},
    {'code': '1', 'name': 'Talbia',       'name_ar': 'طلبية'},
    {'code': '2', 'name': 'TPA',          'name_ar': 'TPA'},
    {'code': '3', 'name': 'Takaful',      'name_ar': 'تكافل'},
    {'code': '4', 'name': 'Other',        'name_ar': 'أخرى (غير محدد)'},
]

NOSALE_CLASSIF_OPTIONS = [
    {'code': '10', 'name': 'Normal — no restriction',  'name_ar': 'طبيعي (بدون قيد)'},
    {'code': '20', 'name': 'Restriction #2',           'name_ar': 'قيد #2'},
    {'code': '30', 'name': 'Restriction #3',           'name_ar': 'قيد #3'},
    {'code': '31', 'name': 'Restriction #4',           'name_ar': 'قيد #4'},
]

TRANS_OPTIONS = [
    {'code': '0', 'name': 'Full (dispatch + return)', 'name_ar': 'كامل (صرف + ارتجاع)'},
    {'code': '1', 'name': 'Dispatch / sell / buy only', 'name_ar': 'صرف / بيع / شراء فقط'},
    {'code': '2', 'name': 'Return only',               'name_ar': 'ارتجاع فقط'},
    {'code': '3', 'name': 'Fully blocked',             'name_ar': 'إيقاف كامل'},
]

ITEM_LEVEL_OPTIONS = [
    {'code': '0', 'name': 'Standard', 'name_ar': 'قياسي'},
    {'code': '1', 'name': 'Special',  'name_ar': 'خاص'},
]


def apply_item_operational_filters(qs, params):
    """
    Apply operational / channel item-level filters from a query-params dict.
    Works on any QuerySet whose model IS catalog.Item (uses direct field lookups,
    not item__ FK prefix — for FK-prefixed version see purchasing._apply_item_filters).

    Supported params:
      is_fast_moving=1        insurance_type=<code>   item_level=<0|1>
      has_points=1            branch_trans=<code>     supplier_trans=<code>
      customer_trans=<code>   nosale_classif=<code>   store_classif=<code>
      is_stockable=1|0        requires_fridge=1       medicine_type=<code>
      category=<int>          supplier_code=<str>     family_code=<str>
      producer_code=<str>
      pack_price_min=<float>  pack_price_max=<float>
      unit_price_min=<float>  unit_price_max=<float>
      variant_group=<int>     (filters to items belonging to the given variant group)
    """
    if params.get('is_fast_moving') == '1':
        qs = qs.filter(is_fast_moving=True)
    if params.get('has_points') == '1':
        qs = qs.filter(has_points=True)
    if params.get('requires_fridge') == '1':
        qs = qs.filter(requires_fridge=True)

    insurance_type = params.get('insurance_type')
    if insurance_type not in (None, ''):
        qs = qs.filter(insurance_type=insurance_type)

    item_level = params.get('item_level')
    if item_level not in (None, ''):
        try:
            qs = qs.filter(item_level=int(item_level))
        except (ValueError, TypeError):
            pass

    branch_trans = params.get('branch_trans')
    if branch_trans not in (None, ''):
        qs = qs.filter(branch_trans=branch_trans)

    supplier_trans = params.get('supplier_trans')
    if supplier_trans not in (None, ''):
        qs = qs.filter(supplier_trans=supplier_trans)

    customer_trans = params.get('customer_trans')
    if customer_trans not in (None, ''):
        qs = qs.filter(customer_trans=customer_trans)

    nosale_classif = params.get('nosale_classif')
    if nosale_classif not in (None, ''):
        qs = qs.filter(nosale_classif=nosale_classif)

    store_classif = params.get('store_classif')
    if store_classif not in (None, ''):
        qs = qs.filter(store_classif=store_classif)

    is_stockable = params.get('is_stockable')
    if is_stockable == '1':
        qs = qs.filter(is_stockable=True)
    elif is_stockable == '0':
        qs = qs.filter(is_stockable=False)

    medicine_type = params.get('medicine_type')
    if medicine_type not in (None, ''):
        qs = qs.filter(medicine_type=medicine_type)

    category = params.get('category')
    if category not in (None, ''):
        try:
            qs = qs.filter(category_id=int(category))
        except (ValueError, TypeError):
            pass

    supplier_code = params.get('supplier_code')
    if supplier_code not in (None, ''):
        qs = qs.filter(supplier_code=supplier_code)

    family_code = params.get('family_code')
    if family_code not in (None, ''):
        qs = qs.filter(family_code=family_code)

    producer_code = params.get('producer_code')
    if producer_code not in (None, ''):
        qs = qs.filter(producer_code=producer_code)

    # Price range filters
    pack_price_min = params.get('pack_price_min')
    if pack_price_min not in (None, ''):
        try:
            qs = qs.filter(pack_price__gte=float(pack_price_min))
        except (ValueError, TypeError):
            pass

    pack_price_max = params.get('pack_price_max')
    if pack_price_max not in (None, ''):
        try:
            qs = qs.filter(pack_price__lte=float(pack_price_max))
        except (ValueError, TypeError):
            pass

    unit_price_min = params.get('unit_price_min')
    if unit_price_min not in (None, ''):
        try:
            qs = qs.filter(unit_price__gte=float(unit_price_min))
        except (ValueError, TypeError):
            pass

    unit_price_max = params.get('unit_price_max')
    if unit_price_max not in (None, ''):
        try:
            qs = qs.filter(unit_price__lte=float(unit_price_max))
        except (ValueError, TypeError):
            pass

    variant_group = params.get('variant_group')
    if variant_group not in (None, ''):
        try:
            from .models import VariantMember
            item_ids = VariantMember.objects.filter(
                group_id=int(variant_group)
            ).values_list('item_id', flat=True)
            qs = qs.filter(id__in=item_ids)
        except (ValueError, TypeError):
            pass

    # Wildcard name search — used by advanced search modal when user types '*'.
    # Converts SOFTECH-style wildcards (* = any characters) to PostgreSQL iregex.
    # Examples:  urosolv*  →  ^urosolv.*   (prefix match, case-insensitive)
    #            *cillin   →  .*cillin$     (suffix match)
    #            amox*500  →  ^amox.*500$   (middle wildcard)
    # When no '*', falls back to plain icontains on name + name_scientific.
    name_filter = params.get('name')
    if name_filter not in (None, ''):
        import re as _re
        name_q = name_filter.strip()
        if '*' in name_q:
            # Build regex: escape special chars first, then restore * → .*
            # Add ^ anchor only if pattern doesn't start with '*' (prefix search)
            # Add $ anchor only if pattern doesn't end with '*' (suffix search)
            escaped = _re.escape(name_q).replace(r'\*', '.*')
            if not name_q.startswith('*'):
                escaped = '^' + escaped
            if not name_q.endswith('*'):
                escaped = escaped + '$'
            qs = qs.filter(
                models.Q(name__iregex=escaped) |
                models.Q(name_scientific__iregex=escaped)
            )
        else:
            qs = qs.filter(
                models.Q(name__icontains=name_q) |
                models.Q(name_scientific__icontains=name_q)
            )

    return qs


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CategorySerializer
    queryset = Category.objects.all().order_by('name')


class ItemViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'requires_fridge', 'medicine_type',
                        'insurance_type', 'item_level', 'is_fast_moving',
                        'has_points', 'is_stockable',
                        'branch_trans', 'supplier_trans', 'customer_trans',
                        'nosale_classif', 'store_classif']
    # barcodes__barcode searches the ItemBarcode table (multiple barcodes per item,
    # including EAN-13 / GS1 barcodes scanned with physical barcode readers).
    search_fields = ['name', 'name_scientific', 'barcode', 'softech_id', 'barcodes__barcode']
    ordering_fields = [
        'name', 'softech_id', 'pack_price', 'unit_price', 'is_fast_moving',
        'name_scientific', 'category__name', 'total_stock',
    ]
    ordering = ['name']

    def get_queryset(self):
        from django.db.models import Sum, Value, DecimalField
        from django.db.models.functions import Coalesce
        qs = Item.objects.filter(is_active=True).prefetch_related(
            'stock_levels__branch', 'category', 'barcodes'
        ).distinct()  # distinct() required: joining ItemBarcode can produce duplicate rows
        p = self.request.query_params

        # Annotate total_stock when ordering by it, or when filtering by in_stock
        ordering_param = p.get('ordering', '')
        needs_stock_annotation = (
            p.get('in_stock') == 'true'
            or 'total_stock' in ordering_param
        )
        if needs_stock_annotation:
            qs = qs.annotate(
                total_stock=Coalesce(
                    Sum(
                        'stock_levels__quantity_on_hand',
                        filter=~models.Q(stock_levels__softech_store_code__in=EXCLUDED_STORE_CODES),
                    ),
                    Value(0, output_field=DecimalField()),
                    output_field=DecimalField(),
                )
            )
            if p.get('in_stock') == 'true':
                qs = qs.filter(total_stock__gt=0)

        # Apply manual operational filters (those that need custom coercion)
        qs = apply_item_operational_filters(qs, p)
        return qs

    @action(detail=False, methods=['get'], url_path='filter-options')
    def filter_options(self, request):
        """
        GET /api/items/filter-options/
        Returns all distinct values needed to populate filter dropdowns.
        Scoped to active, stockable items.

        Response:
          {
            medicine_types:      [{ code, name, name_ar }],
            categories:          [{ id, softech_id, name, name_ar }],
            suppliers:           [{ code, name }],
            families:            [{ code, name, name_ar }],
            insurance_types:     [{ code, name, name_ar }],   -- static
            item_level_options:  [{ code, name, name_ar }],   -- static
            trans_options:       [{ code, name, name_ar }],   -- static
            nosale_classif_options: [{ code, name, name_ar }],-- static
            store_classif_options:  [{ code, name }],          -- dynamic (from DB)
          }
        """
        base_qs = Item.objects.filter(is_active=True, is_stockable=True)

        # ── Medicine types ─────────────────────────────────────────────────────
        med_rows = (
            base_qs.exclude(medicine_type='')
            .values('medicine_type', 'medicine_type_name', 'medicine_type_name_ar')
            .distinct().order_by('medicine_type')
        )
        med_seen = {}
        for r in med_rows:
            code = r['medicine_type']
            if code not in med_seen or not med_seen[code]['name']:
                med_seen[code] = {
                    'code':    code,
                    'name':    r['medicine_type_name'] or r['medicine_type_name_ar'] or code,
                    'name_ar': r['medicine_type_name_ar'] or '',
                }
        medicine_types = sorted(med_seen.values(), key=lambda x: x['code'])

        # ── Categories ─────────────────────────────────────────────────────────
        cat_ids = base_qs.exclude(category__isnull=True).values_list('category_id', flat=True).distinct()
        categories = list(
            Category.objects.filter(id__in=cat_ids)
            .values('id', 'softech_id', 'name', 'name_ar')
            .order_by('name_ar')
        )

        # ── Suppliers ──────────────────────────────────────────────────────────
        supp_rows = (
            base_qs.exclude(supplier_code='')
            .values('supplier_code', 'supplier_name')
            .distinct().order_by('supplier_code')
        )
        supp_seen = {}
        for r in supp_rows:
            code = r['supplier_code']
            if code not in supp_seen or not supp_seen[code]['name']:
                supp_seen[code] = {'code': code, 'name': r['supplier_name'] or code}
        suppliers = sorted(supp_seen.values(), key=lambda x: x['name'].lower())

        # ── Producers ──────────────────────────────────────────────────────────
        prod_rows = (
            base_qs.exclude(producer_code='')
            .values('producer_code', 'producer_name')
            .distinct().order_by('producer_code')
        )
        prod_seen = {}
        for r in prod_rows:
            code = r['producer_code']
            if code not in prod_seen or not prod_seen[code]['name']:
                prod_seen[code] = {'code': code, 'name': r['producer_name'] or code}
        producers = sorted(prod_seen.values(), key=lambda x: x['name'].lower())

        # ── Families (dosage form group) ───────────────────────────────────────
        fam_rows = (
            base_qs.exclude(family_code='')
            .values('family_code', 'family_name', 'family_name_ar')
            .distinct().order_by('family_code')
        )
        fam_seen = {}
        for r in fam_rows:
            code = r['family_code']
            if code not in fam_seen or not fam_seen[code]['name']:
                fam_seen[code] = {
                    'code':    code,
                    'name':    r['family_name'] or code,
                    'name_ar': r['family_name_ar'] or r['family_name'] or code,
                }
        families = sorted(fam_seen.values(), key=lambda x: (x['name_ar'] or x['name']).lower())

        # ── Store classif — dynamic from active items ──────────────────────────
        store_rows = (
            base_qs.exclude(store_classif='')
            .values('store_classif', 'store_classif_name')
            .distinct().order_by('store_classif')
        )
        store_seen = {}
        for r in store_rows:
            code = r['store_classif']
            if code not in store_seen:
                store_seen[code] = {
                    'code': code,
                    'name': r['store_classif_name'] or code,
                }
        store_classif_options = sorted(store_seen.values(), key=lambda x: x['code'])

        return Response({
            'medicine_types':        medicine_types,
            'categories':            categories,
            'suppliers':             suppliers,
            'producers':             producers,
            'families':              families,
            'insurance_types':       INSURANCE_TYPE_OPTIONS,
            'item_level_options':    ITEM_LEVEL_OPTIONS,
            'trans_options':         TRANS_OPTIONS,
            'nosale_classif_options': NOSALE_CLASSIF_OPTIONS,
            'store_classif_options': store_classif_options,
        })

    def get_serializer_class(self):
        if self.action == 'list':
            return ItemSearchSerializer
        return ItemSerializer

    @action(detail=True, methods=['get'])
    def stock(self, request, pk=None):
        """
        Returns per-branch aggregated stock (expired stores 102/103/105 excluded).
        One record per branch, quantities summed across valid stores.
        """
        item = self.get_object()
        from django.db.models import Sum as _Sum
        rows = (
            ItemStock.objects
            .filter(item=item)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('branch__id', 'branch__name', 'branch__name_ar')
            .annotate(
                quantity_on_hand=_Sum('quantity_on_hand'),
                monthly_qty=_Sum('monthly_qty'),
                on_order_qty=_Sum('on_order_qty'),
            )
            .order_by('-quantity_on_hand')
        )
        result = []
        for r in rows:
            qty = float(r['quantity_on_hand'] or 0)
            if qty >= 5:
                stock_status, label = 'in_stock', 'متوفر'
            elif qty > 0:
                stock_status, label = 'low_stock', 'كمية محدودة'
            else:
                stock_status, label = 'out_of_stock', 'غير متوفر'
            result.append({
                'branch':           r['branch__id'],
                'branch_name':      r['branch__name'],
                'branch_name_ar':   r['branch__name_ar'],
                'quantity_on_hand': qty,
                'monthly_qty':      float(r['monthly_qty'] or 0),
                'on_order_qty':     float(r['on_order_qty'] or 0),
                'stock_status':     stock_status,
                'stock_status_label': label,
            })
        return Response(result)

    @action(detail=False, methods=['get'], url_path='softech-search')
    def softech_search(self, request):
        """
        GET /api/items/softech-search/?q=panadol
        GET /api/items/softech-search/?q=pan*500      (wildcard)
        GET /api/items/softech-search/?q=سكر          (Arabic disease term → expands to drug names)
        GET /api/items/softech-search/?q=metformin     (active ingredient)
        GET /api/items/softech-search/?q=A10BA02       (ATC code)

        Wildcard rules (mirrors SOFTECH native search):
          *  anywhere in the query string is converted to SQL LIKE %
          If no * is present, the term is wrapped with % on both sides (implicit match).

        Disease / symptom expansion:
          Arabic and English disease terms (سكر, ضغط, diabetes, hypertension…) are
          automatically expanded to matching drug names via the chronic module's
          ActiveIngredient.chronic_class mapping. Results are ranked: exact name
          matches first, then ingredient/disease matches.

        Falls back to PostgreSQL catalog if SOFTECH is unavailable.
        Returns name, code, scientific name, barcode, public price, and per-branch stock.

        Optional params:
          branch_id — if provided, includes qty_at_branch in each result
        """
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response(
                {'detail': 'يجب إدخال حرفين على الأقل للبحث'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        branch_id = request.query_params.get('branch_id')

        # ── Wildcard conversion ───────────────────────────────────────────────
        # User types "*" → we convert to SQL "%".
        # If no wildcard present, wrap both sides (standard substring match).
        if '*' in q:
            like_q = q.replace('*', '%')
        else:
            like_q = f'%{q}%'
        like_q = like_q.lower()   # normalize; SOFTECH comparison is case-insensitive

        results = []

        # ── SOFTECH live search ───────────────────────────────────────────────
        try:
            from config.sybase import get_sybase_connection
            from apps.sync.sybase_queries import QUERY_ITEM_SEARCH
            conn   = get_sybase_connection()
            cursor = conn.cursor()
            cursor.execute(QUERY_ITEM_SEARCH, [like_q, like_q, like_q, like_q])
            rows   = cursor.fetchall()
            conn.close()

            for row in rows:
                softech_id = str(row[0]).strip() if row[0] else ''
                results.append({
                    'softech_id':      softech_id,
                    'name':            str(row[1]).strip() if row[1] else '',
                    'name_scientific': str(row[2]).strip() if row[2] else '',
                    'barcode':         str(row[3]).strip() if row[3] else '',
                    # row[5] = itemsaleprice  = full-pack retail price (what the customer pays)
                    # row[6] = unitsaleprice  = price per individual unit / strip
                    'pack_price': float(row[5]) if row[5] is not None else 0.0,
                    'unit_price': float(row[6]) if row[6] is not None else 0.0,
                    'requires_fridge': bool(row[9]) if row[9] else False,
                    'medicine_type':   str(row[10]).strip() if row[10] else '',
                    'source':          'softech',
                    'item_id':         None,   # filled below from PG catalog
                    'qty_at_branch':   None,
                })

            # Enrich with local PG id + branch stock
            if results:
                codes   = [r['softech_id'] for r in results if r['softech_id']]
                pg_map  = {
                    item.softech_id: item
                    for item in Item.objects.filter(softech_id__in=codes, is_active=True)
                }
                if branch_id:
                    from django.db.models import Sum as _Sum
                    stock_qs = (
                        ItemStock.objects
                        .filter(item__softech_id__in=codes, branch_id=branch_id)
                        .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
                        .values('item__softech_id')
                        .annotate(qty=_Sum('quantity_on_hand'))
                    )
                    stock_map = {r['item__softech_id']: float(r['qty'] or 0) for r in stock_qs}
                else:
                    stock_map = {}

                for r in results:
                    pg = pg_map.get(r['softech_id'])
                    if pg:
                        r['item_id'] = pg.id
                        # Prefer PG values (synced from SOFTECH) so prices are never stale
                        r['pack_price'] = float(pg.pack_price) or r['pack_price']
                        r['unit_price'] = float(pg.unit_price) or r['unit_price']
                    if branch_id:
                        r['qty_at_branch'] = stock_map.get(r['softech_id'], 0.0)

        except Exception:
            # ── PG catalog fallback ───────────────────────────────────────────
            # Build the same wildcard filter in Django ORM
            pg_like = like_q.replace('%', '')   # strip SQL %, use icontains
            # For true wildcard we build a regex-style filter
            if '*' in q:
                # Convert user pattern to a series of icontains fragments
                parts = [p for p in q.split('*') if p.strip()]
                pg_filter = models.Q()
                for part in parts:
                    pg_filter &= (
                        models.Q(name__icontains=part) |
                        models.Q(name_scientific__icontains=part)
                    )
            else:
                pg_filter = (
                    models.Q(name__icontains=q) |
                    models.Q(softech_id__icontains=q) |
                    models.Q(barcode__icontains=q) |
                    models.Q(name_scientific__icontains=q)
                )

            qs = Item.objects.filter(is_active=True).filter(pg_filter)
            if branch_id:
                from django.db.models import Sum as _Sum
                qs = qs.prefetch_related('stock_levels')
                stock_qs = (
                    ItemStock.objects
                    .filter(item__in=qs, branch_id=branch_id)
                    .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
                    .values('item_id')
                    .annotate(qty=_Sum('quantity_on_hand'))
                )
                stock_map = {r['item_id']: float(r['qty'] or 0) for r in stock_qs}
            else:
                stock_map = {}

            results = [
                {
                    'softech_id':      item.softech_id,
                    'name':            item.name,
                    'name_scientific': item.name_scientific,
                    'barcode':         item.barcode,
                    'pack_price': float(item.pack_price),  # full pack retail price
                    'unit_price': float(item.unit_price),  # per-unit/strip price
                    'requires_fridge': item.requires_fridge,
                    'medicine_type':   item.medicine_type,
                    'source':          'pg_catalog',
                    'item_id':         item.id,
                    'qty_at_branch':   stock_map.get(item.id) if branch_id else None,
                }
                for item in qs[:50]
            ]

        # ── Disease/ingredient expansion — PG only ────────────────────────────
        # If SOFTECH returned results, skip this. If SOFTECH was unreachable,
        # the PG fallback already ran. Only run expansion if results are sparse.
        if len(results) < 3:
            expanded = _expand_disease_query(q)
            if expanded:
                already_ids = {r['softech_id'] for r in results}
                for exp_r in expanded:
                    if exp_r['softech_id'] not in already_ids:
                        results.append(exp_r)
                        already_ids.add(exp_r['softech_id'])

        return Response({'results': results, 'count': len(results)})


# ── Disease / ingredient query expansion ──────────────────────────────────────

# Arabic → chronic_class mapping (covers common misspellings & synonyms)
_ARABIC_DISEASE_MAP = {
    'سكر':        'diabetes',
    'سكري':       'diabetes',
    'السكر':      'diabetes',
    'ضغط':        'hypertension',
    'ضغط الدم':   'hypertension',
    'قلب':        'cardiovascular',
    'كوليسترول':  'cholesterol',
    'دهون':       'cholesterol',
    'غدة':        'thyroid',
    'غدة درقية':  'thyroid',
    'ربو':        'asthma',
    'نفسي':       'depression',
    'اكتئاب':     'depression',
    'صرع':        'epilepsy',
    'عظام':       'osteoporosis',
    'هشاشة':      'osteoporosis',
    'كلى':        'renal',
    'تخثر':       'anticoagulant',
}
_ENGLISH_DISEASE_MAP = {
    'diabetes':     'diabetes',
    'hypertension': 'hypertension',
    'blood pressure': 'hypertension',
    'heart':        'cardiovascular',
    'cholesterol':  'cholesterol',
    'thyroid':      'thyroid',
    'asthma':       'asthma',
    'depression':   'depression',
    'epilepsy':     'epilepsy',
    'seizure':      'epilepsy',
    'osteoporosis': 'osteoporosis',
    'renal':        'renal',
    'kidney':       'renal',
    'anticoagulant': 'anticoagulant',
    'blood thinner': 'anticoagulant',
}


def _expand_disease_query(q: str) -> list:
    """
    If the query looks like a disease/condition term (Arabic or English),
    return items that belong to that chronic_class via ItemIngredientMap.
    Returns a list of result dicts (same shape as softech_search results).
    """
    q_lower = q.strip().lower()

    # Find matching chronic_class
    chronic_class = (
        _ARABIC_DISEASE_MAP.get(q_lower)
        or _ENGLISH_DISEASE_MAP.get(q_lower)
    )

    if not chronic_class:
        # Try partial Arabic match
        for term, cls in _ARABIC_DISEASE_MAP.items():
            if term in q_lower or q_lower in term:
                chronic_class = cls
                break

    if not chronic_class:
        # Try ATC code prefix match (e.g. "A10" → diabetes)
        try:
            from apps.chronic.models import ActiveIngredient
            ai = ActiveIngredient.objects.filter(
                atc_code__istartswith=q_lower.upper()
            ).first()
            if ai and ai.chronic_class:
                chronic_class = ai.chronic_class
        except Exception:
            pass

    if not chronic_class:
        # Try active ingredient name match
        try:
            from apps.chronic.models import ItemIngredientMap
            maps = ItemIngredientMap.objects.filter(
                active_ingredient__name__icontains=q_lower,
            ).select_related('item', 'active_ingredient')[:20]
            results = []
            for m in maps:
                item = m.item
                if item.is_active:
                    results.append({
                        'softech_id':      item.softech_id,
                        'name':            item.name,
                        'name_scientific': item.name_scientific,
                        'barcode':         item.barcode,
                        'pack_price':      float(item.pack_price),
                        'unit_price':      float(item.unit_price),
                        'requires_fridge': item.requires_fridge,
                        'medicine_type':   item.medicine_type,
                        'source':          'ingredient_search',
                        'item_id':         item.id,
                        'qty_at_branch':   None,
                        'match_type':      'ingredient',
                        'ingredient':      m.active_ingredient.name,
                    })
            return results
        except Exception:
            return []

    # Found a chronic_class — find all items mapped to it
    try:
        from apps.chronic.models import ItemIngredientMap
        maps = (
            ItemIngredientMap.objects
            .filter(
                active_ingredient__chronic_class=chronic_class,
                active_ingredient__is_chronic=True,
                item__is_active=True,
            )
            .select_related('item', 'active_ingredient')
            .order_by('item__name')[:30]
        )
        results = []
        seen = set()
        for m in maps:
            item = m.item
            if item.pk in seen:
                continue
            seen.add(item.pk)
            results.append({
                'softech_id':      item.softech_id,
                'name':            item.name,
                'name_scientific': item.name_scientific,
                'barcode':         item.barcode,
                'pack_price':      float(item.pack_price),
                'unit_price':      float(item.unit_price),
                'requires_fridge': item.requires_fridge,
                'medicine_type':   item.medicine_type,
                'source':          'disease_search',
                'item_id':         item.id,
                'qty_at_branch':   None,
                'match_type':      'disease',
                'chronic_class':   chronic_class,
                'ingredient':      m.active_ingredient.name,
            })
        return results
    except Exception:
        return []


# ── Variant Groups API ─────────────────────────────────────────────────────────
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response as DRFResponse
from .models import CatalogVariantGroup, VariantMember, ProductBundle, BundleItem
from .serializers import (
    VariantGroupSerializer, VariantMemberSerializer,
    ProductBundleSerializer, BundleItemSerializer,
)


class VariantGroupListCreateView(generics.ListCreateAPIView):
    serializer_class   = VariantGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = CatalogVariantGroup.objects.prefetch_related('members__item')
        q = self.request.query_params.get('q', '').strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(name_ar__icontains=q))
        return qs

    def perform_create(self, serializer):
        from apps.users.models import StaffProfile
        try:
            staff = StaffProfile.objects.get(user=self.request.user)
        except StaffProfile.DoesNotExist:
            staff = None
        serializer.save(created_by=staff)


class VariantGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = VariantGroupSerializer
    permission_classes = [IsAuthenticated]
    queryset = CatalogVariantGroup.objects.prefetch_related('members__item')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_variant_member(request, group_pk):
    """POST /api/items/variant-groups/{pk}/members/  body: {item, variant_label, sort_order}"""
    from django.shortcuts import get_object_or_404
    group = get_object_or_404(CatalogVariantGroup, pk=group_pk)
    ser = VariantMemberSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    ser.save(group=group)
    return DRFResponse(ser.data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_variant_member(request, group_pk, member_pk):
    """DELETE /api/items/variant-groups/{pk}/members/{member_pk}/"""
    from django.shortcuts import get_object_or_404
    member = get_object_or_404(VariantMember, pk=member_pk, group_id=group_pk)
    member.delete()
    return DRFResponse(status=status.HTTP_204_NO_CONTENT)


# ── Product Bundles API ────────────────────────────────────────────────────────

class ProductBundleListCreateView(generics.ListCreateAPIView):
    serializer_class   = ProductBundleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ProductBundle.objects.prefetch_related('items__item')
        q = self.request.query_params.get('q', '').strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(name_ar__icontains=q))
        active = self.request.query_params.get('active')
        if active is not None:
            qs = qs.filter(is_active=active.lower() == 'true')
        return qs

    def perform_create(self, serializer):
        from apps.users.models import StaffProfile
        try:
            staff = StaffProfile.objects.get(user=self.request.user)
        except StaffProfile.DoesNotExist:
            staff = None
        serializer.save(created_by=staff)


class ProductBundleDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProductBundleSerializer
    permission_classes = [IsAuthenticated]
    queryset = ProductBundle.objects.prefetch_related('items__item')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_bundle_item(request, bundle_pk):
    """POST /api/items/bundles/{pk}/items/  body: {item, quantity}"""
    from django.shortcuts import get_object_or_404
    bundle = get_object_or_404(ProductBundle, pk=bundle_pk)
    ser = BundleItemSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    ser.save(bundle=bundle)
    return DRFResponse(ser.data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_bundle_item(request, bundle_pk, bi_pk):
    """DELETE /api/items/bundles/{pk}/items/{bi_pk}/"""
    from django.shortcuts import get_object_or_404
    bi = get_object_or_404(BundleItem, pk=bi_pk, bundle_id=bundle_pk)
    bi.delete()
    return DRFResponse(status=status.HTTP_204_NO_CONTENT)


# ── Item Full Intelligence Aggregator ─────────────────────────────────────────
# GET /api/items/{softech_id}/intel/
# Aggregates ALL module data for one item — no new models, pure read.
# Writes go to the respective module endpoints directly from the frontend.

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def item_full_intel(request, softech_id):
    """
    Returns every piece of data held about an item across all modules:
      softech        — SOFTECH-synced base fields (catalog.Item)
      enrichment     — enrichment.ItemEnrichment fields + completeness_score
      content        — product_experience.ProductContent
      attributes     — product_experience.ProductAttribute
      seo            — product_experience.ProductSEO
      media          — product_experience.ProductMedia list
      chronic_tag    — catalog.ChronicMedication tag if present
      ingredients    — chronic.ItemIngredientMap → ActiveIngredient records
      demand_network — purchasing.ItemDemandAggregated (latest engine run)
      demand_branches — purchasing.ItemDemandMetrics per branch (latest run)
      purchase_history — invoice-derived: per-supplier avg/min/max price + vendor codes
      fbt            — recommendations.FrequentlyBoughtTogether top pairs
    """
    from django.shortcuts import get_object_or_404
    item = get_object_or_404(Item, softech_id=softech_id, is_active=True)

    payload = {}

    # ── 1. SOFTECH base ───────────────────────────────────────────────────────
    from .serializers import ItemSerializer
    payload['softech'] = ItemSerializer(item).data

    # ── 2. Enrichment ─────────────────────────────────────────────────────────
    try:
        from apps.enrichment.models import ItemEnrichment, ENRICHABLE_FIELDS, FIELD_LABELS_AR
        enr, _ = ItemEnrichment.objects.get_or_create(item=item)
        enr_data = {'id': enr.pk, 'completeness_score': enr.completeness_score, 'is_published': enr.is_published}
        for field in ENRICHABLE_FIELDS:
            enr_data[field] = getattr(enr, field, '')
        enr_data['field_labels'] = FIELD_LABELS_AR
        payload['enrichment'] = enr_data
    except Exception:
        payload['enrichment'] = None

    # ── 3. Product experience ─────────────────────────────────────────────────
    try:
        from apps.product_experience.services import (
            ensure_product_content, ensure_product_attribute, ensure_product_seo
        )
        from apps.product_experience.serializers import (
            ProductContentSerializer, ProductAttributeSerializer,
            ProductSEOSerializer, ProductMediaSerializer
        )
        from apps.product_experience.models import ProductMedia
        content  = ensure_product_content(item)
        attr     = ensure_product_attribute(item)
        seo      = ensure_product_seo(item)
        media_qs = ProductMedia.objects.filter(item=item, approved=True).order_by('-is_primary', 'order')
        payload['content']    = ProductContentSerializer(content).data
        payload['attributes'] = ProductAttributeSerializer(attr).data
        payload['seo']        = ProductSEOSerializer(seo, context={'request': request}).data
        payload['media']      = ProductMediaSerializer(media_qs, many=True, context={'request': request}).data
    except Exception:
        payload['content'] = payload['attributes'] = payload['seo'] = payload['media'] = None

    # ── 4. Chronic classification ─────────────────────────────────────────────
    try:
        chronic_tag = item.chronic_tag if hasattr(item, 'chronic_tag') else None
        if not chronic_tag:
            try:
                from apps.catalog.models import ChronicMedication
                chronic_tag = ChronicMedication.objects.get(item=item)
            except Exception:
                chronic_tag = None
        payload['chronic_tag'] = {
            'exists':         chronic_tag is not None,
            'id':             chronic_tag.pk if chronic_tag else None,
            'category_label': chronic_tag.category_label if chronic_tag else '',
            'is_active':      chronic_tag.is_active if chronic_tag else False,
        }
    except Exception:
        payload['chronic_tag'] = {'exists': False}

    # ── 5. Active ingredient maps (chronic module) ────────────────────────────
    try:
        from apps.chronic.models import ItemIngredientMap
        maps = (
            ItemIngredientMap.objects
            .filter(item=item)
            .select_related('active_ingredient')
            .order_by('-is_primary', 'active_ingredient__name')
        )
        payload['ingredients'] = [
            {
                'map_id':       m.pk,
                'ingredient_id': m.active_ingredient_id,
                'name':          m.active_ingredient.name,
                'name_ar':       m.active_ingredient.name_ar,
                'atc_code':      m.active_ingredient.atc_code,
                'chronic_class': m.active_ingredient.chronic_class,
                'chronic_class_display': m.active_ingredient.get_chronic_class_display() if m.active_ingredient.chronic_class else '',
                'is_chronic':    m.active_ingredient.is_chronic,
                'concentration': m.concentration,
                'is_primary':    m.is_primary,
            }
            for m in maps
        ]
    except Exception:
        payload['ingredients'] = []

    # ── 6. Purchasing intelligence — latest run ───────────────────────────────
    try:
        from apps.purchasing.models import ItemDemandAggregated, ItemDemandMetrics, DemandCalculationRun
        latest_run = DemandCalculationRun.objects.filter(status='success').order_by('-started_at').first()
        agg = (
            ItemDemandAggregated.objects.filter(run=latest_run, item=item).first()
            if latest_run else None
        )
        if latest_run and agg:
            branch_metrics = list(
                ItemDemandMetrics.objects
                .filter(run=latest_run, item=item)
                .select_related('branch')
                .order_by('-monthly_avg')
            )
            payload['demand_network'] = {
                'abc_class':              agg.abc_class,
                'total_monthly_avg':      float(agg.total_monthly_avg),
                'total_current_stock':    float(agg.total_current_stock),
                'total_monthly_value':    float(agg.total_monthly_value),
                'total_gap':              float(agg.total_gap),
                'total_qty_30d':          float(agg.total_qty_30d),
                'total_qty_90d':          float(agg.total_qty_90d),
                'total_qty_365d':         float(agg.total_qty_365d),
                'total_net_sales_revenue': float(agg.total_net_sales_revenue),
                'total_lost_revenue_30d': float(agg.total_lost_revenue_30d),
                'total_lost_qty_30d':     float(agg.total_lost_qty_30d),
                'network_availability_rate_30d': agg.network_availability_rate_30d,
                'branches_with_sales':    agg.branches_with_sales,
                'branches_with_gap':      agg.branches_with_gap,
                'calc_date':              agg.calc_date.isoformat() if agg.calc_date else None,
            }
            payload['demand_branches'] = [
                {
                    'branch_id':             m.branch_id,
                    'branch_name':           m.branch.name_ar or m.branch.name,
                    'abc_class':             m.abc_class,
                    'monthly_avg':           float(m.monthly_avg),
                    'current_stock':         float(m.current_stock),
                    'safety_stock':          float(m.safety_stock),
                    'gap':                   float(m.gap),
                    'coverage_months':       float(m.coverage_months) if m.coverage_months else None,
                    'coverage_days':         m.coverage_days,
                    'stockout_days_30d':     m.stockout_days_30d,
                    'availability_rate_30d': m.availability_rate_30d,
                    'lost_revenue_30d':      float(m.lost_revenue_30d),
                    'root_cause':            m.root_cause,
                    'stock_status':          m.stock_status,
                }
                for m in branch_metrics
            ]
        else:
            payload['demand_network'] = None
            payload['demand_branches'] = []
    except Exception:
        payload['demand_network'] = None
        payload['demand_branches'] = []

    # ── 7. Purchase invoice history ───────────────────────────────────────────
    try:
        from apps.invoices.models import InvoiceLine
        from django.db.models import Avg, Min, Max, Count
        lines = (
            InvoiceLine.objects
            .filter(item=item, is_confirmed=True, unit_price__gt=0)
            .select_related('invoice', 'invoice__vendor')
        )

        # Network aggregates
        agg_overall = lines.aggregate(
            avg_price=Avg('unit_price'),
            min_price=Min('unit_price'),
            max_price=Max('unit_price'),
            invoice_count=Count('id'),
        )

        # Per-vendor breakdown
        from collections import defaultdict
        vendor_data = defaultdict(lambda: {'prices': [], 'codes': set(), 'dates': [], 'name': ''})
        for line in lines.select_related('invoice__vendor')[:500]:
            vendor_key = line.invoice.supplier_name or (line.invoice.vendor.name if line.invoice.vendor else 'غير محدد')
            vendor_data[vendor_key]['name'] = vendor_key
            vendor_data[vendor_key]['prices'].append(float(line.unit_price))
            if line.vendor_item_code:
                vendor_data[vendor_key]['codes'].add(line.vendor_item_code)
            if line.invoice.invoice_date:
                vendor_data[vendor_key]['dates'].append(line.invoice.invoice_date.isoformat())

        suppliers = []
        for vendor_name, d in vendor_data.items():
            prices = d['prices']
            if not prices:
                continue
            suppliers.append({
                'name':            vendor_name,
                'avg_price':       round(sum(prices) / len(prices), 3),
                'min_price':       round(min(prices), 3),
                'max_price':       round(max(prices), 3),
                'invoice_count':   len(prices),
                'vendor_item_codes': sorted(d['codes']),
                'last_invoice_date': max(d['dates']) if d['dates'] else None,
            })
        suppliers.sort(key=lambda x: x['invoice_count'], reverse=True)

        payload['purchase_history'] = {
            'overall': {
                'avg_price':     float(agg_overall['avg_price'] or 0),
                'min_price':     float(agg_overall['min_price'] or 0),
                'max_price':     float(agg_overall['max_price'] or 0),
                'invoice_count': agg_overall['invoice_count'],
            },
            'suppliers': suppliers,
        }
    except Exception:
        payload['purchase_history'] = {'overall': {}, 'suppliers': []}

    # ── 8. Frequently Bought Together ─────────────────────────────────────────
    try:
        from apps.recommendations.models import FrequentlyBoughtTogether, RecommendationEngineRun
        from django.db.models import Q as _Q
        fbt_run = RecommendationEngineRun.objects.filter(status='success').order_by('-started_at').first()
        if fbt_run:
            fbt_pairs = (
                FrequentlyBoughtTogether.objects
                .filter(run=fbt_run)
                .filter(_Q(item_a=item) | _Q(item_b=item))
                .select_related('item_a', 'item_b')
                .order_by('-confidence')
                [:10]
            )
            payload['fbt'] = [
                {
                    'partner_softech_id': p.item_b.softech_id if p.item_a_id == item.pk else p.item_a.softech_id,
                    'partner_name':       p.item_b.name if p.item_a_id == item.pk else p.item_a.name,
                    'confidence':         round(float(p.confidence), 4),
                    'support':            round(float(p.support), 6),
                    'lift':               round(float(p.lift), 3),
                    'co_occurrences':     p.co_occurrences,
                }
                for p in fbt_pairs
            ]
        else:
            payload['fbt'] = []
    except Exception:
        payload['fbt'] = []

    return DRFResponse(payload)


# ── Item ingredient maps (chronic module write via catalog API) ───────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def item_ingredients(request, softech_id):
    """
    GET  /api/items/{softech_id}/ingredients/  — list ItemIngredientMap entries
    POST /api/items/{softech_id}/ingredients/  — add mapping
         body: { active_ingredient_id: int, concentration: str, is_primary: bool }
    """
    from django.shortcuts import get_object_or_404
    item = get_object_or_404(Item, softech_id=softech_id, is_active=True)

    if request.method == 'GET':
        try:
            from apps.chronic.models import ItemIngredientMap
            maps = ItemIngredientMap.objects.filter(item=item).select_related('active_ingredient')
            return DRFResponse([
                {
                    'map_id':        m.pk,
                    'ingredient_id': m.active_ingredient_id,
                    'name':          m.active_ingredient.name,
                    'name_ar':       m.active_ingredient.name_ar,
                    'atc_code':      m.active_ingredient.atc_code,
                    'chronic_class': m.active_ingredient.chronic_class,
                    'is_chronic':    m.active_ingredient.is_chronic,
                    'concentration': m.concentration,
                    'is_primary':    m.is_primary,
                }
                for m in maps
            ])
        except Exception as e:
            return DRFResponse({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # POST
    try:
        from apps.chronic.models import ItemIngredientMap, ActiveIngredient
        from apps.users.models import StaffProfile
        ai_id = request.data.get('active_ingredient_id')
        if not ai_id:
            return DRFResponse({'detail': 'active_ingredient_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        ai = get_object_or_404(ActiveIngredient, pk=ai_id)
        try:
            staff = StaffProfile.objects.get(user=request.user)
        except StaffProfile.DoesNotExist:
            staff = None
        m, created = ItemIngredientMap.objects.get_or_create(
            item=item,
            active_ingredient=ai,
            defaults={
                'concentration': request.data.get('concentration', ''),
                'is_primary':    bool(request.data.get('is_primary', True)),
                'mapped_by':     staff,
            },
        )
        if not created:
            m.concentration = request.data.get('concentration', m.concentration)
            m.is_primary    = bool(request.data.get('is_primary', m.is_primary))
            m.save(update_fields=['concentration', 'is_primary'])
        return DRFResponse({
            'map_id':        m.pk,
            'ingredient_id': m.active_ingredient_id,
            'name':          ai.name,
            'name_ar':       ai.name_ar,
            'atc_code':      ai.atc_code,
            'is_primary':    m.is_primary,
            'concentration': m.concentration,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    except Exception as e:
        return DRFResponse({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def item_ingredient_delete(request, softech_id, map_id):
    """DELETE /api/items/{softech_id}/ingredients/{map_id}/"""
    from django.shortcuts import get_object_or_404
    from apps.chronic.models import ItemIngredientMap
    item = get_object_or_404(Item, softech_id=softech_id, is_active=True)
    m    = get_object_or_404(ItemIngredientMap, pk=map_id, item=item)
    m.delete()
    return DRFResponse(status=status.HTTP_204_NO_CONTENT)
