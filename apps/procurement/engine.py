"""
apps/procurement/engine.py

Procurement Intelligence Engine.

Stages:
  1. sync_purchase_lines()     — fetch from Sybase stktrans (doccode 10/120) → PG cache
  2. sync_supplier_profiles()  — sync supplier master from SOFTECH personsdata
  3. compute_supplier_metrics()— aggregate PurchaseLine → SupplierProfile KPIs
  4. build_supplier_item_mapping()— build/update SupplierItemMapping learning table
  5. compute_snapshot()        — compute daily ProcurementSnapshot
  6. compute_buyer_performance()— compute BuyerPerformance per buyer
  7. generate_alerts()         — detect anomalies and generate ProcurementAlert

DOCCODE RULES (enforced here):
  '10'  → purchase → net = +qty, +value
  '120' → return   → net = -qty, -value
"""
import logging
import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

from django.db import transaction, connection
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Min, Max, Q, F

from config.sybase import get_sybase_connection
from .queries import (
    QUERY_PURCHASES_INCREMENTAL,
    QUERY_SUPPLIERS,
    QUERY_SUPPLIER_ITEM_MAPPING,
    QUERY_SUPPLIERS_SEGMENTED,
)
from .models import (
    PurchaseLine, SupplierProfile, SupplierItemMapping,
    ProcurementEngineRun, ProcurementSnapshot, BuyerPerformance,
    ProcurementAlert, SupplierSegmentation,
)

logger = logging.getLogger('elrezeiky.procurement')

BATCH_SIZE = 500
DEFAULT_LOOKBACK = 365


# ── Helpers ────────────────────────────────────────────────────────────────────

def _d(val, default=Decimal('0')):
    """Safe Decimal conversion."""
    try:
        return Decimal(str(val)) if val is not None else default
    except Exception:
        return default


def _date(val):
    """Convert various date types to Python date."""
    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    return None


# ── Stage 1: Sync purchase lines ──────────────────────────────────────────────

def sync_purchase_lines(run: ProcurementEngineRun, lookback_days: int = DEFAULT_LOOKBACK) -> int:
    """
    Pull purchase lines from SOFTECH (doccode 10/120) and upsert into PurchaseLine.
    Returns count of lines synced.
    """
    from apps.catalog.models import Item
    from apps.branches.models import Branch

    logger.info(f'[ProcurementEngine] Stage 1: syncing purchase lines (last {lookback_days}d)')

    # Pre-load lookup dicts to avoid N+1 DB queries
    item_map = {i.softech_id: i for i in Item.objects.only('id', 'softech_id', 'pack_price', 'cost_price')}
    branch_map = {b.softech_branch_id: b for b in Branch.objects.only('id', 'softech_branch_id')}

    try:
        conn = get_sybase_connection()
        cur  = conn.cursor()
        cur.execute(QUERY_PURCHASES_INCREMENTAL, [lookback_days])
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f'[ProcurementEngine] Sybase fetch failed: {e}')
        raise

    logger.info(f'[ProcurementEngine] Fetched {len(rows)} rows from Sybase')

    upsert_count = 0
    buffer = []

    for row in rows:
        supplier_code   = str(row[0] or '').strip()
        branch_code     = str(row[1] or '').strip()
        doccode         = str(row[2] or '').strip()
        # docnumber comes back from jConnect as a float ('64550.0'); strip the
        # trailing '.0' so invoice-number search/display works as entered.
        doc_number      = str(row[3] or '').strip()
        if doc_number.endswith('.0'):
            doc_number = doc_number[:-2]
        doc_date        = _date(row[4])
        item_code       = str(row[5] or '').strip()
        raw_qty         = _d(row[6])    # PAID qty only (free lines excluded)
        raw_value       = _d(row[7])    # PAID value only
        unit_price      = _d(row[8])    # AVG price over paid lines
        cost_price      = _d(row[9])
        buyer_code      = str(row[10] or '').strip()
        doc_value       = _d(row[11])
        store_code      = str(row[12] or '').strip()
        line_tax_amount = _d(row[13])   # SUM(stktrans.itemsalestax)
        tax_rate_pct    = _d(row[14])   # AVG(stktrans.origintaxp)
        bonus_qty       = _d(row[15])   # free_qty — units on 100%-discount lines

        if not all([supplier_code, branch_code, doc_number, doc_date, item_code, doccode]):
            continue
        if doccode not in ('10', '120'):
            continue

        is_return = (doccode == '120')
        net_qty, net_value = PurchaseLine.compute_net(raw_qty, raw_value, is_return)

        # Get public price from PG item cache
        item_obj = item_map.get(item_code)
        public_price = item_obj.pack_price if item_obj else Decimal('0')
        branch_obj   = branch_map.get(branch_code)

        # Margin calculation
        margin_pct = Decimal('0')
        if public_price > 0 and unit_price > 0:
            margin_pct = ((public_price - unit_price) / public_price * 100).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        # Tax is already sign-correct: returns have negative net_value so we
        # negate the tax amount too (mirrors net_value sign convention).
        net_tax = -line_tax_amount if is_return else line_tax_amount

        # effective_cost = (|net_value| + |net_tax|) / (|net_qty| + |bonus_qty|)
        # Free (بونص) units lower the true per-unit cost: you pay for net_qty but
        # receive net_qty + bonus_qty units.  For pure-FOC lines (net_value ≈ 0)
        # effective_cost stays 0.
        eff_units = abs(net_qty) + abs(bonus_qty)
        if eff_units != 0 and (abs(net_value) + abs(net_tax)) > 0:
            eff_cost = (
                (abs(net_value) + abs(net_tax)) / eff_units
            ).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        else:
            eff_cost = Decimal('0')

        buffer.append(PurchaseLine(
            branch_code     = branch_code,
            supplier_code   = supplier_code,
            doc_number      = doc_number,
            doc_date        = doc_date,
            item_code       = item_code,
            store_code      = store_code,
            doccode         = doccode,
            is_return       = is_return,
            raw_qty         = raw_qty,
            raw_value       = raw_value,
            unit_price      = unit_price,
            cost_price      = cost_price,
            net_qty         = net_qty,
            net_value       = net_value,
            public_price    = public_price,
            margin_pct      = margin_pct,
            buyer_code      = buyer_code,
            doc_value       = doc_value,
            vat_value       = net_tax,
            tax_rate_pct    = tax_rate_pct,
            effective_cost  = eff_cost,
            bonus_qty       = bonus_qty,
            item            = item_obj,
            branch          = branch_obj,
        ))

        if len(buffer) >= BATCH_SIZE:
            upsert_count += _bulk_upsert_lines(buffer)
            buffer.clear()

    if buffer:
        upsert_count += _bulk_upsert_lines(buffer)

    run.lines_synced   = len(rows)
    run.lines_upserted = upsert_count
    run.save(update_fields=['lines_synced', 'lines_upserted'])
    logger.info(f'[ProcurementEngine] Stage 1 done: {upsert_count} lines upserted')
    return upsert_count


def _bulk_upsert_lines(batch: list) -> int:
    """Bulk upsert PurchaseLine objects using ON CONFLICT DO UPDATE."""
    if not batch:
        return 0
    update_fields = [
        'raw_qty', 'raw_value', 'unit_price', 'cost_price',
        'net_qty', 'net_value', 'public_price', 'margin_pct',
        'buyer_code', 'doc_value', 'item_id', 'branch_id',
        'vat_value', 'tax_rate_pct', 'effective_cost', 'bonus_qty',
    ]
    PurchaseLine.objects.bulk_create(
        batch,
        update_conflicts=True,
        unique_fields=['branch_code', 'supplier_code', 'doc_number', 'doc_date', 'item_code', 'doccode'],
        update_fields=update_fields,
    )
    return len(batch)


# ── Stage 2: Sync supplier profiles ───────────────────────────────────────────

def sync_supplier_profiles(run: ProcurementEngineRun) -> int:
    """
    Sync supplier master data from SOFTECH personsdata → SupplierProfile.
    """
    logger.info('[ProcurementEngine] Stage 2: syncing supplier master')
    try:
        conn = get_sybase_connection()
        cur  = conn.cursor()
        cur.execute(QUERY_SUPPLIERS)
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f'[ProcurementEngine] Supplier sync failed: {e}')
        return 0

    buffer = []
    for row in rows:
        supplier_code = str(row[0] or '').strip()
        supplier_name = str(row[1] or '').strip()
        classif_code  = str(row[2] or '').strip()
        if not supplier_code:
            continue
        buffer.append(SupplierProfile(
            supplier_code = supplier_code,
            supplier_name = supplier_name,
            classif_code  = classif_code,
        ))

    if buffer:
        SupplierProfile.objects.bulk_create(
            buffer,
            update_conflicts=True,
            unique_fields=['supplier_code'],
            update_fields=['supplier_name', 'classif_code'],
        )

    logger.info(f'[ProcurementEngine] Stage 2 done: {len(buffer)} suppliers')
    return len(buffer)


# ── Stage 3: Compute supplier metrics ────────────────────────────────────────

def compute_supplier_metrics(run: ProcurementEngineRun) -> int:
    """
    Aggregate PurchaseLine → SupplierProfile KPIs.
    All metrics computed from PostgreSQL (reproducible, offline-capable).
    """
    logger.info('[ProcurementEngine] Stage 3: computing supplier metrics')

    from django.utils.timezone import now
    today = now().date()
    d30  = today - _dt.timedelta(days=30)
    d90  = today - _dt.timedelta(days=90)
    d365 = today - _dt.timedelta(days=365)

    # Aggregate from PurchaseLine
    agg = (
        PurchaseLine.objects
        .filter(doc_date__gte=d365)
        .values('supplier_code')
        .annotate(
            total_value=Sum('net_value'),
            total_qty=Sum('net_qty'),
            return_value=Sum('net_value', filter=Q(is_return=True)),
            purchase_value=Sum('net_value', filter=Q(is_return=False)),
            inv_count=Count('doc_number', distinct=True),
            item_count=Count('item_code', distinct=True),
            branch_count=Count('branch_code', distinct=True),
            avg_margin=Avg('margin_pct', filter=Q(is_return=False)),
            val_30d=Sum('net_value', filter=Q(doc_date__gte=d30)),
            val_90d=Sum('net_value', filter=Q(doc_date__gte=d90)),
            first_date=Min('doc_date'),
            last_date=Max('doc_date'),
        )
    )

    updated = 0
    for row in agg:
        sc = row['supplier_code']
        total_val   = _d(row['total_value'])
        purch_val   = _d(row['purchase_value'])
        ret_val     = abs(_d(row['return_value']))
        return_pct  = (ret_val / purch_val * 100).quantize(Decimal('0.01')) if purch_val > 0 else Decimal('0')
        avg_margin  = _d(row['avg_margin'])

        # Supplier scoring (0–100 per dimension)
        score_margin    = min(Decimal('100'), max(Decimal('0'), avg_margin))
        score_returns   = max(Decimal('0'), Decimal('100') - return_pct * 2)
        score_avail     = Decimal('80') if row['inv_count'] >= 4 else Decimal(str(row['inv_count'] * 20))

        # Price stability: compute coefficient of variation of unit_price per supplier
        prices = [
            _d(p)
            for p in PurchaseLine.objects
            .filter(
                supplier_code=sc,
                doc_date__gte=d365,
                is_return=False
            )
            .values_list('unit_price', flat=True)
            if p is not None
        ]

        if len(prices) >= 2:
            avg_p = sum(prices, Decimal('0')) / Decimal(len(prices))

            if avg_p > 0:
                variance = (
                    sum(
                        (p - avg_p) ** 2
                        for p in prices
                    )
                    / Decimal(len(prices))
                )

                std_dev = variance.sqrt()

                cv = (
                    std_dev
                    / avg_p
                    * Decimal('100')
                )

                score_stability = max(
                    Decimal('0'),
                    Decimal('100') - cv.quantize(Decimal('0.01'))
                )

            else:
                score_stability = Decimal('50')

        else:
            score_stability = Decimal('70')

        total_score = (score_margin * Decimal('0.3') +
                       score_avail  * Decimal('0.25') +
                       score_returns * Decimal('0.25') +
                       score_stability * Decimal('0.2'))

        SupplierProfile.objects.filter(supplier_code=sc).update(
            net_purchase_value  = total_val,
            net_purchase_qty    = _d(row['total_qty']),
            net_return_value    = ret_val,
            return_pct          = return_pct,
            distinct_items      = row['item_count'],
            invoice_count       = row['inv_count'],
            avg_margin_pct      = avg_margin,
            branches_supplied   = row['branch_count'],
            value_30d           = _d(row['val_30d']),
            value_90d           = _d(row['val_90d']),
            value_365d          = total_val,
            score_margin        = score_margin.quantize(Decimal('0.01')),
            score_availability  = score_avail.quantize(Decimal('0.01')),
            score_returns       = score_returns.quantize(Decimal('0.01')),
            score_price_stability = score_stability.quantize(Decimal('0.01')),
            total_score         = total_score.quantize(Decimal('0.01')),
            first_purchase_date = row['first_date'],
            last_purchase_date  = row['last_date'],
        )
        updated += 1

    run.suppliers_updated = updated
    run.save(update_fields=['suppliers_updated'])
    logger.info(f'[ProcurementEngine] Stage 3 done: {updated} suppliers updated')
    return updated


# ── Stage 4: Build supplier-item mapping ──────────────────────────────────────

def build_supplier_item_mapping(run: ProcurementEngineRun) -> int:
    """
    Build/update SupplierItemMapping from PurchaseLine history.
    """
    logger.info('[ProcurementEngine] Stage 4: building supplier-item mapping')

    from apps.catalog.models import Item
    d365 = timezone.now().date() - _dt.timedelta(days=365)

    agg = (
        PurchaseLine.objects
        .filter(doc_date__gte=d365)
        .values('supplier_code', 'item_code')
        .annotate(
            purchase_count=Count('doc_number', distinct=True),
            last_date=Max('doc_date'),
            first_date=Min('doc_date'),
            net_qty=Sum('net_qty'),
            net_val=Sum('net_value'),
            min_p=Min('unit_price', filter=Q(is_return=False)),
            max_p=Max('unit_price', filter=Q(is_return=False)),
            avg_p=Avg('unit_price', filter=Q(is_return=False)),
        )
    )

    item_name_map = {i.softech_id: i.name for i in Item.objects.only('softech_id', 'name')}
    item_obj_map  = {i.softech_id: i for i in Item.objects.only('softech_id', 'id')}
    supp_map      = {s.supplier_code: s.supplier_name for s in SupplierProfile.objects.only('supplier_code', 'supplier_name')}

    updated = 0
    buffer_create = []
    buffer_update = []
    existing = {(m.supplier_code, m.item_code): m for m in SupplierItemMapping.objects.all()}

    for row in agg:
        sc = row['supplier_code']
        ic = row['item_code']
        avg_p = _d(row['avg_p'])
        min_p = _d(row['min_p'])
        max_p = _d(row['max_p'])
        last_p_qs = (
            PurchaseLine.objects
            .filter(supplier_code=sc, item_code=ic, is_return=False)
            .order_by('-doc_date')
            .values_list('unit_price', flat=True)
            .first()
        )
        last_p = _d(last_p_qs)
        drift = ((last_p / avg_p - 1) * 100).quantize(Decimal('0.01')) if avg_p > 0 else Decimal('0')
        cnt = row['purchase_count']
        conf = min(Decimal('95'), Decimal('50') + Decimal(str(cnt)) * Decimal('5'))

        key = (sc, ic)
        if key in existing:
            m = existing[key]
            m.purchase_count = cnt
            m.last_purchase_date  = row['last_date']
            m.first_purchase_date = row['first_date']
            m.net_qty_total   = _d(row['net_qty'])
            m.net_value_total = _d(row['net_val'])
            m.min_price       = min_p
            m.max_price       = max_p
            m.avg_price       = avg_p
            m.last_price      = last_p
            m.price_drift_pct = drift
            m.confidence_score = max(m.confidence_score, conf)
            m.supplier_name   = supp_map.get(sc, '')
            m.item_name       = item_name_map.get(ic, '')
            buffer_update.append(m)
        else:
            buffer_create.append(SupplierItemMapping(
                supplier_code = sc,
                supplier_name = supp_map.get(sc, ''),
                item_code     = ic,
                item          = item_obj_map.get(ic),
                item_name     = item_name_map.get(ic, ''),
                purchase_count = cnt,
                last_purchase_date  = row['last_date'],
                first_purchase_date = row['first_date'],
                net_qty_total  = _d(row['net_qty']),
                net_value_total= _d(row['net_val']),
                min_price      = min_p,
                max_price      = max_p,
                avg_price      = avg_p,
                last_price     = last_p,
                price_drift_pct= drift,
                confidence_score = conf,
            ))

    if buffer_create:
        SupplierItemMapping.objects.bulk_create(buffer_create, batch_size=BATCH_SIZE, ignore_conflicts=True)
    if buffer_update:
        SupplierItemMapping.objects.bulk_update(
            buffer_update,
            ['purchase_count', 'last_purchase_date', 'first_purchase_date',
             'net_qty_total', 'net_value_total', 'min_price', 'max_price', 'avg_price',
             'last_price', 'price_drift_pct', 'confidence_score', 'supplier_name', 'item_name'],
            batch_size=BATCH_SIZE,
        )

    updated = len(buffer_create) + len(buffer_update)
    run.mappings_updated = updated
    run.save(update_fields=['mappings_updated'])
    logger.info(f'[ProcurementEngine] Stage 4 done: {updated} mappings')
    return updated


# ── Stage 5: Compute daily snapshot ──────────────────────────────────────────

def compute_snapshot(run: ProcurementEngineRun) -> None:
    """
    Compute and save today's ProcurementSnapshot.
    """
    logger.info('[ProcurementEngine] Stage 5: computing daily snapshot')
    today = timezone.now().date()
    d30   = today - _dt.timedelta(days=30)
    d90   = today - _dt.timedelta(days=90)
    d365  = today - _dt.timedelta(days=365)

    def _agg(gte_date):
        return PurchaseLine.objects.filter(doc_date__gte=gte_date).aggregate(
            net_val   = Sum('net_value'),
            net_qty   = Sum('net_qty'),
            ret_val   = Sum('net_value', filter=Q(is_return=True)),
            purch_val = Sum('net_value', filter=Q(is_return=False)),
            items     = Count('item_code', distinct=True),
            supps     = Count('supplier_code', distinct=True),
            invs      = Count('doc_number', distinct=True),
            avg_mg    = Avg('margin_pct', filter=Q(is_return=False)),
        )

    a30, a90, a365 = _agg(d30), _agg(d90), _agg(d365)

    # Top-3 supplier concentration (by net_value last 365d)
    top3 = list(
        PurchaseLine.objects.filter(doc_date__gte=d365)
        .values('supplier_code')
        .annotate(v=Sum('net_value'))
        .order_by('-v')[:3]
    )
    total365 = _d(a365['net_val'])
    top3_val = sum(_d(x['v']) for x in top3)
    top3_pct = (top3_val / total365 * 100).quantize(Decimal('0.01')) if total365 > 0 else Decimal('0')

    # MoM growth
    prev30 = _d(
        PurchaseLine.objects.filter(
            doc_date__gte=d30 - _dt.timedelta(days=30),
            doc_date__lt=d30
        ).aggregate(v=Sum('net_value'))['v']
    )
    mom = (((_d(a30['net_val']) - prev30) / prev30) * 100).quantize(Decimal('0.01')) if prev30 > 0 else Decimal('0')

    ret_pct_30 = Decimal('0')
    purch30 = _d(a30['purch_val'])
    ret30   = abs(_d(a30['ret_val']))
    if purch30 > 0:
        ret_pct_30 = (ret30 / purch30 * 100).quantize(Decimal('0.01'))

    ProcurementSnapshot.objects.update_or_create(
        snapshot_date=today,
        defaults=dict(
            engine_run=run,
            net_purchase_value_30d  = _d(a30['net_val']),
            net_purchase_value_90d  = _d(a90['net_val']),
            net_purchase_value_365d = total365,
            net_purchase_qty_30d    = _d(a30['net_qty']),
            net_purchase_qty_90d    = _d(a90['net_qty']),
            net_purchase_qty_365d   = _d(a365['net_qty']),
            distinct_items_30d      = a30['items']  or 0,
            distinct_items_90d      = a90['items']  or 0,
            distinct_items_365d     = a365['items'] or 0,
            distinct_suppliers_30d  = a30['supps']  or 0,
            distinct_suppliers_90d  = a90['supps']  or 0,
            distinct_suppliers_365d = a365['supps'] or 0,
            invoice_count_30d       = a30['invs']   or 0,
            invoice_count_90d       = a90['invs']   or 0,
            invoice_count_365d      = a365['invs']  or 0,
            avg_margin_pct_30d      = _d(a30['avg_mg']),
            avg_margin_pct_90d      = _d(a90['avg_mg']),
            avg_margin_pct_365d     = _d(a365['avg_mg']),
            return_value_30d        = ret30,
            return_pct_30d          = ret_pct_30,
            top3_supplier_pct_365d  = top3_pct,
            purchase_growth_pct_mom = mom,
        )
    )
    logger.info('[ProcurementEngine] Stage 5 done: snapshot saved')


# ── Stage 6: Buyer performance ────────────────────────────────────────────────

def compute_buyer_performance(run: ProcurementEngineRun) -> int:
    """
    Aggregate PurchaseLine → BuyerPerformance per buyer_code.
    """
    logger.info('[ProcurementEngine] Stage 6: computing buyer performance')
    today = timezone.now().date()
    d365  = today - _dt.timedelta(days=365)

    from apps.users.models import StaffProfile
    user_map = {}
    for sp in StaffProfile.objects.select_related('user').all():
        erp_code = getattr(sp, 'erp_user_code', None) or ''
        if erp_code:
            user_map[erp_code.strip().lower()] = sp.full_name

    agg = (
        PurchaseLine.objects.filter(doc_date__gte=d365, buyer_code__gt='')
        .values('buyer_code')
        .annotate(
            net_val = Sum('net_value'),
            inv_cnt = Count('doc_number', distinct=True),
            items   = Count('item_code', distinct=True),
            supps   = Count('supplier_code', distinct=True),
            avg_mg  = Avg('margin_pct', filter=Q(is_return=False)),
            ret_val = Sum('net_value', filter=Q(is_return=True)),
            purch_val = Sum('net_value', filter=Q(is_return=False)),
        )
    )

    updated = 0
    for row in agg:
        bc = row['buyer_code']
        purch = _d(row['purch_val'])
        ret   = abs(_d(row['ret_val']))
        ret_p = (ret / purch * 100).quantize(Decimal('0.01')) if purch > 0 else Decimal('0')
        mg    = _d(row['avg_mg'])
        score = (mg * Decimal('0.4') + (Decimal('100') - ret_p) * Decimal('0.3') +
                 min(Decimal('100'), _d(row['supps']) * 10) * Decimal('0.3'))

        BuyerPerformance.objects.update_or_create(
            buyer_code=bc,
            period_start=d365,
            period_end=today,
            defaults=dict(
                buyer_name          = user_map.get(bc.lower(), bc),
                net_purchase_value  = _d(row['net_val']),
                invoice_count       = row['inv_cnt'],
                distinct_items      = row['items'],
                distinct_suppliers  = row['supps'],
                avg_margin_pct      = mg,
                return_pct          = ret_p,
                procurement_score   = score.quantize(Decimal('0.01')),
                engine_run          = run,
            )
        )
        updated += 1

    logger.info(f'[ProcurementEngine] Stage 6 done: {updated} buyers')
    return updated


# ── Stage 7: Generate alerts ──────────────────────────────────────────────────

def generate_alerts(run: ProcurementEngineRun) -> int:
    """
    Detect anomalies in purchase data and create ProcurementAlert records.
    """
    logger.info('[ProcurementEngine] Stage 7: generating alerts')
    alerts = []
    today = timezone.now().date()
    d90   = today - _dt.timedelta(days=90)
    d30   = today - _dt.timedelta(days=30)

    # 1. High return rate suppliers (>20%)
    for sp in SupplierProfile.objects.filter(return_pct__gt=20, invoice_count__gte=3):
        alerts.append(ProcurementAlert(
            alert_type='high_return_rate',
            severity='warning',
            entity_type='supplier',
            entity_code=sp.supplier_code,
            entity_name=sp.supplier_name,
            title=f'معدل مرتجعات عالٍ: {sp.supplier_name}',
            message=f'معدل المرتجعات للمورد {sp.supplier_name} بلغ {sp.return_pct:.1f}% (الحد المسموح 20%)',
            metric_value=sp.return_pct,
            threshold=Decimal('20'),
            engine_run=run,
        ))

    # 2. Low margin items (margin < 10%)
    low_margin = (
        PurchaseLine.objects.filter(doc_date__gte=d30, is_return=False, margin_pct__lt=10, margin_pct__gt=0)
        .values('item_code')
        .annotate(avg_mg=Avg('margin_pct'), cnt=Count('id'))
        .filter(cnt__gte=2)
        .order_by('avg_mg')[:20]
    )
    for row in low_margin:
        alerts.append(ProcurementAlert(
            alert_type='low_margin',
            severity='warning',
            entity_type='item',
            entity_code=row['item_code'],
            title=f'هامش منخفض: {row["item_code"]}',
            message=f'متوسط هامش الصنف {row["item_code"]} = {row["avg_mg"]:.1f}% (أقل من 10%)',
            metric_value=_d(row['avg_mg']),
            threshold=Decimal('10'),
            engine_run=run,
        ))

    # 3. Supplier concentration > 60% (top single supplier)
    total_val = _d(
        PurchaseLine.objects.filter(doc_date__gte=d90)
        .aggregate(v=Sum('net_value'))['v']
    )
    if total_val > 0:
        top_supp = (
            PurchaseLine.objects.filter(doc_date__gte=d90)
            .values('supplier_code')
            .annotate(v=Sum('net_value'))
            .order_by('-v')
            .first()
        )
        if top_supp:
            conc = _d(top_supp['v']) / total_val * 100
            if conc > 60:
                sp = SupplierProfile.objects.filter(supplier_code=top_supp['supplier_code']).first()
                name = sp.supplier_name if sp else top_supp['supplier_code']
                alerts.append(ProcurementAlert(
                    alert_type='high_concentration',
                    severity='warning',
                    entity_type='supplier',
                    entity_code=top_supp['supplier_code'],
                    entity_name=name,
                    title=f'تركز عالٍ: {name}',
                    message=f'المورد {name} يمثل {conc:.1f}% من إجمالي المشتريات (90 يوم)',
                    metric_value=conc.quantize(Decimal('0.01')),
                    threshold=Decimal('60'),
                    engine_run=run,
                ))

    # 4. Price drift > 15%
    for m in SupplierItemMapping.objects.filter(price_drift_pct__gt=15, purchase_count__gte=3):
        alerts.append(ProcurementAlert(
            alert_type='price_spike',
            severity='warning',
            entity_type='item',
            entity_code=m.item_code,
            entity_name=m.item_name,
            title=f'ارتفاع سعر: {m.item_name or m.item_code}',
            message=f'سعر الصنف {m.item_name or m.item_code} من المورد {m.supplier_name} ارتفع بنسبة {m.price_drift_pct:.1f}%',
            metric_value=m.price_drift_pct,
            threshold=Decimal('15'),
            engine_run=run,
        ))

    if alerts:
        ProcurementAlert.objects.bulk_create(alerts, batch_size=BATCH_SIZE)

    run.alerts_generated = len(alerts)
    run.save(update_fields=['alerts_generated'])
    logger.info(f'[ProcurementEngine] Stage 7 done: {len(alerts)} alerts')
    return len(alerts)


# ── v2 Stage: Enrich purchase lines ──────────────────────────────────────────

class _CategoryResolver:
    """
    Resolve a supplier's category CODE from its SOFTECH (ptcode, ptclassifcode)
    using the admin-managed SupplierClassificationRule table.

    Precedence (most specific wins):
      1. exact rule       (ptcode + ptclassifcode)
      2. ptcode-only rule (blank ptclassifcode = any classif under ptcode)
      3. fallback category (SupplierCategory.is_fallback)

    `.ready` is False when no categories are configured yet — callers should then
    skip re-classification so an un-seeded table never wipes existing categories.
    """

    def __init__(self):
        from .models import SupplierCategory, SupplierClassificationRule
        self.ready = SupplierCategory.objects.exists()
        fb = SupplierCategory.objects.filter(is_fallback=True, is_active=True).first()
        self.fallback_code = fb.code if fb else 'UNKNOWN'
        self._exact  = {}   # (ptcode, ptclassifcode) -> (priority, code)
        self._ptonly = {}   # ptcode -> (priority, code)
        for r in (SupplierClassificationRule.objects
                  .filter(is_active=True, category__is_active=True)
                  .select_related('category')):
            code = r.category.code
            if r.ptclassifcode:
                key = (r.ptcode.strip(), r.ptclassifcode.strip())
                if key not in self._exact or r.priority < self._exact[key][0]:
                    self._exact[key] = (r.priority, code)
            else:
                k = r.ptcode.strip()
                if k not in self._ptonly or r.priority < self._ptonly[k][0]:
                    self._ptonly[k] = (r.priority, code)

    def resolve(self, ptcode: str, ptclassifcode: str) -> str:
        pt = (ptcode or '').strip()
        cl = (ptclassifcode or '').strip()
        if (pt, cl) in self._exact:
            return self._exact[(pt, cl)][1]
        if pt in self._ptonly:
            return self._ptonly[pt][1]
        return self.fallback_code


def enrich_purchase_lines(run: ProcurementEngineRun, lookback_days: int = DEFAULT_LOOKBACK) -> None:
    """
    v2 Stage 1.5 — Enrich PurchaseLine with FOC flags and return types.

    Tax fields (vat_value, tax_rate_pct, effective_cost) are now populated
    directly in Stage 1 (sync_purchase_lines) from stktrans.itemsalestax and
    stktrans.origintaxp — no second Sybase round-trip needed here.

    This stage handles the fields that require post-sync logic:
      - is_foc / foc_type   (zero-price or zero-value detection)
      - return_type          ('expiry' | 'normal' | '')
    """
    logger.info('[ProcurementEngine] Stage 1.5: enriching purchase lines (FOC detection, return types)')

    today = timezone.now().date()
    since = today - _dt.timedelta(days=lookback_days)

    # ── FOC detection ─────────────────────────────────────────────────────────
    # bonus_qty now holds the free-goods quantity computed at sync time from the
    # 100%-discount / zero-price lines (SOFTECH books free goods as a separate
    # line for the same item — see queries.py).  It survives the GROUP BY, so it
    # is the authoritative FOC signal.  A line is FOC iff it delivered free units.
    base = PurchaseLine.objects.filter(doc_date__gte=since, is_return=False)

    # Reset the window first so re-runs don't leave stale flags.
    base.update(is_foc=False, foc_type='')
    base.filter(bonus_qty__gt=0).update(is_foc=True, foc_type='bonus')

    # ── Return type ───────────────────────────────────────────────────────────
    ret_base = PurchaseLine.objects.filter(doc_date__gte=since, is_return=True)
    ret_base.filter(store_code__in=['102', '103', '105']).update(return_type='expiry')
    ret_base.exclude(store_code__in=['102', '103', '105']).update(return_type='normal')

    # Clear return_type on purchase lines (not returns)
    PurchaseLine.objects.filter(
        doc_date__gte=since, is_return=False,
    ).exclude(return_type='').update(return_type='')

    logger.info('[ProcurementEngine] Stage 1.5 done')


# ── v2 Stage: Classify supplier segments ─────────────────────────────────────

def classify_supplier_segments(run: ProcurementEngineRun) -> int:
    """
    v2 Stage 2.5 — Build / update SupplierSegmentation from SOFTECH personsdata.
    Auto-classifies suppliers into semantic categories.
    Existing manual overrides (manual_override=True) are never changed.
    Also back-fills supplier_category on SupplierProfile and PurchaseLine.
    """
    logger.info('[ProcurementEngine] Stage 2.5: classifying supplier segments')

    # Build the admin-managed rule resolver.  If no categories are configured
    # yet, skip re-classification so we never wipe existing category codes.
    resolver = _CategoryResolver()
    if not resolver.ready:
        logger.warning('[ProcurementEngine] Stage 2.5 skipped: no SupplierCategory configured yet')
        return 0

    # Fetch ALL persons from Sybase (no ptcode filter)
    raw_rows = []
    try:
        conn = get_sybase_connection()
        cur  = conn.cursor()
        cur.execute(QUERY_SUPPLIERS_SEGMENTED)
        raw_rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f'[ProcurementEngine] Stage 2.5: QUERY_SUPPLIERS_SEGMENTED failed ({e})')
        return 0

    # Also include any supplier_codes that appear in PurchaseLine but not in personsdata
    known_codes = {str(r[0]).strip() for r in raw_rows if r[0]}
    extra_codes = set(
        PurchaseLine.objects
        .exclude(supplier_code__in=known_codes)
        .values_list('supplier_code', flat=True)
        .distinct()
    )

    # Load existing segmentations (manual overrides must not be touched)
    existing = {
        s.supplier_code: s
        for s in SupplierSegmentation.objects.all()
    }

    to_create = []
    to_update = []

    def _process(supplier_code, supplier_name, ptcode, ptclassifcode, persontype, persontypeclassif):
        if not supplier_code:
            return
        category = resolver.resolve(ptcode, ptclassifcode)
        if supplier_code in existing:
            seg = existing[supplier_code]
            if seg.manual_override:
                return  # Never touch manual overrides
            seg.supplier_name     = supplier_name or seg.supplier_name
            seg.supplier_category = category
            seg.ptcode            = ptcode or seg.ptcode
            seg.ptclassifcode     = ptclassifcode or seg.ptclassifcode
            seg.persontype        = persontype or seg.persontype
            seg.persontypeclassif = persontypeclassif or seg.persontypeclassif
            seg.auto_classified   = True
            to_update.append(seg)
        else:
            to_create.append(SupplierSegmentation(
                supplier_code     = supplier_code,
                supplier_name     = supplier_name or '',
                supplier_category = category,
                ptcode            = ptcode or '',
                ptclassifcode     = ptclassifcode or '',
                persontype        = persontype or '',
                persontypeclassif = persontypeclassif or '',
                auto_classified   = True,
                manual_override   = False,
            ))

    for row in raw_rows:
        _process(
            str(row[0] or '').strip(),
            str(row[1] or '').strip(),
            str(row[2] or '').strip(),
            str(row[3] or '').strip(),
            str(row[4] or '').strip(),
            str(row[5] or '').strip(),
        )

    for code in extra_codes:
        _process(code, '', '', '', '', '')

    if to_create:
        SupplierSegmentation.objects.bulk_create(
            to_create, batch_size=BATCH_SIZE, ignore_conflicts=True,
        )
    if to_update:
        SupplierSegmentation.objects.bulk_update(
            to_update,
            ['supplier_name', 'supplier_category', 'ptcode', 'ptclassifcode',
             'persontype', 'persontypeclassif', 'auto_classified'],
            batch_size=BATCH_SIZE,
        )

    total = len(to_create) + len(to_update)

    # Back-fill supplier_category on PurchaseLine (in batches via raw SQL for speed)
    from django.db import connection
    seg_map = {
        s.supplier_code: s.supplier_category
        for s in SupplierSegmentation.objects.all()
    }

    if seg_map:
        # Build CASE expression for batch update
        cases = ' '.join(
            f"WHEN '{sc}' THEN '{cat}'"
            for sc, cat in seg_map.items()
            if sc and cat
        )
        if cases:
            with connection.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE procurement_purchaseline
                       SET supplier_category = CASE supplier_code {cases} ELSE '' END
                    """
                )

    # Back-fill on SupplierProfile as well
    for sc, cat in seg_map.items():
        SupplierProfile.objects.filter(supplier_code=sc).update(supplier_category=cat)

    logger.info(f'[ProcurementEngine] Stage 2.5 done: {len(to_create)} created, {len(to_update)} updated')
    return total


# ── v2 Stage: Compute enhanced supplier scores ────────────────────────────────

def compute_enhanced_scores(run: ProcurementEngineRun) -> int:
    """
    v2 Stage 3.5 — Compute enhanced scoring on SupplierProfile using v2 data:
      enhanced_total_score = 30% Margin + 20% Effective Cost + 15% FOC
                           + 15% Tax + 10% Returns + 10% Availability

    Also computes foc_rate_pct and avg_tax_burden_pct per supplier.
    Runs after compute_supplier_metrics (Stage 3).
    """
    logger.info('[ProcurementEngine] Stage 3.5: computing enhanced supplier scores')

    today = timezone.now().date()
    d365  = today - _dt.timedelta(days=365)

    # Aggregate FOC and tax data from enriched PurchaseLine
    foc_agg = {}
    for row in (
        PurchaseLine.objects
        .filter(doc_date__gte=d365, is_return=False)
        .values('supplier_code')
        .annotate(
            total_lines   = Count('id'),
            foc_lines     = Count('id', filter=Q(is_foc=True)),
            total_value   = Sum('net_value'),
            total_vat     = Sum('vat_value'),
            avg_eff_cost  = Avg('effective_cost', filter=Q(effective_cost__gt=0)),
        )
    ):
        sc = row['supplier_code']
        total_val = _d(row['total_value'])
        foc_rate  = (Decimal(str(row['foc_lines'])) / Decimal(str(row['total_lines'])) * 100
                     if row['total_lines'] > 0 else Decimal('0'))
        tax_rate  = (_d(row['total_vat']) / total_val * 100
                     if total_val > 0 else Decimal('0'))
        foc_agg[sc] = {
            'foc_rate':     foc_rate.quantize(Decimal('0.01')),
            'tax_rate':     tax_rate.quantize(Decimal('0.01')),
            'avg_eff_cost': _d(row['avg_eff_cost']),
        }

    # Global avg effective_cost for relative scoring
    all_eff_costs = [v['avg_eff_cost'] for v in foc_agg.values() if v['avg_eff_cost'] > 0]
    if all_eff_costs:
        global_avg_cost = sum(all_eff_costs, Decimal('0')) / Decimal(len(all_eff_costs))
    else:
        global_avg_cost = Decimal('1')

    updated = 0
    for sp in SupplierProfile.objects.all():
        sc   = sp.supplier_code
        data = foc_agg.get(sc, {})

        foc_rate    = data.get('foc_rate', Decimal('0'))
        tax_rate    = data.get('tax_rate', Decimal('0'))
        avg_eff     = data.get('avg_eff_cost', Decimal('0'))

        # FOC benefit score: higher FOC rate → better (generous supplier)
        #   0% FOC → 50 (neutral), 5%+ → 100
        score_foc = min(Decimal('100'), Decimal('50') + foc_rate * Decimal('10'))

        # Tax efficiency score: lower tax → better
        #   0% tax → 100, 5%+ tax → lower
        score_tax = max(Decimal('0'), Decimal('100') - tax_rate * Decimal('4'))

        # Effective cost score: compare to global average
        #   at/below avg → 80-100; well above avg → penalized
        if avg_eff > 0 and global_avg_cost > 0:
            ratio = avg_eff / global_avg_cost
            score_eff = max(Decimal('0'), min(Decimal('100'), (Decimal('2') - ratio) * Decimal('50')))
        else:
            score_eff = Decimal('50')

        # Enhanced total score
        enhanced = (
            sp.score_margin         * Decimal('0.30') +
            score_eff               * Decimal('0.20') +
            score_foc               * Decimal('0.15') +
            score_tax               * Decimal('0.15') +
            sp.score_returns        * Decimal('0.10') +
            sp.score_availability   * Decimal('0.10')
        )

        SupplierProfile.objects.filter(supplier_code=sc).update(
            foc_rate_pct         = foc_rate,
            avg_tax_burden_pct   = tax_rate,
            score_effective_cost = score_eff.quantize(Decimal('0.01')),
            score_foc_benefit    = score_foc.quantize(Decimal('0.01')),
            score_tax_efficiency = score_tax.quantize(Decimal('0.01')),
            enhanced_total_score = enhanced.quantize(Decimal('0.01')),
        )

        # Also update SupplierSegmentation purchase stats
        if sc in foc_agg:
            SupplierSegmentation.objects.filter(supplier_code=sc).update(
                foc_rate_pct = foc_rate,
            )

        updated += 1

    logger.info(f'[ProcurementEngine] Stage 3.5 done: {updated} suppliers scored')
    return updated


# ── v2 Stage: Advanced alerts ─────────────────────────────────────────────────

def generate_advanced_alerts(run: ProcurementEngineRun) -> int:
    """
    v2 Stage 7.5 — Generate advanced alerts for:
      - FOC deterioration (supplier used to give FOC, now stopped)
      - Tax spike (unusual tax burden increase)
      - Expiry return spike (expiry returns rising)
      - Patient purchases rising
      - Warehouse dependency
    """
    logger.info('[ProcurementEngine] Stage 7.5: generating advanced alerts')

    alerts = []
    today = timezone.now().date()
    d30   = today - _dt.timedelta(days=30)
    d90   = today - _dt.timedelta(days=90)
    d365  = today - _dt.timedelta(days=365)

    # 1. FOC deterioration: suppliers whose foc_rate dropped >5% vs 6-month average
    for sp in SupplierProfile.objects.filter(
        foc_rate_pct__lt=Decimal('2'),  # now low
        invoice_count__gte=4,
    ):
        # Check if they had FOC in the prior 90-day window
        prior_foc = PurchaseLine.objects.filter(
            supplier_code=sp.supplier_code,
            doc_date__gte=d365,
            doc_date__lt=d90,
            is_foc=True,
        ).count()
        recent_foc = PurchaseLine.objects.filter(
            supplier_code=sp.supplier_code,
            doc_date__gte=d90,
            is_foc=True,
        ).count()
        if prior_foc >= 3 and recent_foc == 0:
            alerts.append(ProcurementAlert(
                alert_type   = 'foc_deterioration',
                severity     = 'info',
                entity_type  = 'supplier',
                entity_code  = sp.supplier_code,
                entity_name  = sp.supplier_name,
                title        = f'توقف البضاعة المجانية: {sp.supplier_name}',
                message      = (f'المورد {sp.supplier_name} كان يمنح بضاعة مجانية سابقًا '
                                f'({prior_foc} سطر) لكن لا يوجد FOC في آخر 90 يومًا.'),
                metric_value = Decimal(str(recent_foc)),
                threshold    = Decimal(str(prior_foc)),
                engine_run   = run,
            ))

    # 2. Tax spike: invoice-level tax burden > 5% of purchase value in last 30d
    tax_30 = PurchaseLine.objects.filter(
        doc_date__gte=d30, is_return=False,
    ).aggregate(
        total_val=Sum('net_value'),
        total_vat=Sum('vat_value'),
    )
    total_val_30 = _d(tax_30['total_val'])
    total_vat_30 = _d(tax_30['total_vat'])
    if total_val_30 > 0:
        network_tax_pct = total_vat_30 / total_val_30 * 100
        if network_tax_pct > Decimal('5'):
            alerts.append(ProcurementAlert(
                alert_type   = 'tax_spike',
                severity     = 'warning',
                entity_type  = 'network',
                entity_code  = '',
                entity_name  = 'شبكة المشتريات',
                title        = 'ارتفاع حاد في الضرائب على المشتريات',
                message      = (f'نسبة الضريبة على المشتريات (30 يوم) بلغت '
                                f'{float(network_tax_pct):.1f}% (الحد المقبول 5%).'),
                metric_value = network_tax_pct.quantize(Decimal('0.01')),
                threshold    = Decimal('5'),
                engine_run   = run,
            ))

    # 3. Expiry return spike: expiry returns > 30% of all returns (last 30d)
    all_returns = PurchaseLine.objects.filter(doc_date__gte=d30, is_return=True)
    total_ret = all_returns.count()
    expiry_ret = all_returns.filter(return_type='expiry').count()
    if total_ret >= 5:
        expiry_pct = Decimal(str(expiry_ret)) / Decimal(str(total_ret)) * 100
        if expiry_pct > Decimal('30'):
            alerts.append(ProcurementAlert(
                alert_type   = 'expiry_return_spike',
                severity     = 'warning',
                entity_type  = 'network',
                entity_code  = '',
                entity_name  = 'شبكة المشتريات',
                title        = 'ارتفاع في مرتجعات التالف',
                message      = (f'مرتجعات التالف تمثل {float(expiry_pct):.1f}% من إجمالي '
                                f'المرتجعات في آخر 30 يومًا ({expiry_ret}/{total_ret} سطر).'),
                metric_value = expiry_pct.quantize(Decimal('0.01')),
                threshold    = Decimal('30'),
                engine_run   = run,
            ))

    # 4. Patient purchases rising: >10% of purchase value from PATIENT_REPURCHASE
    patient_val = _d(
        PurchaseLine.objects.filter(
            doc_date__gte=d90, is_return=False,
            supplier_category='PATIENT_REPURCHASE',
        ).aggregate(v=Sum('net_value'))['v']
    )
    total_val_90 = _d(
        PurchaseLine.objects.filter(doc_date__gte=d90, is_return=False)
        .aggregate(v=Sum('net_value'))['v']
    )
    if total_val_90 > 0 and patient_val > 0:
        patient_pct = patient_val / total_val_90 * 100
        if patient_pct > Decimal('10'):
            alerts.append(ProcurementAlert(
                alert_type   = 'patient_purchases_rising',
                severity     = 'info',
                entity_type  = 'category',
                entity_code  = 'PATIENT_REPURCHASE',
                entity_name  = 'شراء من مرضى',
                title        = 'ارتفاع المشتريات من المرضى',
                message      = (f'مشتريات الصنف "شراء من مرضى" وصلت إلى '
                                f'{float(patient_pct):.1f}% من إجمالي المشتريات (90 يوم).'),
                metric_value = patient_pct.quantize(Decimal('0.01')),
                threshold    = Decimal('10'),
                engine_run   = run,
            ))

    # 5. Warehouse dependency: >40% of purchase value from SMALL_WAREHOUSE
    wh_val = _d(
        PurchaseLine.objects.filter(
            doc_date__gte=d90, is_return=False,
            supplier_category='SMALL_WAREHOUSE',
        ).aggregate(v=Sum('net_value'))['v']
    )
    if total_val_90 > 0 and wh_val > 0:
        wh_pct = wh_val / total_val_90 * 100
        if wh_pct > Decimal('40'):
            alerts.append(ProcurementAlert(
                alert_type   = 'warehouse_dependency',
                severity     = 'warning',
                entity_type  = 'category',
                entity_code  = 'SMALL_WAREHOUSE',
                entity_name  = 'مستودعات صغيرة',
                title        = 'اعتماد مفرط على المستودعات الصغيرة',
                message      = (f'المستودعات الصغيرة تمثل {float(wh_pct):.1f}% من المشتريات '
                                f'(90 يوم). يُنصح بتوسيع قاعدة الموردين الرسميين.'),
                metric_value = wh_pct.quantize(Decimal('0.01')),
                threshold    = Decimal('40'),
                engine_run   = run,
            ))

    if alerts:
        ProcurementAlert.objects.bulk_create(alerts, batch_size=BATCH_SIZE)

    # Update SupplierSegmentation purchase stats
    today_d365 = today - _dt.timedelta(days=365)
    for seg in SupplierSegmentation.objects.all():
        agg = PurchaseLine.objects.filter(
            supplier_code=seg.supplier_code, doc_date__gte=today_d365,
        ).aggregate(
            val=Sum('net_value'),
            inv=Count('doc_number', distinct=True),
            ret_val=Sum('net_value', filter=Q(is_return=True)),
            pur_val=Sum('net_value', filter=Q(is_return=False)),
        )
        pur  = _d(agg['pur_val'])
        ret  = abs(_d(agg['ret_val']))
        ret_p = (ret / pur * 100).quantize(Decimal('0.01')) if pur > 0 else Decimal('0')
        SupplierSegmentation.objects.filter(pk=seg.pk).update(
            purchase_value_365d = _d(agg['val']),
            invoice_count_365d  = agg['inv'] or 0,
            return_pct          = ret_p,
        )

    logger.info(f'[ProcurementEngine] Stage 7.5 done: {len(alerts)} advanced alerts')
    return len(alerts)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_procurement_engine(lookback_days: int = DEFAULT_LOOKBACK, triggered_by: str = 'system') -> ProcurementEngineRun:
    """
    Run the full procurement engine pipeline.
    Stages: sync_lines → sync_suppliers → compute_metrics → build_mapping
            → snapshot → buyer_perf → alerts.
    """
    run = ProcurementEngineRun.objects.create(
        period_days=lookback_days,
        triggered_by=triggered_by,
        status='running',
    )
    logger.info(f'[ProcurementEngine] Starting run #{run.pk} (lookback={lookback_days}d)')

    try:
        # ── Existing pipeline ───────────────────────────────────────────────
        sync_purchase_lines(run, lookback_days)

        # v2 Stage 1.5 — FOC detection, return type, effective cost
        enrich_purchase_lines(run, lookback_days)

        sync_supplier_profiles(run)

        # v2 Stage 2.5 — supplier segmentation
        classify_supplier_segments(run)

        compute_supplier_metrics(run)

        # v2 Stage 3.5 — enhanced scoring (FOC + tax dimensions)
        compute_enhanced_scores(run)

        build_supplier_item_mapping(run)
        compute_snapshot(run)
        compute_buyer_performance(run)
        generate_alerts(run)

        # v2 Stage 7.5 — advanced alerts (FOC, tax, expiry, patient, warehouse)
        adv_alerts = generate_advanced_alerts(run)
        run.alerts_generated = (run.alerts_generated or 0) + adv_alerts
        run.save(update_fields=['alerts_generated'])

        run.finish('success')
        logger.info(f'[ProcurementEngine] Run #{run.pk} completed successfully')
    except Exception as e:
        logger.exception(f'[ProcurementEngine] Run #{run.pk} failed: {e}')
        run.finish('failed', str(e))

    return run
