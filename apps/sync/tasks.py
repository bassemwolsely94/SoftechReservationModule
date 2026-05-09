"""
apps/sync/tasks.py
Sync engine: reads from Sybase ASE 12.5 → writes to PostgreSQL.
Runs every 5 minutes via APScheduler.
ABSOLUTE RULE: NEVER INSERT/UPDATE/DELETE on any Sybase connection.
"""
import datetime as _dt
from decimal import Decimal
import logging
from collections import defaultdict
from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone
from django.contrib.auth.models import User as DjangoUser

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
from apps.users.models import StaffProfile
from apps.sync.models import SyncRun, SyncLog
from apps.reservations.signals import check_stock_for_pending_reservations

logger = logging.getLogger('elrezeiky.sync')


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

        logger.info(f"Sync complete — {total} records synced")

    except Exception as e:
        sync_run.status = 'failed'
        sync_run.error_message = str(e)
        sync_run.completed_at = timezone.now()
        sync_run.save()
        logger.error(f"Sync failed: {e}", exc_info=True)

    return sync_run


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
            name_en = str(row[2] or row[1] or '')   # branchename (English)
            name_ar = str(row[1] or '')              # branchname (Arabic)
            Branch.objects.update_or_create(
                softech_branch_id=str(row[0]),       # branchcode
                defaults={
                    'name': name_en or name_ar,
                    'name_ar': name_ar,
                    'code': str(row[0]),
                    'address': str(row[3] or ''),    # branchaddress
                    'phone': str(row[4] or ''),      # branchphones
                    'is_active': True,
                }
            )
            count += 1
        except Exception as e:
            logger.warning(f"Branch sync error branchcode={row[0]}: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='branches', records_processed=count)
    logger.info(f"Branches synced: {count}")
    return count

def sync_categories(conn, sync_run):
    """
    Real columns: itemsclassifcode, itemsclassifname, classifnamearabic
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_CATEGORIES)
    count = 0
    for row in cursor.fetchall():
        try:
            Category.objects.update_or_create(
                softech_id=str(row[0]),          # itemsclassifcode
                defaults={
                    'name': str(row[1] or ''),   # itemsclassifname
                    'name_ar': str(row[2] or ''), # classifnamearabic
                }
            )
            count += 1
        except Exception as e:
            logger.warning(f"Category sync error: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='itemsclassif', records_processed=count)
    return count


def sync_items(conn, sync_run):
    """
    items.itemcode = PK (varchar 6)
    Active = itemnomoreuse != '1' AND itemarchive = 0
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_ITEMS)
    count = 0
    for row in cursor.fetchall():
        try:
            cat = Category.objects.filter(softech_id=str(row[4])).first() if row[4] else None
            Item.objects.update_or_create(
                softech_id=str(row[0]),           # itemcode
                defaults={
                    'name': row[1] or '',          # itemname
                    'name_scientific': row[2] or '', # itemname_scientific
                    'barcode': row[3] or '',       # itembarcode
                    'category': cat,
                    'supplier_code': row[5] or '', # suppcode
                    'unit_price': Decimal(str(row[6])) if row[6] else 0,
                    'unit_sale_price': Decimal(str(row[7])) if row[7] else 0,
                    'family_code': row[10] or '',  # familycode
                    'requires_fridge': row[11] == '1', # fridgeitem
                    'medicine_type': row[12] or '', # itemmedicine
                    'comment': row[13] or '',      # itemcomment
                    # phcode column does not exist on SOFTECHDB9.dbo.items;
                    # chronic detection uses category name matching instead.
                    'is_active': True,
                }
            )
            count += 1
        except Exception as e:
            logger.warning(f"Item sync error itemcode={row[0]}: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='items', records_processed=count)
    return count


def sync_stock(conn, sync_run):
    """
    stkbal PK: storecode + itemcode
    branchcode DIRECTLY on stkbal — no branchstores join
    Quantity column: nowqty
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_STOCK)
    count = 0
    for row in cursor.fetchall():
        try:
            item = Item.objects.filter(softech_id=str(row[0])).first()
            branch = Branch.objects.filter(softech_branch_id=str(row[1])).first()
            if not item or not branch:
                continue
            ItemStock.objects.update_or_create(
                item=item,
                branch=branch,
                softech_store_code=str(row[2]),
                defaults={
                    'quantity_on_hand': Decimal(str(row[3])) if row[3] else 0,  # nowqty
                    'monthly_qty': Decimal(str(row[4])) if row[4] else 0,
                    'on_order_qty': Decimal(str(row[5])) if row[5] else 0,
                }
            )
            count += 1
        except Exception as e:
            logger.warning(f"Stock sync error itemcode={row[0]}: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='stkbal', records_processed=count)
    return count


def sync_customers(conn, sync_run):
    """
    Sync SOFTECHDB9.dbo.localcustomers → Customer.

    Real schema (confirmed via syscolumns 2026-05-09):
    Row layout:
      [0] branchcode         varchar(5)
      [1] branchcustcode     numeric(6)   ← customer PK within branch
      [2] branchcustname     varchar(30)
      [3] branchcustaddress1 varchar(30)
      [4] branchcustaddress2 varchar(30)
      [5] custdofbirth       datetime
      [6] mobileno           varchar(40)  ← primary phone
      [7] branchcustphone    varchar(30)  ← secondary phone
      [8] branchcustclassif  varchar(2)   ← customer classification code
      [9] ischronic          tinyint      ← SOFTECH native chronic flag

    Phones are embedded on localcustomers; personphones table not used.
    softech_id = branchcode + '-' + branchcustcode (globally unique composite).
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_CUSTOMERS)
    count = 0
    for row in cursor.fetchall():
        try:
            branch_code  = str(row[0] or '').strip()
            # branchcustcode is numeric(6) — cursor returns it as float after
            # BigDecimal conversion; cast to int then string to match
            # stktrans.personcode (varchar 8) which carries the same numeric code.
            raw_cust_num = row[1]  # float after CursorWrapper numeric conversion
            cust_code    = str(int(float(raw_cust_num))) if raw_cust_num is not None else ''
            softech_id   = cust_code  # matches stktrans.personcode

            preferred_branch = None
            if branch_code:
                preferred_branch = Branch.objects.filter(
                    softech_branch_id=branch_code
                ).first()

            mobile = str(row[6] or '').strip()
            phone2 = str(row[7] or '').strip()

            defaults = {
                'name': str(row[2] or '').strip(),
                'address': f"{str(row[3] or '')} {str(row[4] or '')}".strip(),
                'date_of_birth': row[5],
                'preferred_branch': preferred_branch,
                'phone': mobile or phone2,
                'phone_alt': phone2 if mobile else '',
                'softech_ptclassifcode': str(row[8] or '').strip(),
            }

            # Sync ischronic if the Customer model carries the field
            if hasattr(Customer, 'is_chronic_softech'):
                defaults['is_chronic_softech'] = bool(row[9])

            Customer.objects.update_or_create(
                softech_id=softech_id,
                defaults=defaults,
            )
            count += 1
        except Exception as e:
            logger.warning(f"Customer sync error branchcustcode={row[1]}: {e}")

    SyncLog.objects.create(
        sync_run=sync_run,
        table_name='localcustomers',
        records_processed=count
    )
    return count


def sync_sales(conn, sync_run, full_history=False):
    """
    Purchase history from stktrans lines (personcode direct on line).
    Groups lines into invoices by (personcode, branchcode, doccode, docnumber, docdate).
    doccode '115' = sales, '30' = returns (negative qty).
    """
    cursor = conn.cursor()
    query = QUERY_CUSTOMER_SALES_LINES_FULL if full_history else QUERY_CUSTOMER_SALES_LINES_RECENT
    cursor.execute(query)
    rows = cursor.fetchall()

    # Group lines → invoices
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

    count = 0
    for (personcode, branchcode, doccode, docnumber, docdate), lines in invoices.items():
        try:
            customer = Customer.objects.filter(softech_id=personcode).first()
            branch = Branch.objects.filter(softech_branch_id=branchcode).first()
            if not customer or not branch:
                continue

            # docdate is now a Python datetime (converted by CursorWrapper)
            if isinstance(docdate, _dt.datetime):
                date_str = docdate.strftime('%Y%m%d')
            else:
                date_str = str(docdate)[:10].replace('-', '') if docdate else 'nodate'
            invoice_id = f"{branchcode}-{doccode}-{docnumber}-{date_str}"
            total = sum(Decimal(str(line[8])) if line[8] else Decimal(0) for line in lines)

            purchase, _ = PurchaseHistory.objects.update_or_create(
                softech_invoice_id=invoice_id,
                defaults={
                    'customer': customer,
                    'branch': branch,
                    'invoice_date': docdate if isinstance(docdate, _dt.datetime) else None,
                    'total_amount': total,
                    'doc_code': doccode,
                }
            )

            for line in lines:
                item = Item.objects.filter(softech_id=str(line[5])).first()
                if item:
                    PurchaseHistoryLine.objects.update_or_create(
                        purchase=purchase,
                        item=item,
                        defaults={
                            'quantity': Decimal(str(line[6])) if line[6] else 0,
                            'unit_price': Decimal(str(line[7])) if line[7] else 0,
                            'line_total': Decimal(str(line[8])) if line[8] else 0,
                        }
                    )
            count += 1
        except Exception as e:
            logger.warning(f"Sales sync error: {e}")

    SyncLog.objects.create(sync_run=sync_run, table_name='stktrans', records_processed=count)
    return count


def sync_users(conn, sync_run):
    """
    Real columns: userid, usercode, usergroup, user_nomore, branchcode, storecode
    user_nomore=0 means active. usercode used as Django username.
    """
    cursor = conn.cursor()
    cursor.execute(QUERY_USERS)
    count = 0
    for row in cursor.fetchall():
        try:
            login = str(row[1] or row[0]).strip()   # usercode
            if not login:
                continue
            django_user, _ = DjangoUser.objects.get_or_create(
                username=login,
                defaults={'is_active': True}
            )
            branch = Branch.objects.filter(
                softech_branch_id=str(row[4])
            ).first() if row[4] else None
            StaffProfile.objects.update_or_create(
                user=django_user,
                defaults={
                    'branch': branch,
                    'softech_username': login,
                    'softech_user_id': str(row[0]),
                    'role': 'salesperson',
                }
            )
            count += 1
        except Exception as e:
            logger.warning(f"User sync error: {e}")
    SyncLog.objects.create(sync_run=sync_run, table_name='users', records_processed=count)
    return count


# ── SCHEDULER ──────────────────────────────────────────────────────────────────
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
