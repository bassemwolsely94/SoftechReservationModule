"""
python manage.py sync_crm_orders [--minutes N] [--full] [--source {hq,branches,all}]

Syncs delivery orders from ALL SOFTECH sources into DeliveryOrder records.

Sources:
  Source 1 — HQ (192.168.1.8):
    piccrmorders WHERE crmbranchcode='100'  → source_type='call_center'

  Source 2 — Branch DBs:
    piccrmorders WHERE crmbranchcode=branchcode  → source_type='branch_pos' (historical)

  Source 3 — Branch DBs (LIVE PENDING QUEUE):
    piccrmorders5 WHERE docnumber=0  → source_type='branch_pos' (live/pending)
    This is the ACTUAL pending orders table. An order appears here while it is
    being prepared or dispatched (docnumber=0). Once invoiced, it is REMOVED.
    This table is EXCLUSIVE — rows do NOT appear in piccrmorders.

Deduplication key:  (softech_crm_branch, softech_crm_order_no) — unique per order globally.

Status mapping (orderstatus):
  NULL / 10  → created
  20         → pending_review
  30         → preparing
  44         → ready
  50         → out_for_delivery
  90         → delivered
  100        → cancelled
"""
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger('elrezeiky.delivery.sync')

STATUS_MAP = {
    None: 'created',
    10:   'created',
    20:   'pending_review',
    30:   'preparing',
    44:   'ready',
    50:   'out_for_delivery',
    90:   'delivered',
    100:  'cancelled',
}


def _map_status(softech_status):
    return STATUS_MAP.get(softech_status, 'created')


def _sync_source(cursor, query, branch_map, customer_map, source_type,
                 created_count, updated_count, skipped_count, error_count,
                 create_lookback_days=None):
    """
    Core sync loop: execute `query`, upsert into DeliveryOrder.
    Returns updated (created, updated, skipped, error) counts.

    create_lookback_days: if set, NEW orders are only created for actionable
    documents. A SOFTECH row whose orderstatus is NULL and whose order date is
    older than this window is treated as untracked historical data (a completed
    past sale that never got CRM status tracking), NOT a new pending delivery,
    and is skipped on the CREATE path. Updates to existing orders are unaffected.
    This is the guard against the historical-backfill flood that produced 194k
    ancient status='created' orders. See docs / delivery cleanup command.
    """
    from apps.delivery.models import DeliveryOrder, DeliveryStatusLog

    create_cutoff = None
    if create_lookback_days is not None:
        create_cutoff = timezone.now() - timezone.timedelta(days=create_lookback_days)

    cursor.execute('SET ROWCOUNT 0')
    cursor.execute(query)
    rows = cursor.fetchall()

    if not rows:
        return created_count, updated_count, skipped_count, error_count

    # Collect existing DeliveryOrder records for this batch using the composite key.
    # softech_crm_order_no alone is NOT unique — it's per-branch sequential.
    # We must always query by (softech_crm_branch, softech_crm_order_no) together.
    crm_keys = [
        (str(r[0]).strip() if r[0] else '', r[1])
        for r in rows if r[1] is not None
    ]
    crm_nos = [k[1] for k in crm_keys]
    crm_branches = list({k[0] for k in crm_keys})

    existing_qs = DeliveryOrder.objects.filter(
        softech_crm_order_no__in=crm_nos,
        softech_crm_branch__in=crm_branches,
    )
    existing = {
        (o.softech_crm_branch, o.softech_crm_order_no): o
        for o in existing_qs
    }

    for row in rows:
        try:
            row_data      = row[:23]  # guard against future column additions
            crm_branch    = row_data[0]
            crm_no        = row_data[1]
            branch_code   = row_data[2]
            doc_code      = row_data[3]
            order_dt      = row_data[4]
            order_user    = row_data[5]
            order_value   = row_data[6]
            ph_code       = row_data[7]
            driver_code   = row_data[8]
            drv_out_dt    = row_data[9]
            drv_in_dt     = row_data[11]
            to_br_dt      = row_data[14]
            deliver_dt    = row_data[17]
            softech_status = row_data[18]
            # New columns [20..22] — docnumber5, docdate5, docnumber
            doc_number5   = row_data[20] if len(row_data) > 20 else None
            doc_date5     = row_data[21] if len(row_data) > 21 else None
            doc_number    = row_data[22] if len(row_data) > 22 else None

            if crm_no is None:
                skipped_count += 1
                continue

            crm_branch_str = str(crm_branch).strip() if crm_branch else ''
            key = (crm_branch_str, crm_no)

            branch   = branch_map.get(str(branch_code).strip()) if branch_code else None
            customer = customer_map.get(str(ph_code).strip()) if ph_code else None

            customer_name  = customer.name  if customer else ''
            customer_phone = customer.phone if customer else ''
            order_value    = float(order_value) if order_value is not None else 0.0
            django_status  = _map_status(softech_status)

            ordered_at    = order_dt or timezone.now()
            assigned_at   = to_br_dt
            dispatched_at = drv_out_dt
            delivered_at  = drv_in_dt or deliver_dt

            # Normalise doc_number5 (Sybase may return it as float e.g. 712505.0)
            doc_number5_int = int(float(doc_number5)) if doc_number5 and float(doc_number5) > 0 else None
            doc_number_int  = int(float(doc_number))  if doc_number  and float(doc_number)  > 0 else None
            doc_date5_date  = doc_date5.date() if hasattr(doc_date5, 'date') else None

            if key in existing:
                # ── UPDATE ────────────────────────────────────────────────
                order      = existing[key]
                old_status = order.status
                changed    = False

                if order.softech_order_status != softech_status:
                    order.softech_order_status = softech_status
                    order.status               = django_status
                    changed = True
                if dispatched_at and not order.dispatched_at:
                    order.dispatched_at = dispatched_at
                    changed = True
                if delivered_at and not order.delivered_at:
                    order.delivered_at = delivered_at
                    changed = True
                if order_value and order.total_value != order_value:
                    order.total_value = order_value
                    changed = True
                # Update docnumber5 if newly set
                if doc_number5_int and not order.softech_doc_number5:
                    order.softech_doc_number5 = doc_number5_int
                    changed = True
                if doc_date5_date and not order.softech_doc_date5:
                    order.softech_doc_date5 = doc_date5_date
                    changed = True
                # Update final invoice number when order is invoiced (docnumber > 0)
                if doc_number_int and not order.softech_doc_ref:
                    order.softech_doc_ref = str(doc_number_int)
                    changed = True

                if changed:
                    order.save(update_fields=[
                        'softech_order_status', 'status',
                        'dispatched_at', 'delivered_at', 'total_value',
                        'softech_doc_number5', 'softech_doc_date5', 'softech_doc_ref',
                        'updated_at',
                    ])
                    if old_status != django_status:
                        DeliveryStatusLog.objects.create(
                            order=order,
                            from_status=old_status,
                            to_status=django_status,
                            source='import',
                            notes=f'SOFTECH orderstatus={softech_status}',
                        )
                    updated_count += 1

            else:
                # ── CREATE ────────────────────────────────────────────────
                # Guard: never back-fill untracked historical documents as new
                # pending orders. A NULL SOFTECH status on an old order date is
                # a completed past sale that never got CRM tracking — not an
                # actionable delivery. (Genuinely new orders have a recent
                # order date, so ordered_at defaults to now when order_dt is
                # NULL and are not skipped.)
                if create_cutoff is not None and softech_status is None and ordered_at < create_cutoff:
                    skipped_count += 1
                    continue

                order = DeliveryOrder(
                    softech_crm_order_no   = crm_no,
                    softech_crm_branch     = crm_branch_str,
                    softech_branch_code    = str(branch_code).strip() if branch_code else '',
                    softech_order_usercode = str(order_user).strip() if order_user else '',
                    softech_order_status   = softech_status,
                    # docnumber5 = the pre-invoice staging document (PRIMARY SOFTECH REF)
                    softech_doc_number5    = doc_number5_int,
                    softech_doc_date5      = doc_date5_date,
                    # docnumber = final invoice (0 while pending)
                    softech_doc_ref        = str(doc_number_int) if doc_number_int else '',
                    source_type            = source_type,
                    branch                 = branch,
                    customer               = customer,
                    customer_name          = customer_name,
                    customer_phone         = customer_phone,
                    total_value            = order_value,
                    status                 = django_status,
                    ordered_at             = ordered_at,
                    assigned_at            = assigned_at,
                    dispatched_at          = dispatched_at,
                    delivered_at           = delivered_at,
                )
                order.save()
                DeliveryStatusLog.objects.create(
                    order=order,
                    from_status='',
                    to_status=django_status,
                    source='import',
                    notes=f'SOFTECH import: crmBranch={crm_branch_str} crmorderno={crm_no}',
                )
                created_count += 1

        except Exception as e:
            error_count += 1
            logger.warning(f'[delivery sync] Error crmBr={crm_branch} ordno={crm_no}: {e}')

    return created_count, updated_count, skipped_count, error_count


def _apply_branch_status_updates(cursor, minutes, existing_by_key, log_prefix=''):
    """
    Pull piccrmorderstatus changes from a branch DB and apply them to existing
    DeliveryOrder records. Handles both CC orders and branch POS orders.
    """
    from apps.delivery.models import DeliveryOrder, DeliveryStatusLog
    from apps.sync.sybase_queries import QUERY_BRANCH_STATUS_UPDATES_RECENT

    try:
        cursor.execute('SET ROWCOUNT 0')
        cursor.execute(QUERY_BRANCH_STATUS_UPDATES_RECENT.format(minutes=minutes))
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f'{log_prefix} status updates query failed: {e}')
        return 0

    applied = 0
    for row in rows:
        try:
            crm_branch, crm_no, branch_code, orderstatus, usercode, trans_time = row
            if crm_no is None or orderstatus is None:
                continue

            crm_branch_str = str(crm_branch).strip() if crm_branch else ''
            django_status  = _map_status(orderstatus)

            order = existing_by_key.get((crm_branch_str, crm_no))
            if not order:
                # Try direct DB lookup
                try:
                    order = DeliveryOrder.objects.get(
                        softech_crm_branch=crm_branch_str,
                        softech_crm_order_no=crm_no,
                    )
                    existing_by_key[(crm_branch_str, crm_no)] = order
                except DeliveryOrder.DoesNotExist:
                    continue

            if order.status != django_status:
                old_status = order.status
                order.softech_order_status = orderstatus
                order.status               = django_status
                if orderstatus == 50 and not order.dispatched_at:
                    order.dispatched_at = trans_time
                if orderstatus == 90 and not order.delivered_at:
                    order.delivered_at = trans_time
                order.save(update_fields=[
                    'softech_order_status', 'status',
                    'dispatched_at', 'delivered_at', 'updated_at',
                ])
                DeliveryStatusLog.objects.create(
                    order=order,
                    from_status=old_status,
                    to_status=django_status,
                    source='import',
                    notes=f'{log_prefix} piccrmorderstatus: st={orderstatus} user={usercode}',
                )
                applied += 1
        except Exception as e:
            logger.warning(f'{log_prefix} status update error: {e}')

    return applied


class Command(BaseCommand):
    help = 'Sync piccrmorders from HQ + all branch DBs into DeliveryOrder'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=15,
                            help='Incremental window in minutes (default 15). Ignored with --full.')
        parser.add_argument('--full', action='store_true',
                            help='Full sync: pull all active orders from all sources.')
        parser.add_argument('--source', choices=['hq', 'branches', 'all'], default='all',
                            help='Which sources to sync (default: all).')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.delivery.models import DeliveryOrder
        from apps.branches.models import Branch
        from apps.customers.models import Customer
        from apps.sync.sybase_queries import (
            QUERY_PICCRMORDERS_ACTIVE,
            QUERY_PICCRMORDERS_RECENT,
            QUERY_BRANCH_PICCRMORDERS_ACTIVE,
            QUERY_BRANCH_PICCRMORDERS_RECENT,
            QUERY_BRANCH_PICCRMORDERS5_ALL,
            QUERY_BRANCH_PICCRMORDERS5_RECENT,
        )

        minutes = options['minutes']
        full    = options['full']
        source  = options['source']

        # Lookback window for CREATE guard + full-sync SQL date floor.
        # Prevents re-importing years of NULL-status historical rows as new
        # pending orders (root cause of the 194k stale 'created' backlog).
        from apps.config.services import get_setting
        try:
            lookback_days = int(get_setting('delivery_sync_full_lookback_days', default='30'))
        except (ValueError, TypeError):
            lookback_days = 30

        mode = 'Full' if full else f'Incremental ({minutes}m)'
        self.stdout.write(f'[delivery sync] {mode} | source={source} | create-lookback={lookback_days}d')

        # ── Pre-cache branches & customers ───────────────────────────────────
        branch_map = {
            str(b.softech_branch_id): b
            for b in Branch.objects.filter(softech_branch_id__isnull=False)
        }
        customer_map = {
            str(c.softech_pic): c
            for c in Customer.objects.filter(softech_pic__isnull=False).only(
                'id', 'softech_pic', 'name', 'phone'
            )
        }

        # Shared counters
        created = updated = skipped = errors = 0
        status_applied = 0

        # ── HQ sync (call center orders) ─────────────────────────────────────
        if source in ('hq', 'all'):
            try:
                hq_conn   = get_sybase_connection()
                hq_cursor = hq_conn.cursor()
                hq_query  = (
                    QUERY_PICCRMORDERS_ACTIVE.format(days=lookback_days) if full
                    else QUERY_PICCRMORDERS_RECENT.format(minutes=minutes)
                )
                created, updated, skipped, errors = _sync_source(
                    hq_cursor, hq_query, branch_map, customer_map,
                    'call_center', created, updated, skipped, errors,
                    create_lookback_days=lookback_days,
                )
                hq_conn.close()
                self.stdout.write(f'  HQ: c={created} u={updated} sk={skipped} err={errors}')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  HQ failed: {e}'))

        # ── Branch sync (branch POS orders + status updates) ─────────────────
        watchdog_results = {}   # host → {branch_id, ok, elapsed_ms, error}
        if source in ('branches', 'all'):
            import time as _time
            branch_dbs = Branch.objects.filter(db_host__gt='', is_active=True)
            existing_cache = {}

            for branch in branch_dbs:
                prefix = f'  Branch {branch.softech_branch_id} ({branch.db_host})'
                _t0 = _time.monotonic()
                try:
                    br_conn   = get_branch_connection(
                        branch.db_host, branch.db_port, branch.db_name
                    )
                    br_cursor = br_conn.cursor()
                    # Reachable — record connect latency for the watchdog
                    watchdog_results[branch.db_host] = {
                        'branch_id':  str(branch.softech_branch_id),
                        'ok':         True,
                        'elapsed_ms': (_time.monotonic() - _t0) * 1000,
                        'error':      None,
                    }

                    # Source 2: piccrmorders — branch POS historical orders
                    br_query = (
                        QUERY_BRANCH_PICCRMORDERS_ACTIVE.format(days=lookback_days) if full
                        else QUERY_BRANCH_PICCRMORDERS_RECENT.format(minutes=minutes)
                    )
                    c_before = created
                    created, updated, skipped, errors = _sync_source(
                        br_cursor, br_query, branch_map, customer_map,
                        'branch_pos', created, updated, skipped, errors,
                        create_lookback_days=lookback_days,
                    )
                    new_pos = created - c_before
                    self.stdout.write(f'{prefix} piccrmorders POS: +{new_pos} new')

                    # Source 3: piccrmorders5 — LIVE PENDING QUEUE (docnumber=0)
                    # These are orders actively being processed at the branch.
                    # They are exclusive to this table and not in piccrmorders.
                    p5_query = (
                        QUERY_BRANCH_PICCRMORDERS5_ALL if full
                        else QUERY_BRANCH_PICCRMORDERS5_RECENT.format(minutes=minutes)
                    )
                    c_before5 = created
                    created, updated, skipped, errors = _sync_source(
                        br_cursor, p5_query, branch_map, customer_map,
                        'branch_pos', created, updated, skipped, errors,
                        create_lookback_days=lookback_days,
                    )
                    new_p5 = created - c_before5
                    if new_p5 or full:
                        self.stdout.write(f'{prefix} piccrmorders5 LIVE: +{new_p5} new')

                    # Apply status updates from piccrmorderstatus
                    sa = _apply_branch_status_updates(
                        br_cursor, minutes, existing_cache,
                        log_prefix=prefix,
                    )
                    status_applied += sa
                    if sa:
                        self.stdout.write(f'{prefix} status updates applied: {sa}')

                    br_conn.close()

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'{prefix} failed: {e}'))
                    logger.error(f'Branch sync failed ({branch.db_host}): {e}')
                    watchdog_results[branch.db_host] = {
                        'branch_id':  str(branch.softech_branch_id),
                        'ok':         False,
                        'elapsed_ms': (_time.monotonic() - _t0) * 1000,
                        'error':      str(e),
                    }

        # ── Watchdog: record reachability, surface chronic offline branches ──
        if watchdog_results:
            try:
                from apps.delivery.branch_watchdog import record_run
                summary = record_run(watchdog_results)
                self.stdout.write(summary)
            except Exception as wd_err:
                logger.warning(f'[watchdog] record failed: {wd_err}')

        msg = (
            f'[delivery sync] Done — '
            f'created={created} updated={updated} '
            f'status_applied={status_applied} '
            f'skipped={skipped} errors={errors}'
        )
        self.stdout.write(self.style.SUCCESS(msg))
        logger.info(msg)
