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
    QUERY_CUSTOMERS,
    QUERY_CUSTOMER_SALES_LINES_RECENT, QUERY_CUSTOMER_SALES_LINES_FULL,
    QUERY_USERS,
)
from apps.catalog.models import Item, Category, ItemStock
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
        total += sync_stock(conn, sync_run)
        total += sync_customers(conn, sync_run)
        total += sync_sales(conn, sync_run, full_history=full_history)
        total += sync_users(conn, sync_run)

        conn.close()

        sync_run.status = 'success'
        sync_run.records_synced = total
        sync_run.completed_at = timezone.now()
        sync_run.save()

        check_stock_for_pending_reservations()

        # Fire stock-available notifications after every sync
        try:
            from django.core import management
            management.call_command('notify_stock_available', verbosity=0)
        except Exception as notif_err:
            logger.warning(f"Stock notification hook failed: {notif_err}")

        logger.info(f"Sync complete — {total} records synced in "
                    f"{(timezone.now() - sync_run.started_at).seconds}s")

    except Exception as e:
        sync_run.status = 'failed'
        sync_run.error_message = str(e)
        sync_run.completed_at = timezone.now()
        sync_run.save()
        logger.error(f"Sync failed: {e}", exc_info=True)

    return sync_run


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
            Branch.objects.update_or_create(
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
    items.itemcode = PK (varchar 6)
    Active = itemnomoreuse != '1' AND itemarchive = 0

    Optimisation: pre-load category map → single bulk upsert.
    Old approach: 2 queries × N rows. New approach: 1 lookup query + batched bulk INSERT.
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_ITEMS)
    rows = cursor.fetchall()

    # Pre-load once: softech_id → db pk
    cat_map = {c.softech_id: c.id for c in Category.objects.only('id', 'softech_id')}

    objs = []
    for row in rows:
        try:
            objs.append(Item(
                softech_id=str(row[0]),
                name=row[1] or '',
                name_scientific=row[2] or '',
                barcode=row[3] or '',
                category_id=cat_map.get(str(row[4])) if row[4] else None,
                supplier_code=row[5] or '',
                unit_price=_to_decimal(row[6]),
                unit_sale_price=_to_decimal(row[7]),
                family_code=row[10] or '',
                requires_fridge=row[11] == '1',
                medicine_type=row[12] or '',
                comment=row[13] or '',
                is_active=True,
            ))
        except Exception as e:
            logger.warning(f"Item build error itemcode={row[0]}: {e}")

    # Deduplicate on softech_id — last-seen wins
    objs = list({o.softech_id: o for o in objs}.values())
    count = len(objs)
    if objs:
        Item.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['softech_id'],
            update_fields=[
                'name', 'name_scientific', 'barcode', 'category_id',
                'supplier_code', 'unit_price', 'unit_sale_price',
                'family_code', 'requires_fridge', 'medicine_type', 'comment', 'is_active',
            ],
            batch_size=500,
        )
    SyncLog.objects.create(sync_run=sync_run, table_name='items', records_processed=count)
    logger.info(f"Items synced: {count}")
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
    Row layout: [0] branchcode [1] branchcustcode [2] branchcustname
                [3] addr1 [4] addr2 [5] dob [6] mobileno [7] branchcustphone
                [8] branchcustclassif [9] ischronic

    Optimisation: pre-load branch map → single bulk upsert.
    Guest-merge is done in one batched pass at the end (not per-row).
    """
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

            mobile = str(row[6] or '').strip()
            phone2 = str(row[7] or '').strip()
            phone  = mobile or phone2

            # PIC code mirrors the SOFTECH format: {branchcode}HD{branchcustcode}
            # Old branches: 2-digit prefix (01–12), e.g. "01HD14"
            # New branches: 3-digit prefix (100, 130, 140), e.g. "130HD9969"
            pic_code = f"{branch_code}HD{cust_code}" if branch_code and cust_code else ''

            customer = Customer(
                softech_id=cust_code,
                softech_pic=pic_code,
                name=str(row[2] or '').strip(),
                address=f"{str(row[3] or '')} {str(row[4] or '')}".strip(),
                date_of_birth=_to_date(row[5]),
                preferred_branch_id=branch_map.get(branch_code),
                phone=phone,
                phone_alt=phone2 if mobile else '',
                softech_ptclassifcode=str(row[8] or '').strip(),
                is_guest=False,
            )
            if hasattr(Customer, 'is_chronic_softech'):
                customer.is_chronic_softech = bool(row[9])

            objs.append(customer)
            if phone:
                synced_phones.add(phone)

        except Exception as e:
            logger.warning(f"Customer build error branchcustcode={row[1]}: {e}")

    # ── Deduplicate by softech_id ─────────────────────────────────────────────
    # SOFTECH's localcustomers may have the same branchcustcode in multiple
    # branches. Since softech_id = branchcustcode (no branch prefix), one batch
    # can contain duplicate keys. PostgreSQL's ON CONFLICT DO UPDATE refuses to
    # touch the same row twice in a single statement → CardinalityViolation.
    # Keep the last-seen record for each softech_id (prefer entries with a phone).
    seen: dict = {}
    for obj in objs:
        existing = seen.get(obj.softech_id)
        if existing is None or (not existing.phone and obj.phone):
            seen[obj.softech_id] = obj
    objs = list(seen.values())

    count = len(objs)

    update_fields = [
        'name', 'softech_pic', 'address', 'date_of_birth', 'preferred_branch_id',
        'phone', 'phone_alt', 'softech_ptclassifcode', 'is_guest',
    ]
    if hasattr(Customer, 'is_chronic_softech'):
        update_fields.append('is_chronic_softech')

    if objs:
        Customer.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=['softech_id'],
            update_fields=update_fields,
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

def sync_sales(conn, sync_run, full_history=False):
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
    query = QUERY_CUSTOMER_SALES_LINES_FULL if full_history else QUERY_CUSTOMER_SALES_LINES_RECENT
    cursor.execute(query)
    rows = cursor.fetchall()

    if not rows:
        SyncLog.objects.create(sync_run=sync_run, table_name='stktrans', records_processed=0)
        return 0

    # Pre-load lookup dicts once
    customer_map = {
        c.softech_id: c.id
        for c in Customer.objects.filter(softech_id__isnull=False).only('id', 'softech_id')
    }
    branch_map = {b.softech_branch_id: b.id for b in Branch.objects.only('id', 'softech_branch_id')}
    item_map   = {i.softech_id: i.id   for i in Item.objects.only('id', 'softech_id')}

    # Group Sybase rows → invoice buckets
    invoices = defaultdict(list)
    for row in rows:
        key = (
            str(row[0]).strip(),  # personcode
            str(row[1]),          # branchcode
            str(row[2]),          # doccode
            str(row[3]),          # docnumber
            row[4],               # docdate
        )
        invoices[key].append(row)

    total_count = 0
    invoice_items = list(invoices.items())

    for batch_start in range(0, len(invoice_items), INVOICE_BATCH):
        batch = invoice_items[batch_start : batch_start + INVOICE_BATCH]

        header_objs     = []   # PurchaseHistory instances
        lines_by_inv_id = {}   # softech_invoice_id → [(item_id, qty, price, total)]

        for (personcode, branchcode, doccode, docnumber, docdate), lines in batch:
            try:
                customer_id = customer_map.get(personcode)
                branch_id   = branch_map.get(branchcode)
                if not customer_id or not branch_id:
                    continue

                if isinstance(docdate, _dt.datetime):
                    date_str = docdate.strftime('%Y%m%d')
                else:
                    date_str = str(docdate)[:10].replace('-', '') if docdate else 'nodate'
                inv_id = f"{branchcode}-{doccode}-{docnumber}-{date_str}"

                total    = sum(_to_decimal(l[8]) for l in lines)
                usercode = next(
                    (str(l[10] or '').strip() for l in lines if len(l) > 10 and l[10]),
                    ''
                )

                header_objs.append(PurchaseHistory(
                    softech_invoice_id=inv_id,
                    customer_id=customer_id,
                    branch_id=branch_id,
                    invoice_date=docdate if isinstance(docdate, _dt.datetime) else None,
                    total_amount=total,
                    doc_code=doccode,
                    docnumber=docnumber,
                    softech_user=usercode,
                ))

                line_tuples = []
                for l in lines:
                    item_id = item_map.get(str(l[5]))
                    if item_id:
                        line_tuples.append((item_id, _to_decimal(l[6]),
                                            _to_decimal(l[7]), _to_decimal(l[8])))
                if line_tuples:
                    lines_by_inv_id[inv_id] = line_tuples

            except Exception as e:
                logger.warning(f"Sales build error: {e}")

        if not header_objs:
            continue

        # ── 1. Bulk upsert invoice headers ────────────────────────────────────
        PurchaseHistory.objects.bulk_create(
            header_objs,
            update_conflicts=True,
            unique_fields=['softech_invoice_id'],
            update_fields=[
                'customer_id', 'branch_id', 'invoice_date',
                'total_amount', 'doc_code', 'docnumber', 'softech_user',
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
            for item_id, qty, price, total in line_tuples:
                line_objs.append(PurchaseHistoryLine(
                    purchase_id=pk,
                    item_id=item_id,
                    quantity=qty,
                    unit_price=price,
                    line_total=total,
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
                is_active=True,
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


# ── SCHEDULER ─────────────────────────────────────────────────────────────────

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone='Africa/Cairo')
    _scheduler.add_job(
        run_full_sync,
        'interval',
        minutes=5,
        id='softech_sync',
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Sync scheduler started — runs every 5 minutes (Africa/Cairo)")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Sync scheduler stopped")
