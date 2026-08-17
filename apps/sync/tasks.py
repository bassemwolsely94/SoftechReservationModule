"""
apps/sync/tasks.py
Sync engine: reads from Sybase ASE 12.5 → writes to PostgreSQL.
Runs every 5 minutes via APScheduler.
ABSOLUTE RULE: NEVER INSERT/UPDATE/DELETE on any Sybase connection.

Performance strategy (per-table):
  • Pre-load all lookup dicts (item_map, branch_map, etc.) ONCE before the loop
    instead of issuing a SELECT per row (eliminates N+1 queries entirely).
  • Use bulk_create(update_conflicts=True) which PostgreSQL executes as a single
    batched INSERT … ON CONFLICT (unique_key) DO UPDATE — one round-trip per
    batch of 500–1000 rows instead of one round-trip per row.
  Expected speedup: ~20–30× (sync_stock alone drops from ~390,000 queries to ~130).
"""
import datetime as _dt
from decimal import Decimal
import logging
from collections import defaultdict

from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone

from config.sybase import get_sybase_connection
from apps.sync.sybase_queries import (
    QUERY_BRANCHES, QUERY_CATEGORIES, QUERY_ITEMS, QUERY_STOCK,
    QUERY_CUSTOMERS, QUERY_CUSTOMER_PHONES,
    QUERY_PERSONTYPES, QUERY_PERSONTYPESCLASSIF,
    QUERY_CUSTOMER_SALES_LINES_RECENT, QUERY_CUSTOMER_SALES_LINES_FULL,
    QUERY_USERS,
    QUERY_ITEMSPRODUCERS, QUERY_ITEMSUNITS, QUERY_ITEMSHAPE,
    QUERY_ITEMSORIGIN, QUERY_ITEMSEFFECT, QUERY_ITEMSEFFECT2,
    QUERY_ACTIVE_INGREDIENTS, QUERY_ITEMSAI,
    QUERY_CUSTDISCPCLASSIF,
    QUERY_ITEM_BARCODES,
)
from apps.catalog.models import Item, Category, ItemStock, ItemBarcode
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.branches.models import Branch
from apps.sync.models import SyncRun, SyncLog
from apps.reservations.signals import check_stock_for_pending_reservations

logger = logging.getLogger('elrezeiky.sync')


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_decimal(val):
    try:
        return Decimal(str(val)) if val is not None else Decimal('0')
    except Exception:
        return Decimal('0')


def _to_date(val):
    if val is None:
        return None
    if isinstance(val, _dt.datetime):
        return val.date()
    if isinstance(val, _dt.date):
        return val
    return None


def _aware(dt):
    """
    Make a naive SOFTECH datetime timezone-aware in the project default zone
    (Africa/Cairo). SOFTECH stores wall-clock Cairo local time; saving it naive
    under USE_TZ=True triggers a RuntimeWarning and — if a non-Cairo timezone is
    ever active on the thread — would misinterpret the value. Localising to the
    DEFAULT zone (never the per-thread current zone) makes storage correct and
    stable regardless of request context. None / already-aware values pass through.
    """
    if not isinstance(dt, _dt.datetime):
        return None
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_default_timezone())


# ── main entry point ──────────────────────────────────────────────────────────

def run_full_sync(full_history=False):
    """
    Main sync entry point. Called by scheduler every 5 minutes.
    Pass full_history=True for the initial backfill (90 days of sales).
    """
    sync_run = SyncRun.objects.create(status='running')
    total = 0
    try:
        conn = get_sybase_connection()

        total += sync_branches(conn, sync_run)
        total += sync_categories(conn, sync_run)
        total += sync_items(conn, sync_run)
        total += sync_item_barcodes(conn, sync_run)
        total += sync_stock(conn, sync_run)
        total += sync_customers(conn, sync_run)
        total += sync_sales(conn, sync_run, full_history=full_history)
        total += sync_users(conn, sync_run)
        total += _maybe_sync_permissions(conn, sync_run)

        conn.close()

        sync_run.status = 'success'
        sync_run.records_synced = total
        sync_run.completed_at = timezone.now()
        sync_run.save()

        # run_full_sync touches BOTH master data and fast-changing data, so it
        # fires both hook sets (same helpers the tiered lanes use).
        _run_master_hooks()
        _run_reactive_hooks()

        logger.info(f"Sync complete — {total} records synced in "
                    f"{(timezone.now() - sync_run.started_at).seconds}s")

    except Exception as e:
        sync_run.status = 'failed'
        sync_run.error_message = str(e)
        sync_run.completed_at = timezone.now()
        sync_run.save()
        logger.error(f"Sync failed: {e}", exc_info=True)

    return sync_run


# ── Tiered sync lanes ─────────────────────────────────────────────────────────
# run_full_sync (above) pulls EVERYTHING and is used for the manual trigger and
# the initial backfill. For the scheduled cadence we split the work into two
# lanes so the expensive full snapshots (items ~40s, customers ~100s) don't run
# on every tick:
#   • run_fast_sync — stock + sales, every SYNC_FAST_MINUTES (default 5)
#   • run_slow_sync — items/customers/etc, every SYNC_SLOW_MINUTES (default 60)
# The lanes share the exact same sync_* step functions and post-hook helpers as
# run_full_sync, so there is no behavioural divergence — only scheduling.
#
# Eventual consistency note: sync_sales(RECENT) re-pulls today+yesterday every
# run and skips lines whose customer/item isn't in the local map yet. A brand-new
# customer's or item's first sale is therefore skipped once and re-caught on the
# next fast tick after the slow lane imports them — no data is lost, worst-case
# delay is one slow interval.

def _maybe_sync_permissions(conn, sync_run):
    """
    ERP permission mirror — picks up new SOFTECH permission grants. Permissions
    change rarely, so refresh at most hourly to avoid a 5.5k-row upsert on every
    tick. Never breaks the caller if it fails. Returns rows synced (0 if skipped).
    """
    try:
        from apps.users.models import ErpGroupPermission
        from datetime import timedelta
        last = ErpGroupPermission.objects.order_by('-synced_at').values_list('synced_at', flat=True).first()
        if last is None or (timezone.now() - last) >= timedelta(minutes=60):
            n = sync_erp_permissions(conn, sync_run)
            # Re-derive platform module permissions (SOFTECH authoritative)
            try:
                from apps.users.erp_permissions import seed_system_map, derive_group_permissions
                seed_system_map()           # no-op once seeded
                derive_group_permissions()
            except Exception as der_err:
                logger.warning(f"ERP permission derivation skipped: {der_err}")
            return n
    except Exception as perm_err:
        logger.warning(f"ERP permission sync skipped: {perm_err}")
    return 0


def _run_reactive_hooks():
    """
    Post-sync hooks that react to fast-changing STOCK/SALES data. Run after every
    fast (and full) sync. Each is independently guarded — one failing never breaks
    the others or the sync.
    """
    check_stock_for_pending_reservations()

    # Fire stock-available notifications
    try:
        from django.core import management
        management.call_command('notify_stock_available', verbosity=0)
    except Exception as notif_err:
        logger.warning(f"Stock notification hook failed: {notif_err}")

    # Back-in-stock recovery: flag demand lines whose wanted item is now in stock.
    try:
        from apps.demand.service import detect_restocked_demand
        flagged = detect_restocked_demand()
        if flagged:
            logger.info(f"Demand recovery: {flagged} line(s) flagged back-in-stock")
    except Exception as rec_err:
        logger.warning(f"Demand recovery sweep failed (non-fatal): {rec_err}")


def _run_master_hooks():
    """
    Post-sync hooks tied to MASTER data (customers/items/finance). Run after every
    slow (and full) sync. Each is independently guarded.
    """
    # Invalidate the analytics channel-label cache so fresh ptclassifcode labels
    # from persontypesclassif are reflected immediately.
    try:
        import apps.analytics.views as _av
        _av._channel_label_cache = None
        _av._person_type_label_cache = None
    except Exception:
        pass

    # Current-month finance snapshots (snapshot-only, no journal scan).
    try:
        _sync_finance_snapshots()
    except Exception as fin_err:
        logger.warning(f"Finance snapshot post-sync failed (non-fatal): {fin_err}")

    # Poll pending ERP match verifications.
    try:
        _poll_erp_matches()
    except Exception as erp_err:
        logger.warning(f"ERP match polling failed (non-fatal): {erp_err}")

    # Sync SOFTECH PIC points balances into LoyaltyAccount.softech_points_balance.
    # (_award_loyalty_points_for_recent_purchases is DISABLED — SOFTECH awards
    # purchase points natively; awarding here would double-count.)
    try:
        _sync_softech_points_balances()
    except Exception as loyalty_err:
        logger.warning('softech_points_sync failed (non-fatal): %s', loyalty_err)


def run_fast_sync():
    """
    FAST lane (default every 5 min): fast-changing data only — stock + sales —
    plus the reactive stock hooks. branches is included because it's instant and
    keeps branch_map fresh so new-branch stock/sales rows resolve their FK.
    """
    sync_run = SyncRun.objects.create(status='running')
    total = 0
    try:
        conn = get_sybase_connection()
        total += sync_branches(conn, sync_run)
        total += sync_stock(conn, sync_run)
        total += sync_sales(conn, sync_run, full_history=False)
        conn.close()

        sync_run.status = 'success'
        sync_run.records_synced = total
        sync_run.completed_at = timezone.now()
        sync_run.save()

        _run_reactive_hooks()
        logger.info(f"Fast sync complete — {total} records in "
                    f"{(timezone.now() - sync_run.started_at).seconds}s")
    except Exception as e:
        sync_run.status = 'failed'
        sync_run.error_message = str(e)
        sync_run.completed_at = timezone.now()
        sync_run.save()
        logger.error(f"Fast sync failed: {e}", exc_info=True)
    return sync_run


def run_slow_sync():
    """
    SLOW lane (default every 60 min): expensive, slow-changing master data —
    categories, items, barcodes, customers, users, permissions — plus the master
    post-hooks. This carries the heavy full-snapshot cost that used to run on
    every tick.
    """
    sync_run = SyncRun.objects.create(status='running')
    total = 0
    try:
        conn = get_sybase_connection()
        total += sync_categories(conn, sync_run)
        total += sync_items(conn, sync_run)
        total += sync_item_barcodes(conn, sync_run)
        total += sync_customers(conn, sync_run)
        total += sync_users(conn, sync_run)
        total += _maybe_sync_permissions(conn, sync_run)
        conn.close()

        sync_run.status = 'success'
        sync_run.records_synced = total
        sync_run.completed_at = timezone.now()
        sync_run.save()

        _run_master_hooks()
        logger.info(f"Slow sync complete — {total} records in "
                    f"{(timezone.now() - sync_run.started_at).seconds}s")
    except Exception as e:
        sync_run.status = 'failed'
        sync_run.error_message = str(e)
        sync_run.completed_at = timezone.now()
        sync_run.save()
        logger.error(f"Slow sync failed: {e}", exc_info=True)
    return sync_run


def _probe_network_health():
    """Scheduler entry point — probe HQ + all operational branches. Never raises."""
    try:
        from apps.sync.network_health import probe_all_nodes
        probe_all_nodes(record=True)
    except Exception as exc:
        logger.warning('[network_health] probe job failed (non-fatal): %s', exc)


# ── sync_branches ─────────────────────────────────────────────────────────────

def sync_branches(conn, sync_run):
    """
    Real columns: branchcode, branchname, branchename, branchaddress, branchphones
    No bractive column — all branches imported as active.
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_BRANCHES)
    count = 0
    for row in cursor.fetchall():
        try:
            name_en = str(row[2] or row[1] or '')
            name_ar = str(row[1] or '')
            branch, created = Branch.objects.get_or_create(
                softech_branch_id=str(row[0]),
                defaults={
                    'name': name_en or name_ar,
                    'name_ar': name_ar,
                    'code': str(row[0]),
                    'address': str(row[3] or ''),
                    'phone': str(row[4] or ''),
                    'is_active': True,
                }
            )
            if not created:
                # Only sync the canonical ERP fields on subsequent runs.
                # name_ar / address / phone are admin-managed — never overwrite them.
                # is_active / kind / pos_enabled are ALSO admin-curated (SOFTECH has
                # no active flag) — never clobber them here, or closed branches would
                # be silently re-activated every sync.
                branch.name = name_en or name_ar
                branch.code = str(row[0])
                branch.save(update_fields=['name', 'code'])
            count += 1
        except Exception as e:
            logger.warning(f"Branch sync error branchcode={row[0]}: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='branches', records_processed=count)
    logger.info(f"Branches synced: {count}")
    return count


# ── sync_categories ───────────────────────────────────────────────────────────

def sync_categories(conn, sync_run):
    """
    Real columns: itemsclassifcode, itemsclassifname, classifnamearabic
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_CATEGORIES)
    rows = cursor.fetchall()

    objs = []
    for row in rows:
        try:
            objs.append(Category(
                softech_id=str(row[0]),
                name=str(row[1] or ''),
                name_ar=str(row[2] or ''),
            ))
        except Exception as e:
            logger.warning(f"Category build error: {e}")

    count = len(objs)
    if objs:
        Category.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['softech_id'],
            update_fields=['name', 'name_ar'],
            batch_size=500,
        )
    SyncLog.objects.create(sync_run=sync_run, table_name='itemsclassif', records_processed=count)
    logger.info(f"Categories synced: {count}")
    return count


# ── sync_items ────────────────────────────────────────────────────────────────

def sync_items(conn, sync_run):
    """
    Sync SOFTECHDB9.dbo.items → catalog.Item.

    All classification lookups are pre-loaded as dicts before the item loop
    (zero N+1 queries). New fields added:
      shape (dosage form), origin (country), effect/effect2 (indications),
      unit (pack sub-unit type), active_ingredients (from itemsai junction).
    """
    cursor = conn.cursor()

    # ── 1. personsdata: personcode → personname (supplier name resolution) ───
    person_names: dict[str, str] = {}
    try:
        cursor.execute(
            "SELECT personcode, personname FROM SOFTECHDB9.dbo.personsdata"
            " WHERE personname IS NOT NULL"
        )
        for r in cursor.fetchall():
            code = str(r[0] or '').strip()
            if code:
                person_names[code] = str(r[1] or '').strip()
        logger.info(f"[sync_items] personsdata loaded: {len(person_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] personsdata lookup failed: {exc}")

    # ── 2. itemssuppliers: itemcode → primary suppcode (main_supp='1') ───────
    item_supplier_map: dict[str, str] = {}
    try:
        cursor.execute(
            "SELECT itemcode, suppcode FROM SOFTECHDB9.dbo.itemssuppliers"
            " WHERE main_supp = '1'"
        )
        for r in cursor.fetchall():
            icode = str(r[0] or '').strip()
            scode = str(r[1] or '').strip()
            if icode and scode:
                item_supplier_map[icode] = scode
        logger.info(f"[sync_items] itemssuppliers loaded: {len(item_supplier_map)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemssuppliers lookup failed: {exc}")

    # ── 3. itemsfamily: familycode → (en_name, ar_name) ─────────────────────
    family_names: dict[str, tuple[str, str]] = {}
    try:
        cursor.execute(
            "SELECT familycode, familyname, familynamearabic"
            " FROM SOFTECHDB9.dbo.itemsfamily"
            " WHERE familyname IS NOT NULL AND familyname != ''"
        )
        for r in cursor.fetchall():
            code = str(r[0] or '').strip()
            if code and code not in family_names:
                family_names[code] = (str(r[1] or '').strip(), str(r[2] or '').strip())
        logger.info(f"[sync_items] itemsfamily loaded: {len(family_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemsfamily lookup failed: {exc}")

    # ── 4. itemsproducers: itemproducercode → itemproducername ───────────────
    # itemsproducers is a SIMPLE LOOKUP TABLE (not a mapping table).
    # items.itemproducercode (col 31 of QUERY_ITEMS [16]) is the FK.
    producer_names: dict[str, str] = {}
    try:
        cur2 = conn.cursor()
        cur2.execute(QUERY_ITEMSPRODUCERS)
        for r in cur2.fetchall():
            code = str(r[0] or '').strip()
            name = str(r[1] or '').strip()
            if code and name:
                producer_names[code] = name
        logger.info(f"[sync_items] itemsproducers loaded: {len(producer_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemsproducers lookup failed: {exc}")

    # ── 5. itemstree: cdlcode → (en_name, ar_name)  (medicine category) ─────
    medicine_names: dict[str, tuple[str, str]] = {}
    try:
        cursor.execute(
            "SELECT cdlcode, cdldescr, cdldescrar FROM SOFTECHDB9.dbo.itemstree"
            " WHERE cdldescr IS NOT NULL AND cdldescr != ''"
        )
        for r in cursor.fetchall():
            code = str(r[0] or '').strip()
            if code:
                medicine_names[code] = (str(r[1] or '').strip(), str(r[2] or '').strip())
        logger.info(f"[sync_items] itemstree loaded: {len(medicine_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemstree lookup failed: {exc}")

    # ── 6. itemshape: itemshapecode → (en_name, ar_name)  (dosage form) ──────
    shape_names: dict[str, tuple[str, str]] = {}
    try:
        cur3 = conn.cursor()
        cur3.execute(QUERY_ITEMSHAPE)
        for r in cur3.fetchall():
            code = str(r[0] or '').strip()
            if code:
                shape_names[code] = (str(r[1] or '').strip(), str(r[2] or '').strip())
        logger.info(f"[sync_items] itemshape loaded: {len(shape_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemshape lookup failed: {exc}")

    # ── 7. itemsorigin: itemorigincode → (en_name, ar_name, imported_flag) ───
    origin_data: dict[str, tuple[str, str, bool]] = {}
    try:
        cur4 = conn.cursor()
        cur4.execute(QUERY_ITEMSORIGIN)
        for r in cur4.fetchall():
            code = str(r[0] or '').strip()
            if code:
                origin_data[code] = (
                    str(r[1] or '').strip(),
                    str(r[2] or '').strip(),
                    str(r[3] or '') == '1',
                )
        logger.info(f"[sync_items] itemsorigin loaded: {len(origin_data)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemsorigin lookup failed: {exc}")

    # ── 8. itemseffect: itemeffectcode → (en_name, ar_name) ──────────────────
    effect_names: dict[str, tuple[str, str]] = {}
    try:
        cur5 = conn.cursor()
        cur5.execute(QUERY_ITEMSEFFECT)
        for r in cur5.fetchall():
            code = str(r[0] or '').strip()
            if code:
                effect_names[code] = (str(r[1] or '').strip(), str(r[2] or '').strip())
        logger.info(f"[sync_items] itemseffect loaded: {len(effect_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemseffect lookup failed: {exc}")

    # ── 9. itemseffect2: itemeffectcode2 → (en_name, ar_name) ────────────────
    effect2_names: dict[str, tuple[str, str]] = {}
    try:
        cur6 = conn.cursor()
        cur6.execute(QUERY_ITEMSEFFECT2)
        for r in cur6.fetchall():
            code = str(r[0] or '').strip()
            if code:
                effect2_names[code] = (str(r[1] or '').strip(), str(r[2] or '').strip())
        logger.info(f"[sync_items] itemseffect2 loaded: {len(effect2_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemseffect2 lookup failed: {exc}")

    # ── 10. itemsunits: unitcode → unitname ───────────────────────────────────
    unit_names: dict[str, str] = {}
    try:
        cur7 = conn.cursor()
        cur7.execute(QUERY_ITEMSUNITS)
        for r in cur7.fetchall():
            code = str(r[0] or '').strip()
            name = str(r[1] or '').strip()
            if code and name:
                unit_names[code] = name
        logger.info(f"[sync_items] itemsunits loaded: {len(unit_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] itemsunits lookup failed: {exc}")

    # ── 11. activeingredients + itemsai: itemcode → comma-sep AI names ───────
    ai_master: dict[int, str] = {}   # aicode → ainame
    item_ai_map: dict[str, list[str]] = {}   # itemcode → [ainame, ...]
    try:
        cur8 = conn.cursor()
        cur8.execute(QUERY_ACTIVE_INGREDIENTS)
        for r in cur8.fetchall():
            try:
                code = int(r[0])
                name = str(r[1] or '').strip()
                if name:
                    ai_master[code] = name
            except (TypeError, ValueError):
                pass
        logger.info(f"[sync_items] activeingredients loaded: {len(ai_master)} entries")

        cur9 = conn.cursor()
        cur9.execute(QUERY_ITEMSAI)
        for r in cur9.fetchall():
            icode = str(r[0] or '').strip()
            try:
                aicode = int(r[1])
            except (TypeError, ValueError):
                continue
            ai_name = ai_master.get(aicode, '')
            if icode and ai_name:
                item_ai_map.setdefault(icode, []).append(ai_name)
        logger.info(f"[sync_items] itemsai mapped: {len(item_ai_map)} items have AI data")
    except Exception as exc:
        logger.warning(f"[sync_items] active ingredients lookup failed: {exc}")

    # ── 12. custdiscpclassif: custdiscpcode → custdiscpdescr ─────────────────
    # Contract discount classification — items.itemstoreclassif FK
    store_classif_names: dict[str, str] = {}
    try:
        cur10 = conn.cursor()
        cur10.execute(QUERY_CUSTDISCPCLASSIF)
        for r in cur10.fetchall():
            code = str(r[0] or '').strip()
            name = str(r[1] or '').strip()
            if code and name:
                store_classif_names[code] = name
        logger.info(f"[sync_items] custdiscpclassif loaded: {len(store_classif_names)} entries")
    except Exception as exc:
        logger.warning(f"[sync_items] custdiscpclassif lookup failed: {exc}")

    # ── 13. Fetch items ───────────────────────────────────────────────────────
    cursor.execute(QUERY_ITEMS)
    rows = cursor.fetchall()

    cat_map = {c.softech_id: c.id for c in Category.objects.only('id', 'softech_id')}

    objs = []
    for row in rows:
        try:
            item_code     = str(row[0] or '').strip()
            # itemnomoreuse='1' → discontinued ("امر التوريد"). Synced but inactive.
            no_more_use   = str(row[8] or '0').strip() == '1'
            # itemarchive=1 → archived (distinct from no_more_use). Also inactive.
            item_archive  = str(row[9] or '0').strip() == '1'
            family_code   = str(row[10] or '').strip()
            med_code      = str(row[12] or '').strip()
            producer_code = str(row[16] or '').strip() if len(row) > 16 else ''
            unit_code     = str(row[17] or '').strip() if len(row) > 17 else ''
            shape_code    = str(row[18] or '').strip() if len(row) > 18 else ''
            origin_code   = str(row[19] or '').strip() if len(row) > 19 else ''
            effect_code   = str(row[20] or '').strip() if len(row) > 20 else ''
            effect_code2  = str(row[21] or '').strip() if len(row) > 21 else ''
            is_stockable    = (int(row[22] or 0) == 1) if len(row) > 22 else True
            insurance_type  = str(row[23] or '').strip() if len(row) > 23 else ''
            item_level      = int(row[24] or 0) if len(row) > 24 else 0
            has_points      = (int(row[25] or 0) == 1) if len(row) > 25 else False
            pack_qty        = max(1, int(row[26] or 1)) if len(row) > 26 else 1
            branch_trans    = str(int(row[27] or 0)) if len(row) > 27 else ''
            supplier_trans  = str(int(row[28] or 0)) if len(row) > 28 else ''
            customer_trans  = str(int(row[29] or 0)) if len(row) > 29 else ''
            nosale_classif  = str(row[30] or '').strip() if len(row) > 30 else ''
            is_fast_moving  = (str(row[31] or '0').strip() == '1') if len(row) > 31 else False
            store_classif   = str(row[32] or '').strip() if len(row) > 32 else ''
            pharmacy_discp   = _to_decimal(row[33]) if len(row) > 33 else Decimal('0')
            additional_discp = _to_decimal(row[34]) if len(row) > 34 else Decimal('0')
            special_discp    = _to_decimal(row[35]) if len(row) > 35 else Decimal('0')
            pos_discp        = _to_decimal(row[36]) if len(row) > 36 else Decimal('0')
            pack_price_tax   = _to_decimal(row[37]) if len(row) > 37 else Decimal('0')
            sale_tax_pct     = _to_decimal(row[38]) if len(row) > 38 else Decimal('0')

            # Supplier: itemssuppliers (main_supp='1') overrides items.suppcode
            raw_supp_code = str(row[5] or '').strip()
            supp_code     = item_supplier_map.get(item_code, raw_supp_code)
            supp_name     = person_names.get(supp_code, '')

            # Producer: direct lookup via items.itemproducercode → itemsproducers
            prod_name = producer_names.get(producer_code, '')

            store_classif_name = store_classif_names.get(store_classif, '') if store_classif else ''
            fam_name_en, fam_name_ar = family_names.get(family_code, ('', '')) if family_code else ('', '')
            med_name_en, med_name_ar = medicine_names.get(med_code, ('', ''))
            shp_name_en, shp_name_ar = shape_names.get(shape_code, ('', '')) if shape_code else ('', '')
            orig_en, orig_ar, is_imported = origin_data.get(origin_code, ('', '', False)) if origin_code else ('', '', False)
            eff_en, eff_ar = effect_names.get(effect_code, ('', '')) if effect_code else ('', '')
            eff2_en, eff2_ar = effect2_names.get(effect_code2, ('', '')) if effect_code2 else ('', '')
            unit_name = unit_names.get(unit_code, '') if unit_code else ''
            ai_csv = ', '.join(item_ai_map.get(item_code, []))

            # items.itembarcode is char(15) — strip spaces then exclude '0' placeholder
            raw_barcode = str(row[3] or '').strip()
            barcode_val = raw_barcode if raw_barcode and raw_barcode not in ('0', '00', '000') else ''

            objs.append(Item(
                softech_id=item_code,
                name=row[1] or '',
                name_scientific=row[2] or '',
                barcode=barcode_val,
                category_id=cat_map.get(str(row[4])) if row[4] else None,
                supplier_code=supp_code,
                supplier_name=supp_name,
                producer_code=producer_code,
                producer_name=prod_name,
                pack_price=_to_decimal(row[6]),   # itemsaleprice  — full-pack retail price
                unit_price=_to_decimal(row[7]),   # unitsaleprice  — per-unit/strip price
                cost_price=_to_decimal(row[15]),  # itemcostprice  — current catalog cost
                family_code=family_code,
                family_name=fam_name_en,
                family_name_ar=fam_name_ar,
                requires_fridge=row[11] == '1',
                medicine_type=med_code,
                medicine_type_name=med_name_en,
                medicine_type_name_ar=med_name_ar,
                shape_code=shape_code,
                shape_name=shp_name_en,
                shape_name_ar=shp_name_ar,
                origin_code=origin_code,
                origin_name=orig_en,
                origin_name_ar=orig_ar,
                is_imported=is_imported,
                effect_code=effect_code,
                effect_name=eff_en,
                effect_name_ar=eff_ar,
                effect_code2=effect_code2,
                effect_name2=eff2_en,
                effect_name2_ar=eff2_ar,
                unit_code=unit_code,
                unit_name=unit_name,
                active_ingredients=ai_csv,
                comment=row[13] or '',
                is_active=not (no_more_use or item_archive),   # discontinued OR archived → inactive
                no_more_use=no_more_use,
                item_archive=item_archive,
                is_stockable=is_stockable,
                is_fast_moving=is_fast_moving,
                insurance_type=insurance_type,
                item_level=item_level,
                has_points=has_points,
                pack_qty=pack_qty,
                branch_trans=branch_trans,
                supplier_trans=supplier_trans,
                customer_trans=customer_trans,
                nosale_classif=nosale_classif,
                store_classif=store_classif,
                store_classif_name=store_classif_name,
                pharmacy_discp=pharmacy_discp,
                additional_discp=additional_discp,
                special_discp=special_discp,
                pos_discp=pos_discp,
                pack_price_tax=pack_price_tax,
                sale_tax_pct=sale_tax_pct,
            ))
        except Exception as e:
            logger.warning(f"Item build error itemcode={row[0]}: {e}")

    objs = list({o.softech_id: o for o in objs}.values())
    count = len(objs)
    if objs:
        Item.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['softech_id'],
            update_fields=[
                'name', 'name_scientific', 'barcode', 'category_id',
                'supplier_code', 'supplier_name',
                'producer_code', 'producer_name',
                'pack_price', 'unit_price', 'cost_price',
                'family_code', 'family_name', 'family_name_ar',
                'requires_fridge',
                'medicine_type', 'medicine_type_name', 'medicine_type_name_ar',
                'shape_code', 'shape_name', 'shape_name_ar',
                'origin_code', 'origin_name', 'origin_name_ar', 'is_imported',
                'effect_code', 'effect_name', 'effect_name_ar',
                'effect_code2', 'effect_name2', 'effect_name2_ar',
                'unit_code', 'unit_name',
                'active_ingredients',
                'comment', 'is_active', 'no_more_use', 'item_archive', 'is_stockable',
                'is_fast_moving', 'insurance_type', 'item_level', 'has_points',
                'pack_qty', 'branch_trans', 'supplier_trans', 'customer_trans',
                'nosale_classif',
                'store_classif', 'store_classif_name',
                'pharmacy_discp', 'additional_discp', 'special_discp', 'pos_discp',
                'pack_price_tax', 'sale_tax_pct',
            ],
            batch_size=500,
        )
    SyncLog.objects.create(sync_run=sync_run, table_name='items', records_processed=count)
    logger.info(f"Items synced: {count}")
    return count


# ── sync_item_barcodes ────────────────────────────────────────────────────────

def sync_item_barcodes(conn, sync_run):
    """
    Sync all EAN-13 / GS1 / international barcodes from SOFTECHDB9.dbo.itembarcodes.
    One item can have many barcodes. Inactive barcodes (obsolete='1') are preserved
    with is_active=False so scanners can still identify products by old barcodes.

    SAFETY: SELECT-only from Sybase. Writes go to PostgreSQL only.
    Wrapped in try/except — if the itembarcodes table has a different schema on
    this SOFTECH instance, the sync continues without barcodes (non-fatal).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(QUERY_ITEM_BARCODES)
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(
            f'sync_item_barcodes: itembarcodes query failed (table may have different '
            f'column names on this SOFTECH instance). Error: {e}'
        )
        return 0

    if not rows:
        logger.info('sync_item_barcodes: 0 rows returned from itembarcodes table')
        return 0

    # Build item_map once — avoids N+1 queries
    item_map = {row.softech_id: row.id for row in Item.objects.only('id', 'softech_id')}

    to_upsert = []
    seen = set()
    for row in rows:
        item_code    = str(row[0] or '').strip()
        barcode      = str(row[1] or '').strip()   # itembarcode column
        block_flag   = str(row[2] or '0').strip()  # blockbarcode: '1'=blocked/inactive
        is_active    = (block_flag != '1')

        item_id = item_map.get(item_code)
        if not item_id or not barcode:
            continue

        key = (item_id, barcode)
        if key in seen:
            continue
        seen.add(key)

        to_upsert.append(ItemBarcode(item_id=item_id, barcode=barcode, is_active=is_active))

    if not to_upsert:
        return 0

    ItemBarcode.objects.bulk_create(
        to_upsert,
        update_conflicts=True,
        unique_fields=['item', 'barcode'],
        update_fields=['is_active'],
        batch_size=1000,
    )
    count = len(to_upsert)
    SyncLog.objects.create(sync_run=sync_run, table_name='itembarcodes', records_processed=count)
    logger.info(f'sync_item_barcodes: {count} barcodes upserted')
    return count


# ── sync_stock ────────────────────────────────────────────────────────────────

def sync_stock(conn, sync_run):
    """
    stkbal PK: storecode + itemcode + branchcode
    Quantity column: nowqty

    Optimisation: this is the largest table (~130k+ rows).
    Old approach: 3 queries × 130k rows ≈ 390,000 DB round-trips → ~6 min.
    New approach: 2 pre-load queries + batched bulk INSERT … ON CONFLICT → ~10 sec.
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_STOCK)
    rows = cursor.fetchall()

    # Pre-load lookup dicts ONCE — avoids N+1 entirely
    item_map   = {i.softech_id: i.id   for i in Item.objects.only('id', 'softech_id')}
    branch_map = {b.softech_branch_id: b.id for b in Branch.objects.only('id', 'softech_branch_id')}

    objs = []
    skipped = 0
    for row in rows:
        item_id   = item_map.get(str(row[0]))
        branch_id = branch_map.get(str(row[1]))
        if not item_id or not branch_id:
            skipped += 1
            continue
        try:
            objs.append(ItemStock(
                item_id=item_id,
                branch_id=branch_id,
                softech_store_code=str(row[2]),
                quantity_on_hand=_to_decimal(row[3]),
                monthly_qty=_to_decimal(row[4]),
                on_order_qty=_to_decimal(row[5]),
            ))
        except Exception as e:
            logger.warning(f"Stock build error itemcode={row[0]}: {e}")

    # Deduplicate on composite key — last-seen wins
    objs = list(
        {(o.item_id, o.branch_id, o.softech_store_code): o for o in objs}.values()
    )
    count = len(objs)
    if objs:
        ItemStock.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['item', 'branch', 'softech_store_code'],
            update_fields=['quantity_on_hand', 'monthly_qty', 'on_order_qty'],
            batch_size=1000,
        )
    if skipped:
        logger.debug(f"Stock: skipped {skipped} rows (item or branch not found yet)")
    SyncLog.objects.create(sync_run=sync_run, table_name='stkbal', records_processed=count)
    logger.info(f"Stock synced: {count}")
    return count


# ── sync_customers ────────────────────────────────────────────────────────────

def sync_customers(conn, sync_run):
    """
    Sync SOFTECHDB9.dbo.localcustomers → Customer.

    Row layout (QUERY_CUSTOMERS with LEFT JOIN personsdata):
      [0]  lc.branchcode
      [1]  lc.branchcustcode          (softech_id / per-branch sequential number)
      [2]  lc.branchcustname
      [3]  lc.branchcustaddress1
      [4]  lc.branchcustaddress2
      [5]  lc.custdofbirth
      [6]  lc.mobileno
      [7]  lc.branchcustphone
      [8]  lc.branchcustclassif       (branch-level fallback channel code)
      [9]  lc.ischronic
      [10] lc.phcode                  (PIC — global unique customer code)
      [11] lc.orderbranchcode         (default delivery/order branch)
      [12] pd.ptcode                  (person type — from personsdata; NULL if no PIC)
      [13] pd.ptclassifcode           (channel code — AUTHORITATIVE; falls back to row[8])
      [14] pd.personglobalcode        (global person code from personsdata)

    Person-type lookups:
      persontypes       ptcode → ptdescr (Arabic label, e.g. '01' → 'عميل')
      persontypesclassif (ptcode, ptclassifcode) → ptclassifdescr (channel label)
    """
    # ── Pre-load person-type label lookups ────────────────────────────────────
    pt_map: dict = {}   # ptcode → ptdescr
    pc_map: dict = {}   # (ptcode, ptclassifcode) → ptclassifdescr
    pc_by_classif: dict = {}  # ptclassifcode → ptclassifdescr (fallback, ignores ptcode)
    try:
        pt_cur = conn.cursor()
        pt_cur.execute(QUERY_PERSONTYPES)
        for r in pt_cur.fetchall():
            code = str(r[0] or '').strip()
            if code:
                pt_map[code] = str(r[1] or '').strip()   # ptdescr (Arabic)

        pc_cur = conn.cursor()
        pc_cur.execute(QUERY_PERSONTYPESCLASSIF)
        for r in pc_cur.fetchall():
            ptcode  = str(r[0] or '').strip()
            clsf    = str(r[1] or '').strip()
            label   = str(r[2] or '').strip()
            if ptcode and clsf:
                pc_map[(ptcode, clsf)] = label
            if clsf and clsf not in pc_by_classif:
                pc_by_classif[clsf] = label   # first occurrence wins (usually ptcode='01')

        logger.info(
            f"Loaded {len(pt_map)} person types, {len(pc_map)} person classif labels"
        )

        # ── Persist label caches so analytics can resolve labels without a re-sync ──
        try:
            from apps.sync.models import SoftechPersonType, SoftechPersonClassif

            # person types
            pt_objs = [
                SoftechPersonType(ptcode=code, ptdescr=label)
                for code, label in pt_map.items() if code
            ]
            if pt_objs:
                SoftechPersonType.objects.bulk_create(
                    pt_objs,
                    update_conflicts=True,
                    unique_fields=['ptcode'],
                    update_fields=['ptdescr'],
                )

            # person classif (channel labels)
            pc_full: dict = {}  # (ptcode, ptclassifcode) → label  (from pc_map which already has full key)
            for (ptcode, clsf), label in pc_map.items():
                pc_full[(ptcode, clsf)] = label

            pc_objs = [
                SoftechPersonClassif(ptcode=ptcode, ptclassifcode=clsf, ptclassifdescr=label)
                for (ptcode, clsf), label in pc_full.items()
                if ptcode and clsf
            ]
            if pc_objs:
                SoftechPersonClassif.objects.bulk_create(
                    pc_objs,
                    update_conflicts=True,
                    unique_fields=['ptcode', 'ptclassifcode'],
                    update_fields=['ptclassifdescr'],
                )
            logger.info(
                f"PersonType/Classif label cache: {len(pt_objs)} types, {len(pc_objs)} classifs"
            )
        except Exception as cache_err:
            logger.warning(f"Failed to persist person-type label caches: {cache_err}")

    except Exception as lookup_err:
        logger.warning(f"Person-type lookup pre-load failed: {lookup_err}")

    # ── Pre-load all phones from personphones keyed by PIC (phcode) ───────────
    pic_phone_map: dict = {}  # phcode → [primary_phone, alt_phone, ...]
    try:
        ph_cur = conn.cursor()
        ph_cur.execute(QUERY_CUSTOMER_PHONES)
        for ph_row in ph_cur.fetchall():
            pic   = str(ph_row[0] or '').strip()
            phone = str(ph_row[1] or '').strip()
            if pic and phone:
                pic_phone_map.setdefault(pic, []).append(phone)
        logger.info(f"Loaded phones for {len(pic_phone_map)} PICs from personphones")
    except Exception as ph_err:
        logger.warning(f"personphones pre-load failed (falling back to mobileno): {ph_err}")

    cursor = conn.cursor()
    cursor.execute(QUERY_CUSTOMERS)
    rows = cursor.fetchall()

    branch_map = {
        b.softech_branch_id: b.id
        for b in Branch.objects.only('id', 'softech_branch_id')
    }

    objs = []
    synced_phones = set()   # used for batch guest-merge

    for row in rows:
        try:
            branch_code  = str(row[0] or '').strip()
            raw_cust_num = row[1]
            cust_code    = str(int(float(raw_cust_num))) if raw_cust_num is not None else ''
            if not cust_code:
                continue

            # row[10] = lc.phcode — globally unique PIC (e.g. "12HD28")
            pic_code = str(row[10] or '').strip() if len(row) > 10 else ''
            pic_code = pic_code or None  # store None not '' — unique index allows multiple NULLs

            # Extra columns from LEFT JOIN personsdata (may be absent if QUERY_CUSTOMERS
            # is still the old version; guard with len(row) > N)
            order_branch  = str(row[11] or '').strip() if len(row) > 11 else ''
            pt_code       = str(row[12] or '').strip() if len(row) > 12 else ''
            pd_classif    = str(row[13] or '').strip() if len(row) > 13 else ''
            global_code   = str(row[14] or '').strip() if len(row) > 14 else ''

            # Channel: personsdata.ptclassifcode is the ONLY valid source.
            # localcustomers.branchcustclassif stores district/area codes (e.g. 'HD')
            # that do NOT map to persontypesclassif and MUST NOT be used as fallback.
            classif_code = pd_classif  # empty string if customer not in personsdata

            # Label lookups
            pt_label     = pt_map.get(pt_code, '')
            classif_label = (
                pc_map.get((pt_code, classif_code))
                or pc_by_classif.get(classif_code, '')
            )

            # Phones: personphones is primary; localcustomers.mobileno is fallback.
            pic_phones = pic_phone_map.get(pic_code, [])
            if pic_phones:
                phone  = pic_phones[0]
                phone2 = pic_phones[1] if len(pic_phones) > 1 else ''
            else:
                mobile   = str(row[6] or '').strip()
                landline = str(row[7] or '').strip()
                phone    = mobile or landline
                phone2   = landline if mobile else ''

            customer = Customer(
                softech_id=cust_code,
                softech_pic=pic_code,
                name=str(row[2] or '').strip(),
                address=f"{str(row[3] or '')} {str(row[4] or '')}".strip(),
                date_of_birth=_to_date(row[5]),
                preferred_branch_id=branch_map.get(branch_code),
                phone=phone,
                phone_alt=phone2,
                # Person-type tree (authoritative from personsdata)
                softech_ptcode=pt_code,
                softech_ptclassifcode=classif_code,
                person_type_label=pt_label,
                person_classif_label=classif_label,
                softech_global_code=global_code,
                order_branch_code=order_branch,
                is_guest=False,
            )
            if hasattr(Customer, 'is_chronic_softech'):
                customer.is_chronic_softech = bool(row[9])

            objs.append(customer)
            for p in (phone, phone2):
                if p:
                    synced_phones.add(p)

        except Exception as e:
            logger.warning(f"Customer build error branchcustcode={row[1]}: {e}")

    # ── Deduplicate by softech_pic (PIC is the true unique key) ─────────────────
    seen_pic: dict = {}   # softech_pic → obj
    seen_id:  dict = {}   # softech_id  → obj  (fallback for no-PIC records)
    for obj in objs:
        if obj.softech_pic:
            seen_pic[obj.softech_pic] = obj
        else:
            existing = seen_id.get(obj.softech_id)
            if existing is None or (not existing.phone and obj.phone):
                seen_id[obj.softech_id] = obj

    with_pic    = list(seen_pic.values())
    without_pic = list(seen_id.values())
    count       = len(with_pic) + len(without_pic)

    update_fields = [
        'softech_id', 'name', 'address', 'date_of_birth', 'preferred_branch_id',
        'phone', 'phone_alt',
        'softech_ptcode', 'softech_ptclassifcode',
        'person_type_label', 'person_classif_label',
        'softech_global_code', 'order_branch_code',
        'is_guest',
    ]
    if hasattr(Customer, 'is_chronic_softech'):
        update_fields.append('is_chronic_softech')

    if with_pic:
        Customer.objects.bulk_create(
            with_pic,
            update_conflicts=True,
            unique_fields=['softech_pic'],
            update_fields=update_fields,
            batch_size=2000,
        )
    if without_pic:
        Customer.objects.bulk_create(
            without_pic,
            update_conflicts=True,
            unique_fields=['softech_id'],
            update_fields=[f for f in update_fields if f != 'softech_id'],
            batch_size=2000,
        )

    # ── Batch guest-merge pass ────────────────────────────────────────────────
    # Instead of one per-row check, find all guest customers whose phones were
    # just synced in one query, then re-link their reservations in bulk.
    if synced_phones:
        try:
            from apps.reservations.models import Reservation as _R
            guests = list(
                Customer.objects.filter(is_guest=True, phone__in=synced_phones)
                .values('id', 'phone')
            )
            if guests:
                real_by_phone = {
                    c.phone: c.id
                    for c in Customer.objects.filter(
                        phone__in=[g['phone'] for g in guests],
                        is_guest=False,
                    ).only('id', 'phone')
                }
                merged = 0
                for guest in guests:
                    real_id = real_by_phone.get(guest['phone'])
                    if real_id:
                        updated = _R.objects.filter(customer_id=guest['id']).update(
                            customer_id=real_id
                        )
                        Customer.objects.filter(id=guest['id']).delete()
                        merged += 1
                if merged:
                    logger.info(f"Guest-merge: merged {merged} guest customers")
        except Exception as merge_err:
            logger.warning(f"Batch guest-merge error: {merge_err}")

    SyncLog.objects.create(
        sync_run=sync_run, table_name='localcustomers', records_processed=count
    )
    logger.info(f"Customers synced: {count}")
    return count


# ── sync_sales ────────────────────────────────────────────────────────────────

def sync_sales(conn, sync_run, full_history=False, query=None):
    """
    Purchase history from stktrans lines.
    Groups lines into invoices by (personcode, branchcode, doccode, docnumber, docdate).
    doccode '115' = sales, '30' = returns (negative qty).

    Optimisation strategy:
      • Pre-load customer/branch/item maps — zero per-row lookups.
      • Process invoices in batches of INVOICE_BATCH:
          1. bulk_create(update_conflicts) for PurchaseHistory headers
          2. One SELECT to reload their PKs
          3. One DELETE to wipe existing lines for those invoices
          4. bulk_create for the new lines
      • This replaces ~2 queries/invoice + ~2 queries/line with
        ~4 queries per batch of 1000 invoices.
    """
    INVOICE_BATCH = 1000

    cursor = conn.cursor()
    if query is None:
        query = QUERY_CUSTOMER_SALES_LINES_FULL if full_history else QUERY_CUSTOMER_SALES_LINES_RECENT
    # The stktrans⋈stktransm scan legitimately runs longer than the interactive
    # 30s default; without a generous timeout jConnect aborts fetchall() with
    # JZ0T3 (socket read timeout) and the whole sync fails. Bounded, not unlimited.
    from django.conf import settings as _settings
    cursor.execute(query, timeout=getattr(_settings, 'SYBASE_SYNC_QUERY_TIMEOUT', 300))
    rows = cursor.fetchall()

    if not rows:
        SyncLog.objects.create(sync_run=sync_run, table_name='stktrans', records_processed=0)
        return 0

    # ── Pre-load lookup dicts once ────────────────────────────────────────────
    customer_map = {
        c.softech_id: c.id
        for c in Customer.objects.filter(softech_id__isnull=False).only('id', 'softech_id')
    }

    # sm.ptcode [13] and sm.ptclassifcode [14] are read directly from each invoice row —
    # these are the AUTHORITATIVE source for sales channel (قناة البيع / نوع العميل).
    # No customer-side lookup needed; the classification is stamped on the invoice itself.

    branch_map = {b.softech_branch_id: b.id for b in Branch.objects.only('id', 'softech_branch_id')}
    item_map   = {i.softech_id: i.id   for i in Item.objects.only('id', 'softech_id')}

    # Group Sybase rows → invoice buckets.
    # docnumber is normalised to an integer string (Sybase may return it as
    # Decimal / float, e.g. 500123.0 → "500123") so the softech_invoice_id
    # never changes format between sync runs.
    def _norm_docnum(v):
        """'400022.0' → '400022'; '400022' → '400022'; None → 'nonum'."""
        if v is None:
            return 'nonum'
        try:
            return str(int(float(str(v))))
        except (ValueError, OverflowError):
            return str(v).strip()

    invoices = defaultdict(list)
    for row in rows:
        key = (
            str(row[0]).strip(),   # personcode
            str(row[1]),           # branchcode
            str(row[2]),           # doccode
            _norm_docnum(row[3]),  # docnumber — normalised integer string
            row[4],                # docdate
        )
        invoices[key].append(row)

    total_count = 0
    invoice_items = list(invoices.items())

    for batch_start in range(0, len(invoice_items), INVOICE_BATCH):
        batch = invoice_items[batch_start : batch_start + INVOICE_BATCH]

        header_by_invid = {}   # softech_invoice_id → PurchaseHistory (dedup within batch)
        lines_by_inv_id = {}   # softech_invoice_id → [(item_id, qty, price, total, cost)]

        for (personcode, branchcode, doccode, docnumber, docdate), lines in batch:
            # docnumber is already normalised (integer string) from the grouping step.
            try:
                customer_id = customer_map.get(personcode)
                branch_id   = branch_map.get(branchcode)
                if not customer_id or not branch_id:
                    continue

                # STABLE calendar-date key for the invoice id. docdate from SOFTECH is
                # a naive Cairo-local date (midnight); if a tz-aware value ever arrives,
                # localise it FIRST so the date never shifts across the UTC boundary —
                # otherwise the same invoice gets two ids (…-0530 / …-0531) and the
                # upsert can't dedupe, doubling every overlap-month invoice.
                if isinstance(docdate, _dt.datetime):
                    dd = timezone.localtime(docdate) if timezone.is_aware(docdate) else docdate
                    date_str = dd.strftime('%Y%m%d')
                else:
                    date_str = str(docdate)[:10].replace('-', '') if docdate else 'nodate'
                inv_id = f"{branchcode}-{doccode}-{docnumber}-{date_str}"

                total    = sum(_to_decimal(l[8]) for l in lines)
                usercode = next(
                    (str(l[10] or '').strip() for l in lines if len(l) > 10 and l[10]),
                    ''
                )
                # st.storecode — warehouse/store code (index 9); take from first line
                store_code = str(lines[0][9] or '').strip() if lines and len(lines[0]) > 9 else ''
                # sm.cust_branch_code — customer ordering branch (index 12); take first non-empty
                cust_branch_code = next(
                    (str(l[12] or '').strip() for l in lines if len(l) > 12 and l[12]),
                    ''
                )

                # sm.ptclassifcode [14] — AUTHORITATIVE channel code stamped on this invoice
                #   by SOFTECH at sale time (e.g. '91'=نقدى, '90'=Delivery, '10'=تعاقدات).
                # sm.ptcode        [13] — person-type code on this invoice (e.g. '10'=عميل).
                # sm.phcode        [11] — customer PIC (same as localcustomers.phcode, e.g.
                #   "01HD14"). Stored in softech_phcode so analytics can count distinct PICs
                #   from invoice data directly instead of traversing customer__softech_pic,
                #   which under-counts because personcode 1500/1510 (anonymous walk-in/delivery)
                #   all map to the same two Customer records regardless of the invoice PIC.
                channel     = str(lines[0][14] or '').strip() if len(lines[0]) > 14 else ''
                person_type = str(lines[0][13] or '').strip() if len(lines[0]) > 13 else ''
                phcode      = str(lines[0][11] or '').strip() if len(lines[0]) > 11 else ''

                # st.trans_time [16] — actual clock time of the transaction.
                # stktransm.docdate stores only the date (midnight), so hour-of-day
                # analytics must use trans_time instead. Take from the first line.
                raw_trans_time = lines[0][16] if len(lines[0]) > 16 else None
                trans_time = raw_trans_time if isinstance(raw_trans_time, _dt.datetime) else None

                line_tuples = []
                for l in lines:
                    item_id = item_map.get(str(l[5]))   # None if item not in catalog
                    # l[15] = st.newcostprice — running weighted-average cost at time of transaction.
                    # This is the authoritative COGS value; Item.cost_price diverges
                    # over time as catalog prices are updated on every sync.
                    # item_id may be None for archived/discontinued items — still save the
                    # line so revenue and COGS totals match SOFTECH exactly (item FK is nullable).
                    cost_at_sale = _to_decimal(l[15]) if len(l) > 15 else _to_decimal(0)
                    # [17] itemsaleprice(list) [18] pharmacydiscp [19] additionaldiscp
                    # [17] itemsaleprice (tax-INCLUSIVE list) [18] pharmacydiscp [19] additionaldiscp
                    # [20] custdiscp [21] specialdiscp — customer discount derived from list vs paid.
                    # (bonusqty removed: it's a PURCHASING column, not on sales 115/30.)
                    disc = lambda i: _to_decimal(l[i]) if len(l) > i else _to_decimal(0)
                    line_tuples.append((item_id, _to_decimal(l[6]),
                                        _to_decimal(l[7]), _to_decimal(l[8]),
                                        cost_at_sale,
                                        disc(17), disc(18), disc(19), disc(20), disc(21)))

                # Merge rows that collapse to the same softech_invoice_id within this
                # batch (invoice split across docdate time components / personcode) —
                # otherwise the ON CONFLICT upsert rejects the duplicate key.
                if inv_id in header_by_invid:
                    header_by_invid[inv_id].total_amount += total
                    lines_by_inv_id[inv_id].extend(line_tuples)
                else:
                    header_by_invid[inv_id] = PurchaseHistory(
                        softech_invoice_id=inv_id,
                        customer_id=customer_id,
                        branch_id=branch_id,
                        invoice_date=_aware(docdate),
                        trans_time=_aware(trans_time),
                        total_amount=total,
                        doc_code=doccode,
                        docnumber=docnumber,  # normalised integer string
                        softech_user=usercode,
                        sales_channel=channel,        # sm.ptclassifcode — e.g. '91', '90', '10'
                        sales_person_type=person_type, # sm.ptcode — e.g. '10', '11'
                        store_code=store_code,
                        cust_branch_code=cust_branch_code,
                        softech_phcode=phcode,         # sm.phcode — customer PIC per invoice
                    )
                    lines_by_inv_id[inv_id] = line_tuples

            except Exception as e:
                logger.warning(f"Sales build error: {e}")

        header_objs = list(header_by_invid.values())
        if not header_objs:
            continue

        # ── 1. Bulk upsert invoice headers ────────────────────────────────────
        PurchaseHistory.objects.bulk_create(
            header_objs,
            update_conflicts=True,
            unique_fields=['softech_invoice_id'],
            update_fields=[
                'customer_id', 'branch_id', 'invoice_date', 'trans_time',
                'total_amount', 'doc_code', 'docnumber', 'softech_user',
                'sales_channel', 'sales_person_type',
                'store_code', 'cust_branch_code',
                'softech_phcode',
            ],
            batch_size=500,
        )

        # ── 2. Reload PKs (bulk_create may not populate all PKs on upsert) ───
        inv_ids = [obj.softech_invoice_id for obj in header_objs]
        pk_map  = {
            h.softech_invoice_id: h.id
            for h in PurchaseHistory.objects.filter(
                softech_invoice_id__in=inv_ids
            ).only('id', 'softech_invoice_id')
        }

        # ── 3. Delete existing lines for these invoices ───────────────────────
        PurchaseHistoryLine.objects.filter(
            purchase_id__in=pk_map.values()
        ).delete()

        # ── 4. Bulk create fresh lines ────────────────────────────────────────
        line_objs = []
        for inv_id, line_tuples in lines_by_inv_id.items():
            pk = pk_map.get(inv_id)
            if not pk:
                continue
            for (l_item_id, qty, price, total, cost_at_sale,
                 list_price, dp_pharm, dp_addl, dp_cust, dp_spec) in line_tuples:
                line_objs.append(PurchaseHistoryLine(
                    purchase_id=pk,
                    item_id=l_item_id,
                    quantity=qty,
                    unit_price=price,
                    line_total=total,
                    cost_at_sale=cost_at_sale,  # stktrans.newcostprice — weighted-avg cost at time of transaction
                    list_price=list_price,
                    disc_pharmacy_pct=dp_pharm,
                    disc_additional_pct=dp_addl,
                    disc_customer_pct=dp_cust,
                    disc_special_pct=dp_spec,
                ))
        if line_objs:
            PurchaseHistoryLine.objects.bulk_create(line_objs, batch_size=2000)

        total_count += len(header_objs)

    SyncLog.objects.create(sync_run=sync_run, table_name='stktrans', records_processed=total_count)
    logger.info(f"Sales invoices synced: {total_count}")
    return total_count


# ── sync_users ────────────────────────────────────────────────────────────────

def sync_users(conn, sync_run):
    """
    Sync ERP users into the local ERPUser cache table.

    Does NOT create Django users or StaffProfiles — that's done explicitly by
    admins via the user-management UI. ERPUser is only a lookup cache used to
    validate that a username exists in SOFTECH before creating a local account.

    Real columns: userid, usercode, usergroup, user_nomore, branchcode, storecode
    user_nomore=0 means active.
    """
    from apps.users.models import ERPUser

    cursor = conn.cursor()
    cursor.execute(QUERY_USERS)
    rows = cursor.fetchall()

    objs = []
    for row in rows:
        try:
            # Row: [0] userid  [1] usercode  [2] usergroup  [3] user_nomore
            #       [4] branchcode  [5] storecode
            # Some rows may have extra columns (full_name etc.) from extended queries.
            login = str(row[1] or row[0]).strip()
            if not login:
                continue
            objs.append(ERPUser(
                username=login,
                user_id=str(row[0] or '').strip(),
                user_group=str(row[2] or '').strip(),
                branch_code=str(row[4] or '').strip(),
                full_name=str(row[6] or '').strip() if len(row) > 6 else '',
                is_active=(str(row[3] or '1').strip() == '0'),   # user_nomore='0' → active
            ))
        except Exception as e:
            logger.warning(f"ERP user build error userid={row[0]}: {e}")

    count = len(objs)
    if objs:
        ERPUser.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['username'],
            update_fields=['user_id', 'user_group', 'branch_code', 'full_name', 'is_active'],
            batch_size=200,
        )
    SyncLog.objects.create(sync_run=sync_run, table_name='users', records_processed=count)
    logger.info(f"ERP Users synced: {count}")
    return count


# ── ERP permission mirror (usergroups / mitems / mglevels) ────────────────────

def _b(v):
    """SOFTECH stores permission flags as smallint 0/1 OR varchar '1'/'0'."""
    s = str(v).strip()
    return s in ('1', '1.0', 'True', 'true')


def sync_erp_permissions(conn, sync_run):
    """
    Mirror the SOFTECH authorization model into Django (read-only reference):
      usergroups → ErpUserGroup
      mitems     → ErpScreen
      mglevels   → ErpGroupPermission (group × screen × 12 action flags)

    Lets Django later DERIVE effective module permissions per user from their
    ERP group. Never writes back to SOFTECH.
    """
    from apps.users.models import ErpUserGroup, ErpScreen, ErpGroupPermission
    from apps.sync.sybase_queries import (
        QUERY_ERP_USERGROUPS, QUERY_ERP_SCREENS, QUERY_ERP_GROUPPERMS,
    )
    total = 0

    # 1) usergroups
    try:
        cur = conn.cursor()
        cur.execute(QUERY_ERP_USERGROUPS)
        groups = []
        for r in cur.fetchall():
            try:
                groups.append(ErpUserGroup(
                    usergroup=int(r[0]),
                    name=str(r[1] or '').strip(),
                    is_blocked=_b(r[2]),
                ))
            except Exception:
                continue
        if groups:
            ErpUserGroup.objects.bulk_create(
                groups, update_conflicts=True, unique_fields=['usergroup'],
                update_fields=['name', 'is_blocked'], batch_size=100,
            )
        total += len(groups)
        logger.info(f"[perms] usergroups synced: {len(groups)}")
    except Exception as exc:
        logger.error(f"[perms] usergroups sync failed: {exc}")

    # 2) mitems (screens)
    try:
        cur = conn.cursor()
        cur.execute(QUERY_ERP_SCREENS)
        screens = []
        for r in cur.fetchall():
            name = str(r[0] or '').strip()
            if not name:
                continue
            screens.append(ErpScreen(
                mitemname=name,
                descr_ar=str(r[1] or '').strip()[:120],
                descr_en=str(r[2] or '').strip()[:120],
                system=str(r[3] or '').strip()[:4],
                subsystem=str(r[4] or '').strip()[:20],
                item_order=int(r[5] or 0),
            ))
        # de-dup by mitemname (catalog can contain dup rows)
        screens = list({s.mitemname: s for s in screens}.values())
        if screens:
            ErpScreen.objects.bulk_create(
                screens, update_conflicts=True, unique_fields=['mitemname'],
                update_fields=['descr_ar', 'descr_en', 'system', 'subsystem', 'item_order'],
                batch_size=500,
            )
        total += len(screens)
        logger.info(f"[perms] screens synced: {len(screens)}")
    except Exception as exc:
        logger.error(f"[perms] screens sync failed: {exc}")

    # 3) mglevels (group × screen permissions)
    try:
        group_map = {g.usergroup: g.id for g in ErpUserGroup.objects.all()}
        cur = conn.cursor()
        cur.execute(QUERY_ERP_GROUPPERMS)
        perms = []
        for r in cur.fetchall():
            try:
                gid = group_map.get(int(r[0]))
            except Exception:
                gid = None
            name = str(r[1] or '').strip()
            if not gid or not name:
                continue
            perms.append(ErpGroupPermission(
                group_id=gid, mitemname=name,
                can_enable=_b(r[2]),  can_show=_b(r[3]),  can_retrieve=_b(r[4]),
                can_save=_b(r[5]),    can_datain=_b(r[6]), can_print=_b(r[7]),
                can_scan=_b(r[8]),    can_data=_b(r[9]),   can_money=_b(r[10]),
                can_cost=_b(r[11]),   can_brmb=_b(r[12]),  can_scanedit=_b(r[13]),
            ))
        # de-dup by (group, mitemname)
        perms = list({(p.group_id, p.mitemname): p for p in perms}.values())
        if perms:
            ErpGroupPermission.objects.bulk_create(
                perms, update_conflicts=True,
                unique_fields=['group', 'mitemname'],
                update_fields=[
                    'can_enable', 'can_show', 'can_retrieve', 'can_save', 'can_datain',
                    'can_print', 'can_scan', 'can_data', 'can_money', 'can_cost',
                    'can_brmb', 'can_scanedit',
                ],
                batch_size=500,
            )
        total += len(perms)
        logger.info(f"[perms] group permissions synced: {len(perms)}")
    except Exception as exc:
        logger.error(f"[perms] mglevels sync failed: {exc}")

    SyncLog.objects.create(sync_run=sync_run, table_name='erp_permissions', records_processed=total)
    return total


# ── finance snapshot helper ───────────────────────────────────────────────────

def _sync_finance_snapshots():
    """
    Fast finance P&L snapshot refresh — called after every 30-minute sync cycle.

    Runs snapshot-only sync (skip_journal=True, skip_inventory=True) for:
      • The current calendar month (always)
      • The previous calendar month (only during the first 5 days — late corrections)

    Each month takes ~1–3 seconds (one stktrans GROUP BY query via a fresh
    Sybase connection).  Journal and inventory scans are skipped to keep the
    scheduler load minimal; those are run manually via:
        python manage.py sync_finance --months N

    The FinanceSyncEngine opens its own connection and closes it on completion.
    """
    import datetime as _dt2
    from apps.finance.engine.sync_engine import FinanceSyncEngine

    today = _dt2.date.today()
    months_to_sync = [(today.year, today.month)]

    # Include previous month during first 5 days (supplier returns / corrections
    # for month-end documents may arrive a few days late in SOFTECH).
    if today.day <= 5:
        prev = today.replace(day=1) - _dt2.timedelta(days=1)
        months_to_sync.append((prev.year, prev.month))

    for yr, mo in months_to_sync:
        try:
            engine = FinanceSyncEngine(
                year=yr,
                month=mo,
                # Fast path: only P&L snapshot from stktrans GROUP BY.
                # Journal, inventory, expenses, treasury are skipped in the
                # scheduler cycle to keep the 30-min run under 5 seconds.
                # Run these manually: python manage.py sync_finance --months 3
                skip_coa=True,
                skip_journal=True,
                skip_inventory=True,
                skip_expenses=True,
                skip_treasury=True,
            )
            stats = engine.run()
            logger.info(
                f"[finance-snap] {yr}-{mo:02d} OK — "
                f"created={stats.get('snapshots_created', 0)} "
                f"updated={stats.get('snapshots_updated', 0)}"
            )
        except Exception as exc:
            logger.warning(f"[finance-snap] {yr}-{mo:02d} failed: {exc}")


# ── ERP match polling ─────────────────────────────────────────────────────────

# 96 polls × 30 min = 48 hours maximum wait before marking timeout
_ERP_MATCH_MAX_ATTEMPTS = 96


def _poll_erp_matches():
    """
    Called inside every run_full_sync() cycle (every 30 min).

    Finds all TransferRequests in state sent_to_erp with erp_match_status='pending'
    and an erp_reference set, then runs ERPMatcher on each one.

    ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT/UPDATE/DELETE.
    All writes go to PostgreSQL (TransferRequest fields + chatter + notifications).
    """
    from apps.transfers.models import TransferRequest, TransferRequestMessage
    from apps.transfers.erp_matcher import ERPMatcher, apply_match_result, ERP_MATCH_UPDATE_FIELDS
    from django.utils import timezone

    pending_qs = TransferRequest.objects.filter(
        status='sent_to_erp',
        erp_match_status='pending',
    ).exclude(erp_reference='').select_related(
        'supplying_branch', 'requesting_branch',
    )

    checked = 0
    for tr in pending_qs:
        try:
            result = ERPMatcher(tr).run()
            apply_match_result(tr, result)

            match_status = result['status']

            # Timeout guard — give up after MAX_ATTEMPTS regardless of status
            if (tr.erp_check_attempts or 0) >= _ERP_MATCH_MAX_ATTEMPTS and match_status not in ('matched',):
                tr.erp_match_status  = 'timeout'
                tr.erp_match_detail  = (
                    f'⏱️ انتهت مهلة التحقق بعد {_ERP_MATCH_MAX_ATTEMPTS} محاولة '
                    f'({_ERP_MATCH_MAX_ATTEMPTS // 2} ساعة). '
                    f'المستند {tr.erp_reference} لم يُعثر عليه في SOFTECH بعد.'
                )

            tr.save(update_fields=ERP_MATCH_UPDATE_FIELDS)

            # Chatter entry for any state change
            TransferRequestMessage.log_system(tr, tr.erp_match_detail)

            # Notifications on match/partial/timeout
            if match_status in ('matched', 'partial'):
                _erp_notify(
                    tr,
                    f'تم التحقق من مستند ERP — {tr.request_number}',
                    tr.erp_match_detail,
                    notif_type='transfer_response',
                )
            elif tr.erp_match_status == 'timeout':
                _erp_notify(
                    tr,
                    f'انتهت مهلة التحقق من ERP — {tr.request_number}',
                    tr.erp_match_detail,
                    notif_type='transfer_response',
                )

            checked += 1

        except Exception as exc:
            logger.warning(
                f'_poll_erp_matches: error processing TR {tr.request_number}: {exc}'
            )

    if checked:
        logger.info(f'[erp-match] Polled {checked} pending transfer(s)')


def _erp_notify(transfer_request, title, body, notif_type):
    """Non-fatal notification helper for ERP match events (notifies both branches)."""
    try:
        from apps.notifications.models import Notification

        # Notify supplying branch (the one that processed the ERP doc)
        if transfer_request.supplying_branch:
            Notification.send_to_branch(
                branch=transfer_request.supplying_branch,
                notification_type=notif_type,
                title=title,
                body=body or '',
                transfer_id=transfer_request.id,
                dedup_key=f'{notif_type}_erp_{transfer_request.id}',
                include_admins=True,
            )

        # Notify requesting branch (they want to know it's been processed)
        if transfer_request.requesting_branch:
            Notification.send_to_branch(
                branch=transfer_request.requesting_branch,
                notification_type=notif_type,
                title=title,
                body=body or '',
                transfer_id=transfer_request.id,
                dedup_key=f'{notif_type}_erp_req_{transfer_request.id}',
                include_admins=True,
            )
    except Exception:
        pass


# ── SCHEDULER ─────────────────────────────────────────────────────────────────

_scheduler = None


def _patch_apscheduler_for_python312():
    """
    APScheduler 3.x submits jobs via concurrent.futures.ThreadPoolExecutor.
    On Python 3.12+ / dev autoreload, the underlying pool can be marked
    _shutdown=True while the scheduler keeps ticking (a lingering/zombie worker
    process that didn't fully exit).  executor.submit() then raises:
        RuntimeError: cannot schedule new futures after shutdown

    CRITICAL: do NOT merely swallow this — if _do_submit_job returns normally
    without actually submitting, APScheduler's submit_job still does
    `self._instances[job.id] += 1`, but the job never runs/completes, so the
    counter is never decremented → every future run is skipped forever with
    "maximum number of running instances reached".  (That was the cause of the
    permanent job-skip cascade.)

    Correct fix: detect the dead pool, RECREATE it, and retry the submit once so
    the job actually runs and the instance counter is managed normally.  If the
    retry still fails, re-raise so APScheduler skips the increment (no wedge).
    """
    try:
        from apscheduler.executors.pool import BasePoolExecutor
        _orig = BasePoolExecutor._do_submit_job

        def _safe_submit(self, job, run_times):
            try:
                _orig(self, job, run_times)
            except RuntimeError as exc:
                if 'shutdown' not in str(exc).lower():
                    raise
                pool = getattr(self, '_pool', None)
                if pool is None:
                    raise
                # Recreate the torn-down thread pool, then retry the submit once.
                from concurrent.futures import ThreadPoolExecutor as _TPE
                mw = getattr(pool, '_max_workers', None) or 10
                self._pool = _TPE(max_workers=mw)
                logger.warning('[scheduler] thread pool was shut down — recreated '
                               '(%d workers) and retrying job %s', mw, job.id)
                _orig(self, job, run_times)   # propagate if it still fails → no increment

        BasePoolExecutor._do_submit_job = _safe_submit
        logger.debug('[scheduler] APScheduler pool self-heal patch applied')
    except (ImportError, AttributeError) as exc:
        logger.debug('[scheduler] APScheduler patch skipped: %s', exc)


SCHEDULER_HEARTBEAT_KEY = 'scheduler_heartbeat'


def _write_heartbeat():
    """Persist 'scheduler is alive' timestamp so the API can detect a dead scheduler."""
    try:
        from apps.config.models import SystemSetting
        from django.utils import timezone
        SystemSetting.objects.update_or_create(
            key=SCHEDULER_HEARTBEAT_KEY,
            defaults={
                'value':      timezone.now().isoformat(),
                'value_type': 'string',
                'label':      'نبضة المجدول',
                'category':   'general',
            },
        )
    except Exception as exc:
        logger.debug('[scheduler] heartbeat write failed: %s', exc)


def _run_segment_customers():
    """Wrapper for APScheduler — calls segment_customers management command."""
    try:
        from django.core.management import call_command
        call_command('segment_customers', verbosity=0)
        logger.info('[APScheduler] segment_customers completed')
    except Exception as exc:
        logger.error('[APScheduler] segment_customers failed: %s', exc)


def _run_insights(period):
    """Wrapper for APScheduler — generate + WhatsApp-deliver the narrative report (doc 18)."""
    try:
        from django.core.management import call_command
        call_command('generate_insights', period=period, send=True, verbosity=0)
        logger.info('[APScheduler] insights %s report generated', period)
    except Exception as exc:
        logger.error('[APScheduler] insights %s failed: %s', period, exc)


def _insights_daily():
    _run_insights('day')


def _insights_weekly():
    _run_insights('week')


def _insights_monthly():
    _run_insights('month')


def _run_procurement_refresh():
    """Keep procurement.PurchaseLine current so the purchasing insight rules aren't stale.
    Short lookback (the engine upserts) — runs just before the daily insight report."""
    try:
        from django.core.management import call_command
        call_command('run_procurement_engine', days=14, triggered_by='scheduler', verbosity=0)
        logger.info('[APScheduler] procurement refresh done')
    except Exception as exc:
        logger.error('[APScheduler] procurement refresh failed: %s', exc)


def _send_followup_reminders():
    """Fire reminder notifications for FollowUpTask records whose reminder_at has passed."""
    try:
        from apps.followups.models import FollowUpTask
        from apps.notifications.models import Notification
        now = timezone.now()
        due = list(
            FollowUpTask.objects.filter(
                reminder_at__lte=now,
                reminder_sent=False,
                status__in=('pending', 'called'),
            ).select_related('assigned_to__user', 'customer', 'item')
        )
        for task in due:
            if task.assigned_to:
                Notification.send_to_user(
                    staff             = task.assigned_to,
                    notification_type = 'follow_up_due',
                    title             = f'⏰ تذكير متابعة: {task.customer.name if task.customer else "—"}',
                    body              = f'{task.item.name if task.item else "مهمة مخصصة"} — استحقاق {task.due_date}',
                    dedup_key         = f'fu_reminder_{task.pk}',
                )
        if due:
            FollowUpTask.objects.filter(pk__in=[t.pk for t in due]).update(reminder_sent=True)
            logger.info('[APScheduler] followup_reminders: sent %d reminders', len(due))
    except Exception as exc:
        logger.error('[APScheduler] followup_reminders failed: %s', exc)


def _process_reminders_and_snoozes():
    """Every minute: un-snooze due notifications (re-alarm) + fire due personal reminders."""
    try:
        from apps.notifications.models import Notification, PersonalReminder
        now = timezone.now()
        # 1) Un-snooze: clear snoozed_until and re-push so the bell re-alarms.
        due = list(Notification.objects.filter(snoozed_until__lte=now)[:1000])
        for n in due:
            n.snoozed_until = None
            n.save(update_fields=['snoozed_until'])
            try:
                n.push_realtime()   # new_notification path → re-alarm on the client
            except Exception:
                pass
        # 2) Fire due personal reminders (PersonalReminder.fire is idempotent).
        fired = 0
        for r in PersonalReminder.objects.filter(is_fired=False, remind_at__lte=now)[:1000]:
            try:
                r.fire()
                fired += 1
            except Exception:
                logger.exception('[scheduler] reminder fire failed: %s', r.pk)
        if due or fired:
            logger.info('[scheduler] reminders/snooze: unsnoozed=%d reminders_fired=%d',
                        len(due), fired)
    except Exception as exc:
        logger.warning('reminders/snooze worker failed (non-fatal): %s', exc)


def _demand_recovery_escalation():
    """Hourly: escalate stale back-in-stock recovery opportunities to supervisors."""
    try:
        from apps.demand.service import escalate_stale_recoveries
        n = escalate_stale_recoveries()
        if n:
            logger.info('[scheduler] demand recovery escalation: %d escalated', n)
    except Exception as exc:
        logger.warning('demand recovery escalation failed (non-fatal): %s', exc)


def _demand_sla_escalation():
    """Hourly: escalate demand-intake SLA breaches (unassigned/stalled) — TD-C003."""
    try:
        from apps.demand.service import escalate_breached_demand_sla
        n = escalate_breached_demand_sla()
        if n:
            logger.info('[scheduler] demand SLA escalation: %d escalated', n)
    except Exception as exc:
        logger.warning('demand SLA escalation failed (non-fatal): %s', exc)


def _auto_expire_reservations():
    """
    Nightly job (03:00 Cairo) — expires stale reservations.
    Threshold is read from SystemSetting 'reservation_expiry_days' (default: 30).
    Only affects pending / available / contacted — confirmed are left alone.
    """
    try:
        from apps.reservations.models import Reservation, ReservationStatusLog, ReservationActivity
        from apps.config.models import SystemSetting

        try:
            days = SystemSetting.objects.get(key='reservation_expiry_days').typed_value() or 30
        except SystemSetting.DoesNotExist:
            days = 30
        days = max(1, int(days))

        cutoff = timezone.now() - _dt.timedelta(days=days)
        stale = list(
            Reservation.objects.filter(
                status__in=['pending', 'available', 'contacted'],
                created_at__lt=cutoff,
            ).select_related('branch')[:300]
        )

        if not stale:
            return

        stale_ids = [r.pk for r in stale]

        # Bulk status + log + chatter
        status_logs = []
        activities = []
        for r in stale:
            status_logs.append(ReservationStatusLog(
                reservation_id=r.pk,
                old_status=r.status,
                new_status='expired',
                note=f'انتهت مدة الحجز تلقائياً بعد {days} يوماً',
            ))
            activities.append(ReservationActivity(
                reservation_id=r.pk,
                activity_type='status_changed',
                message=f'⏰ انتهت صلاحية الحجز تلقائياً بعد {days} يوماً دون إتمام',
            ))

        ReservationStatusLog.objects.bulk_create(status_logs, batch_size=200)
        ReservationActivity.objects.bulk_create(activities, batch_size=200)
        Reservation.objects.filter(pk__in=stale_ids).update(
            status='expired',
            updated_at=timezone.now(),
        )

        logger.info(f'[auto-expire] Expired {len(stale_ids)} stale reservations (>{days} days old)')

        # Notify admins + call center once with a summary
        try:
            from apps.notifications.models import Notification
            Notification.send_to_call_center(
                notification_type='reservation_status',
                title=f'⏰ انتهت صلاحية {len(stale_ids)} حجز تلقائياً',
                body=f'تم إنهاء {len(stale_ids)} حجز لم يُكتمل خلال {days} يوماً.',
                dedup_key=f'auto_expire_{timezone.now().date()}',
            )
        except Exception:
            pass

    except Exception as exc:
        logger.error('[auto-expire] Failed: %s', exc, exc_info=True)


def _delivery_sla_alerts():
    """
    F8 — SLA Alert job (every 15 minutes).
    Scans active delivery orders for SLA breaches and notifies delivery managers.
    Thresholds read from SystemSetting:
      delivery_sla_unassigned_mins  (default 20)
      delivery_sla_preparing_mins   (default 30)
      delivery_sla_dispatch_mins    (default 90)
    """
    try:
        from apps.delivery.models import DeliveryOrder
        from apps.notifications.models import Notification
        from apps.config.models import SystemSetting
        from apps.users.models import StaffProfile

        now = timezone.now()

        def _setting(key, default):
            try:
                return int(SystemSetting.objects.get(key=key).value or default)
            except SystemSetting.DoesNotExist:
                return default

        mins_unassigned = _setting('delivery_sla_unassigned_mins', 20)
        mins_preparing  = _setting('delivery_sla_preparing_mins',  30)
        mins_dispatch   = _setting('delivery_sla_dispatch_mins',   90)
        # Upper age bound: an order breaching SLA for longer than this is stale/
        # abandoned data (e.g. never-closed historical orders), not an actionable
        # alert. Without this floor, every ancient open order re-alerts on every
        # 15-min run forever. Set very high to effectively disable the cap.
        max_age_hours = _setting('delivery_sla_max_age_hours', 48)
        age_floor = now - _dt.timedelta(hours=max_age_hours)

        alerted = 0

        # 1. Unassigned too long (created/pending_review but no driver)
        stuck_unassigned = DeliveryOrder.objects.filter(
            status__in=[DeliveryOrder.STATUS_CREATED, DeliveryOrder.STATUS_PENDING_REVIEW],
            assigned_driver__isnull=True,
            ordered_at__lt=now - _dt.timedelta(minutes=mins_unassigned),
            ordered_at__gte=age_floor,
        ).select_related('branch')

        for order in stuck_unassigned:
            age = int((now - order.ordered_at).total_seconds() // 60)
            Notification.send_to_roles(
                roles=['delivery', 'admin'],
                notification_type='delivery_sla_alert',
                title=f'⏰ طلب بدون سائق منذ {age} دقيقة',
                body=(
                    f'الطلب {order.order_number} — {order.customer_name}\n'
                    f'الفرع: {order.branch.display_name if order.branch else "—"}\n'
                    f'القيمة: {order.total_value} ج.م'
                ),
                dedup_key=f'sla_unassigned_{order.id}_{now.strftime("%Y%m%d%H")}',
                dedup_once=True,
            )
            alerted += 1

        # 2. In "ready" state too long without dispatch
        stuck_ready = DeliveryOrder.objects.filter(
            status__in=[DeliveryOrder.STATUS_READY, DeliveryOrder.STATUS_ASSIGNED, DeliveryOrder.STATUS_DRIVER_ACCEPTED],
            ordered_at__lt=now - _dt.timedelta(minutes=mins_preparing),
            ordered_at__gte=age_floor,
        ).select_related('branch')

        for order in stuck_ready:
            age = int((now - order.ordered_at).total_seconds() // 60)
            Notification.send_to_roles(
                roles=['delivery', 'admin'],
                notification_type='delivery_sla_alert',
                title=f'⏰ طلب لم يخرج للتوصيل منذ {age} دقيقة',
                body=(
                    f'الطلب {order.order_number} — {order.customer_name}\n'
                    f'الحالة: {order.get_status_display()}\n'
                    f'السائق: {order.assigned_driver.full_name if order.assigned_driver else "غير محدد"}'
                ),
                dedup_key=f'sla_ready_{order.id}_{now.strftime("%Y%m%d%H")}',
                dedup_once=True,
            )
            alerted += 1

        # 3. Out for delivery too long without confirmation
        stuck_dispatch = DeliveryOrder.objects.filter(
            status=DeliveryOrder.STATUS_OUT,
            dispatched_at__lt=now - _dt.timedelta(minutes=mins_dispatch),
            dispatched_at__isnull=False,
            dispatched_at__gte=age_floor,
        ).select_related('branch', 'assigned_driver')

        for order in stuck_dispatch:
            age = int((now - order.dispatched_at).total_seconds() // 60)
            Notification.send_to_roles(
                roles=['delivery', 'admin'],
                notification_type='delivery_sla_alert',
                title=f'⏰ سائق في الطريق منذ {age} دقيقة بدون تأكيد',
                body=(
                    f'الطلب {order.order_number} — {order.customer_name}\n'
                    f'السائق: {order.assigned_driver.full_name if order.assigned_driver else "—"}\n'
                    f'📞 {order.customer_phone}'
                ),
                dedup_key=f'sla_dispatch_{order.id}_{now.strftime("%Y%m%d%H")}',
                dedup_once=True,
            )
            alerted += 1

        if alerted:
            logger.info(f'[delivery-sla] Sent {alerted} SLA alerts')
    except Exception as exc:
        logger.error('[delivery-sla] Failed: %s', exc)


def _sync_in_transit_transfers():
    """
    Transit Sync — every 15 minutes.
    Scans SOFTECH for new/updated doccode='125' inter-branch transfers and
    refreshes the InTransitTransfer local cache. Fires overdue alerts.
    """
    try:
        from django.core.management import call_command
        call_command('sync_in_transit', verbosity=0)
        logger.info('[APScheduler] sync_in_transit completed')
    except Exception as exc:
        logger.error('[APScheduler] sync_in_transit failed: %s', exc)


def _check_transfer_sla():
    """
    B3 — Transfer SLA enforcement (every hour).
    Notifies admin/purchasing when a pending transfer has not been reviewed
    within transfer_sla_hours (default 24 h) of submission.
    """
    try:
        from django.core.management import call_command
        call_command('check_transfer_sla', verbosity=0)
        logger.info('[APScheduler] check_transfer_sla completed')
    except Exception as exc:
        logger.error('[APScheduler] check_transfer_sla failed: %s', exc)


def _delivery_csat_sender():
    """
    F14 — CSAT WhatsApp sender (every 30 minutes).
    Sends a satisfaction survey WhatsApp message for delivered orders
    after the configured delay (delivery_csat_delay_mins).
    """
    try:
        from apps.delivery.models import DeliveryOrder, DeliveryCSAT
        from apps.config.models import SystemSetting

        try:
            enabled = SystemSetting.objects.get(key='delivery_csat_enabled').value.lower() in ('true', '1', 'yes')
        except SystemSetting.DoesNotExist:
            enabled = True

        if not enabled:
            return

        try:
            delay_mins = int(SystemSetting.objects.get(key='delivery_csat_delay_mins').value or 30)
        except SystemSetting.DoesNotExist:
            delay_mins = 30

        try:
            pharmacy = SystemSetting.objects.get(key='delivery_pharmacy_name').value or 'صيدليات الرزيقي'
        except SystemSetting.DoesNotExist:
            pharmacy = 'صيدليات الرزيقي'

        cutoff = timezone.now() - _dt.timedelta(minutes=delay_mins)

        # Find delivered orders not yet sent a CSAT request
        candidates = DeliveryOrder.objects.filter(
            status=DeliveryOrder.STATUS_DELIVERED,
            delivered_at__isnull=False,
            delivered_at__lt=cutoff,
            delivered_at__gte=timezone.now() - _dt.timedelta(hours=48),  # don't spam old orders
        ).exclude(
            csat__wa_sent=True
        ).select_related('customer')[:50]  # cap per run

        sent = 0
        for order in candidates:
            phone = order.customer_phone or order.customer_phone_alt
            if not phone:
                continue

            # Normalise phone
            clean = phone.strip().replace(' ', '').replace('-', '').replace('+', '')
            if clean.startswith('0'):
                clean = '20' + clean[1:]
            elif not clean.startswith('20'):
                clean = '20' + clean

            import urllib.parse
            msg = (
                f'عزيزنا العميل 😊\n'
                f'شكراً لتعاملكم مع {pharmacy}\n'
                f'طلبكم رقم {order.order_number} تم تسليمه بنجاح ✅\n\n'
                f'كيف تقيّم تجربة التوصيل؟\n'
                f'1⭐ ضعيف  |  3⭐ جيد  |  5⭐ ممتاز\n\n'
                f'أرسل رقمك (1-5) وسنسعد بتحسين خدمتنا 💊'
            )

            DeliveryCSAT.objects.update_or_create(
                order=order,
                defaults={
                    'wa_sent':    True,
                    'wa_sent_at': timezone.now(),
                    'channel':    'whatsapp',
                },
            )
            # Note: actual WhatsApp sending would use the WhatsApp Business API.
            # For now, we mark wa_sent=True and log the URL for staff to send manually.
            wa_url = f'https://wa.me/{clean}?text={urllib.parse.quote(msg)}'
            logger.info(f'[csat] CSAT queued for order {order.order_number}: {wa_url}')
            sent += 1

        if sent:
            logger.info(f'[csat] {sent} CSAT messages queued')
    except Exception as exc:
        logger.error('[csat] Failed: %s', exc)


def _sync_crm_delivery_orders():
    """
    APScheduler job — incremental poll of piccrmorders every 5 minutes.
    Delegates to the sync_crm_orders management command (incremental, 10-min window).
    Non-fatal: errors are logged but never crash the scheduler.
    """
    try:
        from django.core.management import call_command
        call_command('sync_crm_orders', minutes=10, verbosity=0)
        logger.info('[APScheduler] crm_delivery_sync completed')
    except Exception as exc:
        logger.error('[APScheduler] crm_delivery_sync failed: %s', exc)


def _reconcile_pos_orders():
    """
    APScheduler job — reconcile pushed Indirect-POS orders vs the branch DBs every
    5 minutes (read-only settlement detection). Delegates to reconcile_pos_orders.
    Non-fatal: errors are logged but never crash the scheduler.
    """
    try:
        from django.core.management import call_command
        call_command('reconcile_pos_orders', verbosity=0)
        logger.info('[APScheduler] pos_orders_reconcile completed')
    except Exception as exc:
        logger.error('[APScheduler] pos_orders_reconcile failed: %s', exc)


def _flush_pos_orders():
    """
    APScheduler job — retry POS orders queued while the branch/SOFTECH was unreachable.
    Idempotent + serial-allocated-at-write, so retries can never duplicate a document.
    No-op unless POS_WRITER_ENABLED. Non-fatal.
    """
    try:
        from django.core.management import call_command
        call_command('flush_pos_orders', verbosity=0)
        logger.info('[APScheduler] pos_orders_flush completed')
    except Exception as exc:
        logger.error('[APScheduler] pos_orders_flush failed: %s', exc)


def _sync_insurance_cache():
    """Daily insurance cache sync — motalba + companiesitems last-90-days mirror."""
    try:
        from apps.insurance.sync import sync_insurance_cache
        result = sync_insurance_cache()
        logger.info('[APScheduler] insurance_cache_sync: %s', result)
    except Exception as exc:
        logger.error('[APScheduler] insurance_cache_sync failed: %s', exc)


def _run_replication_audit(full_catalog=False):
    """
    Replication audit + policy-driven auto-repair.
      full_catalog=False → daily window scan (policy.daily_window_days).
      full_catalog=True  → weekly deep scan of EVERY active item (#6).
    Auto-repair only runs when policy.auto_repair_enabled, capped at
    policy.max_items_per_run (#5).
    """
    try:
        from apps.discount_approvals.replication import scan_recent, force_replication
        from apps.discount_approvals.models import ReplicationGap, ReplicationPolicy
        from apps.discount_approvals.notify import notify_admins_replication_gaps

        pol = ReplicationPolicy.get()
        if full_catalog and not pol.weekly_full_audit:
            return
        days = None if full_catalog else pol.daily_window_days
        scan = scan_recent(days=days, persist=True, is_scheduled=True)
        notify_admins_replication_gaps(scan)
        logger.info('[APScheduler] replication_audit(full=%s) scan #%s gaps=%s down=%s',
                    full_catalog, scan.pk, scan.items_with_gaps, scan.branches_down)

        if pol.auto_repair_enabled and scan.items_with_gaps:
            codes = sorted(set(
                ReplicationGap.objects.filter(scan=scan)
                .exclude(status=ReplicationGap.STATUS_REPAIRED)
                .values_list('item_softech_id', flat=True)
            ))[:pol.max_items_per_run]   # safety cap
            for code in codes:
                force_replication(code, mode='restamp')
            logger.info('[APScheduler] replication_audit re-queued %s items (cap=%s)',
                        len(codes), pol.max_items_per_run)
        elif scan.items_with_gaps:
            logger.info('[APScheduler] replication_audit: auto-repair OFF — alert only')
    except Exception as exc:
        logger.error('[APScheduler] replication_audit failed: %s', exc)


def _run_replication_full_audit():
    """Weekly full-catalog drift audit (#6)."""
    _run_replication_audit(full_catalog=True)


# ── New-module scheduled jobs ─────────────────────────────────────────────────

def _near_expiry_scan():
    """
    Daily at 06:00 Cairo — scan all StockBatch records for near-expiry thresholds
    and create NearExpiryAlert rows. Also marks truly-expired batches.
    Non-fatal: errors logged, scheduler continues.
    """
    try:
        from apps.batches.service import BatchService
        result = BatchService.scan_near_expiry()
        logger.info('[APScheduler] near_expiry_scan: expired=%s alerts_created=%s',
                    result.get('expired', 0), result.get('alerts_created', 0))
    except Exception as exc:
        logger.error('[APScheduler] near_expiry_scan failed: %s', exc)


def _escalate_overdue_approvals():
    """
    Every hour — escalate approval steps that have exceeded their SLA deadline.
    Sends notifications to the next eligible approvers and logs an escalation record.
    Non-fatal.
    """
    try:
        from apps.approvals.service import ApprovalService
        count = ApprovalService.escalate_overdue_steps()
        if count:
            logger.info('[APScheduler] escalate_overdue_approvals: %d steps escalated', count)
    except Exception as exc:
        logger.error('[APScheduler] escalate_overdue_approvals failed: %s', exc)


def _run_forecast_job():
    """
    Daily at 02:30 Cairo (after customer segmentation, before near-expiry scan).
    Runs the full ForecastService across all items × branches.
    Writes forecast fields into ItemDemandMetrics.
    Non-fatal.
    """
    try:
        from apps.forecasting.service import ForecastService
        result = ForecastService.run_forecast()
        logger.info('[APScheduler] run_forecast: items_processed=%s errors=%s run_id=%s',
                    result.get('items_processed', 0),
                    result.get('errors', 0),
                    result.get('run_id'))
    except Exception as exc:
        logger.error('[APScheduler] run_forecast failed: %s', exc)


def _sync_softech_points_balances():
    """
    Pull SOFTECH PIC points balances into LoyaltyAccount.softech_points_balance.
    Runs after every full sync cycle (replaces _award_loyalty_points_for_recent_purchases
    which was disabled to prevent double-counting with SOFTECH's own POS logic).
    """
    from apps.loyalty.pic_bridge import sync_all_softech_balances
    updated = sync_all_softech_balances()
    if updated:
        logger.info('softech_points_sync: updated %d accounts', updated)


def _models_sum(field):
    from django.db.models import Sum
    return Sum(field)


def _drain_wa_queue():
    try:
        from apps.campaigns.dispatcher import drain_queue
        drain_queue()
    except Exception as exc:
        logger.error('[APScheduler] _drain_wa_queue failed: %s', exc)


def _flush_pos_orders():
    """Retry POS orders queued during a SOFTECH/branch outage. Idempotent + gated."""
    try:
        from apps.pos_orders import writer
        if not writer.writer_enabled():
            return
        from apps.pos_orders.models import SoftechSalesOrder
        qs = (SoftechSalesOrder.objects
              .filter(status=SoftechSalesOrder.STATUS_QUEUED)
              .select_related('branch').order_by('created_at')[:50])
        for order in qs:
            try:
                writer.push_order(order, dry_run=False)
            except Exception as exc:
                logger.warning('[APScheduler] pos flush order %s: %s', order.pk, exc)
    except Exception as exc:
        logger.error('[APScheduler] _flush_pos_orders failed: %s', exc)


def _reconcile_pos_orders():
    """Flip pushed → settled by reading the branch DB (read-only)."""
    try:
        from apps.pos_orders.reconcile import run_reconcile
        run_reconcile()
    except Exception as exc:
        logger.error('[APScheduler] _reconcile_pos_orders failed: %s', exc)


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    # Suppress APScheduler "cannot schedule new futures after shutdown" on Py 3.12+
    _patch_apscheduler_for_python312()

    from django.conf import settings as _dj_settings
    _fast_min = int(getattr(_dj_settings, 'SYNC_FAST_MINUTES', 5))
    _slow_min = int(getattr(_dj_settings, 'SYNC_SLOW_MINUTES', 60))

    _scheduler = BackgroundScheduler(timezone='Africa/Cairo')
    # FAST lane — stock + sales + reactive hooks (cheap, high-frequency).
    _scheduler.add_job(
        run_fast_sync,
        'interval',
        minutes=_fast_min,
        id='softech_sync_fast',
        replace_existing=True,
        max_instances=1,       # never overlap; skip a tick if the previous run is still going
        misfire_grace_time=60,
    )
    # SLOW lane — items/customers/etc + master hooks (expensive, low-frequency).
    _scheduler.add_job(
        run_slow_sync,
        'interval',
        minutes=_slow_min,
        id='softech_sync_slow',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    # NETWORK HEALTH — probe HQ + all operational branches (6 nodes) in parallel,
    # fail-fast, every fast interval. Isolated from the sync lanes so a down node
    # never delays data sync. Feeds the branch_watchdog map (HQ included).
    _scheduler.add_job(
        _probe_network_health,
        'interval',
        minutes=_fast_min,
        id='network_health_probe',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    # Nightly customer segmentation — runs at 02:00 Cairo time
    _scheduler.add_job(
        _run_segment_customers,
        'cron',
        hour=2, minute=0,
        id='segment_customers',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.add_job(
        _send_followup_reminders,
        'interval',
        minutes=15,
        id='followup_reminders',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.add_job(
        _auto_expire_reservations,
        'cron',
        hour=3, minute=0,
        id='auto_expire_reservations',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.add_job(
        _demand_recovery_escalation,
        'interval',
        hours=1,
        id='demand_recovery_escalation',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    # Demand-intake SLA escalation — every hour (TD-C003): unassigned 'new' (10m)
    # and stalled 'assigned' (20m) records → tiered breach alerts (HIGH alarm).
    _scheduler.add_job(
        _demand_sla_escalation,
        'interval',
        hours=1,
        id='demand_sla_escalation',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    # Snooze returns + personal reminders — every minute
    _scheduler.add_job(
        _process_reminders_and_snoozes,
        'interval',
        minutes=1,
        id='reminders_and_snoozes',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=55,
    )
    # CRM delivery order sync — piccrmorders every 5 minutes (incremental, last 10 min)
    _scheduler.add_job(
        _sync_crm_delivery_orders,
        'interval',
        minutes=5,
        id='crm_delivery_sync',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    # Indirect-POS order reconcile — pushed orders → settled (read-only) every 5 min
    _scheduler.add_job(
        _reconcile_pos_orders,
        'interval',
        minutes=5,
        id='pos_orders_reconcile',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    # Indirect-POS flush — retry orders queued during a branch outage, every 2 min
    _scheduler.add_job(
        _flush_pos_orders,
        'interval',
        minutes=2,
        id='pos_orders_flush',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    # F8 — SLA alerts — every 15 minutes
    _scheduler.add_job(
        _delivery_sla_alerts,
        'interval',
        minutes=15,
        id='delivery_sla_alerts',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    # F14 — CSAT WhatsApp sender — every 30 minutes
    _scheduler.add_job(
        _delivery_csat_sender,
        'interval',
        minutes=30,
        id='delivery_csat_sender',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    # Replication audit — daily at 04:00 Cairo: detect HQ→branch price/discount
    # changes (module OR direct SOFTECH edits) that a down branch missed, and
    # auto re-queue them for the native replication cycle.
    _scheduler.add_job(
        _run_replication_audit,
        'cron',
        hour=4, minute=0,
        id='pricing_replication_audit',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    # Weekly full-catalog drift audit (#6) — Fridays 03:00 Cairo (low traffic)
    _scheduler.add_job(
        _run_replication_full_audit,
        'cron',
        day_of_week='fri', hour=3, minute=0,
        id='pricing_replication_full_audit',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
    )
    # Insurance cache sync — daily at 01:00 Cairo (after midnight, before segmentation)
    _scheduler.add_job(
        _sync_insurance_cache,
        'cron',
        hour=1, minute=0,
        id='insurance_cache_sync',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,   # 10-min grace — initial 90-day load can be slow
    )
    # Heartbeat — every minute, so /api/sync/scheduler-status/ can detect a
    # dead/stopped scheduler process.
    _scheduler.add_job(
        _write_heartbeat,
        'interval',
        minutes=1,
        id='scheduler_heartbeat',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    # Transit Sync — every 15 minutes
    _scheduler.add_job(
        _sync_in_transit_transfers,
        'interval',
        minutes=15,
        id='sync_in_transit_transfers',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # B3 — Transfer SLA check — every hour
    _scheduler.add_job(
        _check_transfer_sla,
        'interval',
        hours=1,
        id='transfer_sla_check',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Near-expiry batch scan — daily at 06:00 Cairo
    _scheduler.add_job(
        _near_expiry_scan,
        'cron',
        hour=6, minute=0,
        id='near_expiry_scan',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # Approval escalation — every hour (SLA overdue steps)
    _scheduler.add_job(
        _escalate_overdue_approvals,
        'interval',
        hours=1,
        id='escalate_overdue_approvals',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Sales forecast engine — daily at 02:30 Cairo (after segmentation at 02:00)
    _scheduler.add_job(
        _run_forecast_job,
        'cron',
        hour=2, minute=30,
        id='sales_forecast',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # WhatsApp campaign queue drain — every 2 minutes
    _scheduler.add_job(
        _drain_wa_queue,
        'interval',
        minutes=2,
        id='wa_campaign_drain',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    # POS writeback resilience — flush orders queued during a SOFTECH/branch outage,
    # then reconcile pushed→settled. Both are no-ops when POS_WRITER_ENABLED is off.
    _scheduler.add_job(
        _flush_pos_orders, 'interval', minutes=2, id='pos_flush_queued',
        replace_existing=True, max_instances=1, misfire_grace_time=60,
    )
    _scheduler.add_job(
        _reconcile_pos_orders, 'interval', minutes=5, id='pos_reconcile',
        replace_existing=True, max_instances=1, misfire_grace_time=120,
    )
    # Refresh procurement.PurchaseLine before the insight reports so the purchasing
    # rules (price-creep, supplier concentration, etc.) run on current data.
    _scheduler.add_job(
        _run_procurement_refresh, 'cron', hour=6, minute=45, id='procurement_refresh',
        replace_existing=True, max_instances=1, misfire_grace_time=1800,
    )
    # ── Narrative insight reports (doc 18) — bilingual, WhatsApp-delivered ─────
    # Timed after the overnight syncs so yesterday's data is complete (Africa/Cairo).
    _scheduler.add_job(
        _insights_daily, 'cron', hour=7, minute=30, id='insights_daily',
        replace_existing=True, max_instances=1, misfire_grace_time=1800,
    )
    _scheduler.add_job(   # Sunday = start of the Egyptian work-week → prior-week report
        _insights_weekly, 'cron', day_of_week='sun', hour=8, minute=0, id='insights_weekly',
        replace_existing=True, max_instances=1, misfire_grace_time=3600,
    )
    _scheduler.add_job(   # 1st of the month → prior 30 days
        _insights_monthly, 'cron', day=1, hour=8, minute=30, id='insights_monthly',
        replace_existing=True, max_instances=1, misfire_grace_time=3600,
    )

    _scheduler.start()
    _write_heartbeat()   # initial beat so status is fresh immediately

    # Register an atexit hook so the scheduler stops BEFORE the thread-pool
    # atexit finalizer runs.  atexit callbacks fire in LIFO order, so
    # registering here (after module imports) means our hook executes first,
    # cleanly draining the scheduler before Python tears down the executor.
    import atexit
    atexit.register(stop_scheduler)

    logger.info("Sync scheduler started — runs every 30 minutes (Africa/Cairo)")
    logger.info("Segmentation job scheduled — runs daily at 02:00 Cairo")
    logger.info("Follow-up reminder job scheduled — runs every 15 minutes")
    logger.info("Auto-expire reservations job scheduled — runs daily at 03:00 Cairo")
    logger.info("CRM delivery sync scheduled — runs every 5 minutes (piccrmorders)")
    logger.info("Delivery SLA alerts — runs every 15 minutes")
    logger.info("Delivery CSAT sender — runs every 30 minutes")
    logger.info("Transfer SLA check scheduled — runs every hour")
    logger.info("Transit transfers sync scheduled — runs every 15 minutes")
    logger.info("Near-expiry batch scan — runs daily at 06:00 Cairo")
    logger.info("Approval escalation — runs every hour")
    logger.info("Sales forecast engine — runs daily at 02:30 Cairo")
    logger.info("WhatsApp campaign queue drain — runs every 2 minutes")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        try:
            # wait=False: don't block — just tell the scheduler to stop.
            # Any job currently running in its thread will finish naturally;
            # we won't wait for it during interpreter teardown to avoid
            # the "cannot schedule new futures after shutdown" chain.
            _scheduler.shutdown(wait=False)
            logger.info("Sync scheduler stopped")
        except Exception:
            pass  # ignore errors during interpreter teardown
