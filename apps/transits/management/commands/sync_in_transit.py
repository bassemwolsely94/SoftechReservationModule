"""
apps/transits/management/commands/sync_in_transit.py

SOFTECH → local cache sync for inter-branch transfers (doccode='125').

KEY SOFTECH FACTS (empirically verified 2026-07-20, e.g. doc 103486):
  • Document numbers are a sequence PER (branch, doc-type) — NOT globally
    unique. The same docnumber exists simultaneously for unrelated documents
    (e.g. doccode 115) at other branches. Every query MUST filter doccode
    (and branch where applicable); identity = (docnumber, supplying branch).
  • The 125 header carries its true destination: stktransm.cust_branch_code.
  • The receipt is a doccode='25' document at the RECEIVING branch with its
    OWN docnumber (receiver's sequence); it links back to the 125 via
    stktransm.docnumber2 = the 125's docnumber (cust_branch_code = sender).

What this command does:
  1. Queries stktransm for doccode='125' headers in the lookback window
     (default 30 days), including cust_branch_code = the destination.
  2. For each document:
     a. Fetches the issued line items (stktrans, doccode='125', source branch).
     b. Detects receipt via the 25-header (docnumber2 link, see above).
     c. When received, fetches the 25-document's own lines and reconciles
        them against the issued side → missing items / qty diffs / value diff.
  3. Upserts into InTransitTransfer keyed by (docnumber, supplying branch) —
     creates new records, updates changed ones, and CLEARS stale receipt data
     recorded by the old same-docnumber heuristic (false receipts).
  4. Refreshes computed fields (priority, days_in_transit, cancellation_available).
  5. Fires notifications for new alerts (day 4 warning, day 7 high, day 14 critical)
     plus a one-off alert whenever a 125↔25 discrepancy is first detected.
  6. Attempts to link to existing TransferRequest by erp_reference match.

ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT/UPDATE/DELETE on SOFTECH.
"""
import datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger('elrezeiky.transits')


# ── SOFTECH query constants ───────────────────────────────────────────────────
# doccode '125' = صرف تبادل بين الفروع (inter-branch issue from supplying branch)
# doccode '25'  = استلام تبادل بين الفروع (receipt at the destination branch)

_QUERY_TRANSIT_HEADERS = """
    SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate,
           sm.docvalue, sm.usercode, sm.storecode, sm.cust_branch_code
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.doccode = '125'
      AND sm.docdate >= ?
    ORDER BY sm.docdate DESC
"""

# Receipt header at the destination: its docnumber2 points back at the 125's
# docnumber, cust_branch_code = the sending branch. docdate bound helps the
# optimizer and is always true (receipt can't precede issue).
_QUERY_RECEIPT = """
    SELECT sm.docnumber, sm.docdate
    FROM SOFTECHDB9.dbo.stktransm sm
    WHERE sm.doccode = '25'
      AND sm.branchcode = ?
      AND sm.cust_branch_code = ?
      AND sm.docnumber2 = ?
      AND sm.docdate >= ?
"""

# Line items of ONE document side: (docnumber, branch, doccode) — the doccode
# filter is essential because docnumbers collide across document types.
# itemexpirydate = batch expiry, item_partno = batch/lot number (رقم التشغيلة) —
# both feed the picking-sheet export. If the rich query fails on this SOFTECH
# build (column missing), we fall back to the legacy column set.
_QUERY_ITEMS = """
    SELECT st.itemcode, st.transqty, st.transprice_total, st.storecode, st.trans_time,
           st.itemexpirydate, st.item_partno
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
      AND st.branchcode = ?
      AND st.doccode = ?
    ORDER BY st.itemcode
"""

_QUERY_ITEMS_LEGACY = """
    SELECT st.itemcode, st.transqty, st.transprice_total, st.storecode, st.trans_time
    FROM SOFTECHDB9.dbo.stktrans st
    WHERE st.docnumber = ?
      AND st.branchcode = ?
      AND st.doccode = ?
    ORDER BY st.itemcode
"""

NEAR_EXPIRY_DAYS = 45   # keep in sync with InTransitTransfer.has_near_expiry


class Command(BaseCommand):
    help = (
        'Sync SOFTECH inter-branch transfers (doccode=125) into InTransitTransfer cache. '
        'READ-ONLY on Sybase. Safe to run at any frequency.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='How many days back to scan SOFTECH (default: 30)',
        )
        parser.add_argument(
            '--doc', type=str, default='',
            help='Sync a specific document number only (for debugging)',
        )
        parser.add_argument(
            '--date', type=str, default='',
            help='With --doc: approximate issue date (YYYY-MM-DD) — bounds the '
                 'header scan so it can use the docdate index (stktransm has '
                 'no index on docnumber alone)',
        )

    def handle(self, *args, **options):
        days   = options['days']
        single = options['doc'].strip()
        single_date = options.get('date', '').strip()
        start  = timezone.now()

        self.stdout.write(
            f'[sync_in_transit] Starting — lookback {days}d'
            + (f', single doc={single}' if single else '')
        )
        logger.info('[sync_in_transit] Starting sync (lookback=%dd)', days)

        try:
            conn = self._get_connection()
        except Exception as exc:
            logger.error('[sync_in_transit] Cannot connect to SOFTECH: %s', exc)
            self.stderr.write(f'SOFTECH connection failed: {exc}')
            return

        try:
            stats = self._sync(conn, days, single, single_date)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        elapsed = (timezone.now() - start).total_seconds()
        msg = (
            f'[sync_in_transit] Done in {elapsed:.1f}s — '
            f'created={stats["created"]}, updated={stats["updated"]}, '
            f'skipped={stats["skipped"]}, errors={stats["errors"]}'
        )
        self.stdout.write(msg)
        logger.info(msg)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_connection(self):
        from config.sybase import get_sybase_connection
        return get_sybase_connection()

    def _sync(self, conn, days: int, single_doc: str, single_date: str = '') -> dict:
        """Main sync loop. Returns stats dict."""
        from django.db import transaction
        from apps.branches.models import Branch
        from apps.transits.models import (
            InTransitAuditEvent, InTransitNote, InTransitTransfer,
            compute_reconciliation,
        )
        from apps.transfers.models import TransferRequest

        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}

        # ── Build branch lookup: softech_branch_id → Branch ──────────────────
        branch_map = {
            str(b.softech_branch_id).strip(): b
            for b in Branch.objects.filter(is_active=True)
        }

        # ── Build erp_reference → TransferRequest lookup ──────────────────────
        # Only 'sent_to_erp' and 'completed' transfers have a valid erp_reference
        tr_map: dict[str, 'TransferRequest'] = {}
        for tr in TransferRequest.objects.filter(
            status__in=('sent_to_erp', 'completed'),
            erp_reference__gt='',
        ).only('id', 'erp_reference'):
            tr_map[str(tr.erp_reference).strip()] = tr

        # ── Fetch SOFTECH headers ─────────────────────────────────────────────
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        cur   = conn.cursor()

        try:
            if single_doc:
                # docnumber is DECIMAL in Sybase — pass an int (CHAR→DECIMAL
                # implicit conversion is refused).
                try:
                    single_param = int(float(single_doc))
                except (ValueError, TypeError):
                    single_param = single_doc
                sql = (
                    "SELECT sm.docnumber, sm.doccode, sm.branchcode, sm.docdate, "
                    "sm.docvalue, sm.usercode, sm.storecode, sm.cust_branch_code "
                    "FROM SOFTECHDB9.dbo.stktransm sm "
                    "WHERE sm.doccode = '125' AND sm.docnumber = ?"
                )
                params = [single_param]
                if single_date:
                    # bound the scan around the known date → docdate index
                    sql += ' AND sm.docdate >= ? AND sm.docdate <= ?'
                    import datetime as _dt
                    d = _dt.date.fromisoformat(single_date)
                    params += [(d - _dt.timedelta(days=3)).isoformat(),
                               (d + _dt.timedelta(days=3)).isoformat()]
                cur.execute(sql, params)
            else:
                cur.execute(_QUERY_TRANSIT_HEADERS, [since])
            rows = cur.fetchall() or []
        except Exception as exc:
            logger.error('[sync_in_transit] stktransm query failed: %s', exc)
            return stats
        finally:
            try:
                cur.close()
            except Exception:
                pass

        logger.info('[sync_in_transit] %d headers fetched from SOFTECH', len(rows))

        # (doc_num, supply_code) keys handled by the header-window loop below —
        # so the wide re-check pass afterwards can skip them (no double work).
        processed_keys: set = set()

        # ── Process each document ─────────────────────────────────────────────
        for hdr in rows:
            try:
                raw_doc = hdr[0]
                try:
                    doc_num = str(int(float(str(raw_doc))))
                except (ValueError, TypeError):
                    doc_num = str(raw_doc).strip()

                supply_code = str(hdr[2] or '').strip()
                processed_keys.add((doc_num, supply_code))
                raw_date    = hdr[3]

                if isinstance(raw_date, datetime.datetime):
                    issue_date = raw_date.date()
                elif isinstance(raw_date, datetime.date):
                    issue_date = raw_date
                else:
                    try:
                        issue_date = datetime.date.fromisoformat(str(raw_date)[:10])
                    except Exception:
                        stats['skipped'] += 1
                        continue

                doc_value  = _safe_decimal(hdr[4])
                user_code  = str(hdr[5] or '').strip()
                store_code = str(hdr[6] or '').strip()
                # Authoritative destination from the 125 header itself
                recv_code  = str(hdr[7] or '').strip() if len(hdr) > 7 else ''

                # ── Detect receipt: the 25-doc at the destination whose
                #    docnumber2 points back at this 125 ─────────────────────────
                received_date, receipt_doc = self._detect_receipt(
                    conn, doc_num, supply_code, recv_code, issue_date
                )

                # ── Get line items (issued / 125 side) ────────────────────────
                items_data, item_count, total_qty = self._fetch_items(
                    conn, doc_num, supply_code, branch_map, doccode='125'
                )

                # ── Reconcile against the receipt (25) document's own lines ───
                received_items = []
                if received_date and receipt_doc:
                    received_items, _, _ = self._fetch_items(
                        conn, receipt_doc, recv_code, branch_map, doccode='25'
                    )

                # ── Determine transit status ──────────────────────────────────
                if received_date and receipt_doc:
                    # Only reconcile when we actually fetched the 25-side lines;
                    # an empty fetch must NOT be read as "everything missing".
                    if received_items:
                        recon = compute_reconciliation(items_data, received_items)
                        t_status = 'erp_mismatch' if recon['has_discrepancy'] else 'received'
                    else:
                        t_status = 'received'
                else:
                    t_status = 'in_transit'
                    received_date = None
                    receipt_doc = ''

                # ── Cancellation window ───────────────────────────────────────
                cancel_expires = issue_date + datetime.timedelta(
                    days=_get_cancel_window()
                )

                # ── Upsert (identity = docnumber + supplying branch) ──────────
                with transaction.atomic():
                    existing = InTransitTransfer.objects.filter(
                        erp_doc_number=doc_num,
                        erp_supplying_branch_code=supply_code,
                    ).first()

                    if existing:
                        changed = False
                        prev_status = existing.transit_status

                        # Only update ERP-derived fields; leave local-only fields intact
                        if existing.transit_status not in ('force_closed',):
                            if existing.transit_status != t_status:
                                existing.transit_status = t_status
                                changed = True
                            # Receiver is authoritative from the 125 header —
                            # corrects rows polluted by the old same-docnumber
                            # guess (unrelated doc types at other branches).
                            if recv_code and existing.erp_receiving_branch_code != recv_code:
                                existing.erp_receiving_branch_code = recv_code
                                existing.receiving_branch = branch_map.get(recv_code)
                                changed = True
                            if existing.issue_date != issue_date:
                                existing.issue_date = issue_date
                                changed = True
                            if received_date and existing.erp_received_date != received_date:
                                existing.erp_received_date = received_date
                                changed = True
                            if receipt_doc and existing.erp_receipt_doc_number != receipt_doc:
                                existing.erp_receipt_doc_number = receipt_doc
                                changed = True
                            if doc_value and existing.doc_value != doc_value:
                                existing.doc_value = doc_value
                                changed = True
                            # Compare full snapshots (not just the count) so
                            # enrichment backfills (expiry/batch) reach records
                            # synced before those columns were fetched.
                            if items_data and existing.items_snapshot != items_data:
                                existing.item_count = item_count
                                existing.total_quantity = total_qty
                                existing.items_snapshot = items_data
                                changed = True
                            # Reconcile 125↔25 once the receiving side exists
                            if received_items:
                                existing.apply_reconciliation(received_items)
                            elif t_status == 'in_transit' and (
                                existing.erp_received_date
                                or existing.received_items_snapshot
                                or existing.has_discrepancy
                            ):
                                # No real 25-receipt exists — clear the FALSE
                                # receipt data the old heuristic recorded.
                                existing.erp_received_date = None
                                existing.erp_receipt_doc_number = ''
                                existing.received_items_snapshot = []
                                existing.reconciliation = {}
                                existing.has_discrepancy = False
                                changed = True

                        existing.last_synced_at = timezone.now()
                        existing.refresh_computed_fields()
                        existing.save()

                        if changed:
                            stats['updated'] += 1
                            InTransitAuditEvent.log(
                                existing, 'synced',
                                detail=f'ERP sync — status={t_status}'
                            )
                        else:
                            stats['skipped'] += 1

                        # First-time discrepancy detection → alert
                        if t_status == 'erp_mismatch' and prev_status != 'erp_mismatch':
                            self._notify_mismatch(existing)

                    else:
                        # New record
                        supply_branch = branch_map.get(supply_code)
                        recv_branch   = branch_map.get(recv_code) if recv_code else None

                        # Try to link to existing TransferRequest
                        linked_tr = tr_map.get(doc_num)

                        tt = InTransitTransfer(
                            erp_doc_number             = doc_num,
                            erp_doc_code               = '125',
                            erp_supplying_branch_code  = supply_code,
                            erp_receiving_branch_code  = recv_code or '',
                            erp_receipt_doc_number     = receipt_doc or '',
                            erp_user_code              = user_code,
                            erp_store_code             = store_code,
                            issue_date                 = issue_date,
                            erp_received_date          = received_date,
                            cancellation_expires_at    = cancel_expires,
                            supplying_branch           = supply_branch,
                            receiving_branch           = recv_branch,
                            linked_request             = linked_tr,
                            doc_value                  = doc_value,
                            item_count                 = item_count,
                            total_quantity             = total_qty,
                            items_snapshot             = items_data,
                            transit_status             = t_status,
                            last_synced_at             = timezone.now(),
                        )
                        if received_items:
                            tt.apply_reconciliation(received_items)
                        tt.refresh_computed_fields()
                        tt.save()

                        InTransitNote.log_system(
                            tt,
                            f'تم اكتشاف المستند {doc_num} في SOFTECH (doccode=125) '
                            f'من الفرع {supply_code}',
                        )
                        InTransitAuditEvent.log(tt, 'synced', detail='First discovered in ERP sync')

                        if linked_tr:
                            InTransitAuditEvent.log(
                                tt, 'linked',
                                detail=f'ربط تلقائي بطلب {linked_tr.request_number}',
                            )

                        if t_status == 'erp_mismatch':
                            self._notify_mismatch(tt)

                        stats['created'] += 1

            except Exception as exc:
                logger.warning(
                    '[sync_in_transit] Error processing doc %s: %s',
                    hdr[0] if hdr else '?', exc, exc_info=True,
                )
                stats['errors'] += 1

        # ── Wide receipt re-check ─────────────────────────────────────────────
        # The header scan above only covers the recent `days` window, so a doc
        # RECEIVED after it aged out of that window would stay 'in_transit'
        # forever. Re-check EVERY still-open record (any age) for a receipt now.
        # Skipped in single-doc debug mode.
        if not single_doc:
            self._recheck_open_transfers(conn, branch_map, processed_keys, stats)

        # ── Fire alerts for overdue in-transit transfers ──────────────────────
        self._fire_alerts()

        return stats

    def _recheck_open_transfers(self, conn, branch_map: dict,
                                processed_keys: set, stats: dict):
        """
        Re-detect receipts for open 'in_transit' records of ANY age — closing the
        gap left by the recent-only header scan. For each open record not already
        handled this run, run _detect_receipt; if a real 25-receipt now exists,
        fetch its lines, reconcile, and flip the status to received/erp_mismatch.

        Orphan/duplicate 125 docs (no 25 ever links back to them) correctly stay
        'in_transit' — there is genuinely no receipt. READ-ONLY on Sybase.
        """
        from django.db import transaction
        from apps.transits.models import (
            InTransitAuditEvent, InTransitTransfer, compute_reconciliation,
        )

        open_qs = (
            InTransitTransfer.objects
            .filter(transit_status='in_transit')
            .exclude(erp_receiving_branch_code='')
        )
        rechecked = resolved = 0
        for tt in open_qs.iterator():
            key = (tt.erp_doc_number, tt.erp_supplying_branch_code)
            if key in processed_keys:
                continue   # already handled by the header-window loop
            rechecked += 1
            try:
                received_date, receipt_doc = self._detect_receipt(
                    conn, tt.erp_doc_number, tt.erp_supplying_branch_code,
                    tt.erp_receiving_branch_code, tt.issue_date,
                )
                if not (received_date and receipt_doc):
                    continue   # still genuinely un-received (or orphan doc)

                received_items, _, _ = self._fetch_items(
                    conn, receipt_doc, tt.erp_receiving_branch_code,
                    branch_map, doccode='25',
                )
                if received_items:
                    recon = compute_reconciliation(tt.items_snapshot, received_items)
                    new_status = 'erp_mismatch' if recon['has_discrepancy'] else 'received'
                else:
                    new_status = 'received'

                with transaction.atomic():
                    prev = tt.transit_status
                    tt.transit_status         = new_status
                    tt.erp_received_date      = received_date
                    tt.erp_receipt_doc_number = receipt_doc
                    if received_items:
                        tt.apply_reconciliation(received_items)
                    tt.last_synced_at = timezone.now()
                    tt.refresh_computed_fields()
                    tt.save()
                    InTransitAuditEvent.log(
                        tt, 'synced',
                        detail=f'wide re-check — receipt {receipt_doc} found → {new_status}',
                    )
                    if new_status == 'erp_mismatch' and prev != 'erp_mismatch':
                        self._notify_mismatch(tt)
                resolved += 1
                stats['updated'] += 1
            except Exception as exc:
                logger.warning('[sync_in_transit] re-check failed doc=%s: %s',
                               tt.erp_doc_number, exc)
                stats['errors'] += 1

        logger.info('[sync_in_transit] wide re-check: %d open re-checked, %d newly received',
                    rechecked, resolved)

    def _detect_receipt(self, conn, doc_num: str, supply_code: str,
                        recv_code: str, issue_date):
        """
        Find the REAL receipt: a doccode='25' header at the destination branch
        whose docnumber2 points back at this 125's docnumber (and whose
        cust_branch_code is the sender). The receipt has its OWN docnumber.

        Returns (received_date, receipt_doc_number) or (None, '').

        NOTE the old heuristic (any stktrans row sharing the docnumber at
        another branch) was WRONG — docnumbers collide across doc types and
        branches, which produced false receivers/receipts (e.g. doc 103486).

        ABSOLUTE RULE: SELECT ONLY on Sybase.
        """
        if not recv_code:
            return None, ''
        try:
            try:
                doc_param = int(doc_num)
            except (ValueError, TypeError):
                doc_param = doc_num

            cur = conn.cursor()
            try:
                cur.execute(_QUERY_RECEIPT, [
                    recv_code, supply_code, doc_param, issue_date.isoformat(),
                ])
                rows = cur.fetchall() or []
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

            if not rows:
                return None, ''

            # Multiple receipts for one issue are not expected; take the latest.
            best = max(rows, key=lambda r: str(r[1] or ''))
            raw_doc, raw_date = best[0], best[1]
            try:
                receipt_doc = str(int(float(str(raw_doc))))
            except (ValueError, TypeError):
                receipt_doc = str(raw_doc).strip()

            recv_date = None
            if isinstance(raw_date, datetime.datetime):
                recv_date = raw_date.date()
            elif isinstance(raw_date, datetime.date):
                recv_date = raw_date
            else:
                try:
                    recv_date = datetime.date.fromisoformat(str(raw_date)[:10])
                except (ValueError, TypeError):
                    pass

            return recv_date, receipt_doc

        except Exception as exc:
            logger.warning('[sync_in_transit] _detect_receipt failed doc=%s: %s',
                           doc_num, exc)
            return None, ''

    def _fetch_items(self, conn, doc_num: str, branch_code: str,
                     branch_map: dict, doccode: str = '125'):
        """
        Fetch line items of ONE document side from stktrans, identified by
        (docnumber, branch, doccode) — the doccode filter prevents pulling
        lines from unrelated same-numbered documents.
        Resolves itemname from local catalog.

        A single item may span MULTIPLE stktrans rows (one per batch/expiry) —
        those rows are AGGREGATED into one snapshot entry: quantities and costs
        summed, earliest expiry kept for FEFO, distinct batches collected. The
        previous version dropped every row after the first, which undercounted
        both quantity and value (e.g. doc 103289: 3 pens across 2 batches were
        shown as 1). item_count therefore stays = distinct items.

        Returns (items_list, item_count, total_quantity).
        """
        items = []
        total_qty_raw = 0

        try:
            try:
                doc_param = int(doc_num)
            except (ValueError, TypeError):
                doc_param = doc_num

            rows = []
            for query in (_QUERY_ITEMS, _QUERY_ITEMS_LEGACY):
                cur = conn.cursor()
                try:
                    cur.execute(query, [doc_param, branch_code, doccode])
                    rows = cur.fetchall() or []
                    break
                except Exception as exc:
                    if query is _QUERY_ITEMS:
                        logger.warning(
                            '[sync_in_transit] rich items query failed doc=%s '
                            '(falling back to legacy columns): %s', doc_num, exc,
                        )
                        continue
                    raise
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass

            if not rows:
                return [], 0, None

            # Resolve itemnames from local catalog in bulk
            item_codes = list({str(r[0] or '').strip() for r in rows if r[0]})
            name_map = _get_item_names(item_codes)

            # Aggregate rows by itemcode (each row = one batch/expiry).
            agg = {}
            order = []
            for row in rows:
                icode = str(row[0] or '').strip()
                if not icode:
                    continue

                qty  = _safe_float(row[1]) or 0.0
                cost = _safe_float(row[2]) or 0.0
                total_qty_raw += qty

                expiry = _safe_date_iso(row[5]) if len(row) > 5 else None
                batch  = (str(row[6]).strip() if len(row) > 6 and row[6] else None)

                entry = agg.get(icode)
                if entry is None:
                    entry = {
                        'itemcode':      icode,
                        'itemname':      name_map.get(icode, icode),
                        'qty':           0.0,
                        'unit_cost':     0.0,
                        'extended_cost': 0.0,
                        'batch':         None,
                        'expiry':        None,
                        'near_expiry':   False,
                        'batches':       [],   # per-batch detail (FEFO / audit)
                    }
                    agg[icode] = entry
                    order.append(icode)

                entry['qty']           += qty
                entry['extended_cost'] += cost
                # earliest expiry wins (FEFO); near_expiry if ANY batch is close
                if expiry and (entry['expiry'] is None or expiry < entry['expiry']):
                    entry['expiry'] = expiry
                entry['near_expiry'] = entry['near_expiry'] or _is_near_expiry(expiry)
                # ONE entry per raw stktrans row (batch line) — complete, so the
                # detail view can list batches on separate lines like SOFTECH.
                entry['batches'].append({
                    'batch':         batch,
                    'expiry':        expiry,
                    'qty':           qty,
                    'unit_cost':     round(cost / qty, 4) if qty else 0,
                    'extended_cost': cost,
                    'near_expiry':   _is_near_expiry(expiry),
                })

            items = []
            for icode in order:
                e = agg[icode]
                q = e['qty']
                e['unit_cost'] = round(e['extended_cost'] / q, 4) if q else 0
                # scalar batch = distinct non-null batch numbers joined (usually 1)
                names = [b['batch'] for b in e['batches'] if b['batch']]
                seen_names, uniq = set(), []
                for n in names:
                    if n not in seen_names:
                        seen_names.add(n); uniq.append(n)
                e['batch'] = ' / '.join(uniq) if uniq else None
                items.append(e)

            return items, len(items), _safe_decimal(total_qty_raw)

        except Exception as exc:
            logger.warning('[sync_in_transit] _fetch_items failed doc=%s: %s', doc_num, exc)
            return [], 0, None

    def _notify_mismatch(self, transfer):
        """
        Fire a one-off alert when a 125↔25 discrepancy is first detected.
        Notifies the receiving branch, the supplying branch, and HQ admins.
        Logs an audit event + an alert note. Non-fatal.
        """
        from apps.transits.models import InTransitAuditEvent, InTransitNote

        recon = transfer.reconciliation or {}
        n_missing = len(recon.get('missing_items', []))
        n_qty     = len(recon.get('qty_diffs', []))
        n_extra   = len(recon.get('extra_items', []))
        value_diff = recon.get('value_diff', 0)

        body = (
            f'تباين بين الصرف (125) والاستلام (25) للمستند {transfer.erp_doc_number}: '
            f'{n_missing} صنف ناقص، {n_qty} فرق كمية، {n_extra} صنف زائد، '
            f'فرق القيمة {value_diff} ج.م.'
        )

        from apps.notifications.models import Notification
        for branch in (transfer.receiving_branch, transfer.supplying_branch):
            if not branch:
                continue
            try:
                Notification.send_to_branch(
                    branch=branch,
                    notification_type='transit_mismatch',
                    title=f'⚠️ تباين تحويل — {transfer.erp_doc_number}',
                    body=body,
                    dedup_key=f'transit_mismatch_{transfer.id}',
                    include_admins=True,
                )
            except Exception as exc:
                logger.warning('[sync_in_transit] mismatch notification failed: %s', exc)

        try:
            InTransitNote.objects.create(
                transfer=transfer, note_type='alert',
                body=f'🔔 {body}', created_by=None,
            )
            InTransitAuditEvent.log(
                transfer, 'alert_sent',
                detail=f'erp_mismatch: missing={n_missing}, qty_diff={n_qty}, '
                       f'extra={n_extra}, value_diff={value_diff}',
            )
        except Exception:
            pass

    def _fire_alerts(self):
        """
        Scan in-transit records and fire notifications for:
        - day 4:  warning (first reminder)
        - day 7:  high priority alert
        - day 14: critical escalation

        Each transfer is alerted at its SINGLE highest applicable level, at most
        once per calendar day (guarded by last_alert_level/last_alert_sent_at, and
        by dedup_once on the day-scoped dedup_key). Transfers older than
        transit_alert_max_days are treated as dead data and skipped so they stop
        re-notifying forever — EXCEPT docs issued 2026+, which are real open
        transfers kept surfaced until received (exempt from the age ceiling).

        NOTE: thresholds are ordered HIGHEST-first and we break on the first match.
        The previous version looped all three thresholds independently and each
        iteration overwrote last_alert_level, which defeated the per-day guard and
        made a >=14-day transfer fire all three alert types on every run.
        """
        from django.db.models import Q
        from apps.transits.models import InTransitAuditEvent, InTransitNote, InTransitTransfer

        today = datetime.date.today()
        max_days = _get_alert_max_days()

        thresholds = [
            (14, 'd14', 'critical',
             lambda t: f'🚨 حرج: تحويل {t.erp_doc_number} عالق منذ {t.days_in_transit} يوم — يحتاج تدخلاً فورياً',
             'transit_critical'),
            (7,  'd7', 'high',
             lambda t: f'تنبيه عاجل: تحويل {t.erp_doc_number} في النقل منذ {t.days_in_transit} يوم — تأخر الاستلام',
             'transit_overdue'),
            (4,  'd4', 'warning',
             lambda t: f'تحويل {t.erp_doc_number} في النقل منذ {t.days_in_transit} يوم — يرجى المتابعة',
             'transit_approaching_cancel'),
        ]

        # Age ceiling (max_days) stops ancient legacy data from re-notifying
        # forever — BUT docs issued 2026+ are real open transfers we must keep
        # surfacing until received, so they are exempt from the ceiling.
        qs = InTransitTransfer.objects.filter(
            transit_status='in_transit',
            days_in_transit__gte=4,
        ).filter(
            Q(days_in_transit__lte=max_days) | Q(issue_date__year__gte=2026)
        ).select_related('supplying_branch', 'receiving_branch')

        for transfer in qs:
            # Pick the single highest threshold this transfer has reached.
            for days_threshold, level, alert_label, body_fn, notif_type in thresholds:
                if transfer.days_in_transit >= days_threshold:
                    break
            else:
                continue

            # Skip if we already sent this level today
            if (
                transfer.last_alert_level == level
                and transfer.last_alert_sent_at
                and transfer.last_alert_sent_at.date() == today
            ):
                continue

            body = body_fn(transfer)

            # Notify receiving branch (they must receive it)
            try:
                from apps.notifications.models import Notification
                target_branch = transfer.receiving_branch or transfer.supplying_branch
                if target_branch:
                    dedup = f'{notif_type}_{transfer.id}_{today.isoformat()}'
                    Notification.send_to_branch(
                        branch=target_branch,
                        notification_type=notif_type,
                        title=f'تحويل قيد النقل — {transfer.erp_doc_number}',
                        body=body,
                        dedup_key=dedup,
                        include_admins=True,
                        dedup_once=True,
                    )
            except Exception as exc:
                logger.warning('[sync_in_transit] notification failed: %s', exc)

            # Also notify supplying branch for critical
            if level == 'd14' and transfer.supplying_branch:
                try:
                    from apps.notifications.models import Notification
                    Notification.send_to_branch(
                        branch=transfer.supplying_branch,
                        notification_type=notif_type,
                        title=f'🚨 تحويل حرج — {transfer.erp_doc_number}',
                        body=body,
                        dedup_key=f'{notif_type}_{transfer.id}_supply_{today.isoformat()}',
                        include_admins=True,
                        dedup_once=True,
                    )
                except Exception:
                    pass

            InTransitNote.objects.create(
                transfer=transfer,
                note_type='alert',
                body=f'🔔 تنبيه تلقائي ({alert_label}): {body}',
                created_by=None,
            )
            InTransitAuditEvent.log(
                transfer, 'alert_sent',
                detail=f'level={level}, days={transfer.days_in_transit}',
            )

            transfer.last_alert_level   = level
            transfer.last_alert_sent_at = timezone.now()
            transfer.alert_notification_count += 1
            transfer.save(update_fields=[
                'last_alert_level', 'last_alert_sent_at',
                'alert_notification_count', 'updated_at',
            ])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_cancel_window() -> int:
    """Read SOFTECH cancellation window from SystemSetting or use default (5 days)."""
    try:
        from apps.config.models import SystemSetting
        return int(SystemSetting.get('transit_cancel_window_days', 5))
    except Exception:
        return 5


def _get_alert_max_days() -> int:
    """Upper age bound for transit alerting (SystemSetting or default 21 days).

    Beyond this a transfer is treated as abandoned/dead ERP data, not an
    actionable alert — so it stops re-notifying every run forever. Set very high
    to effectively disable the cap.
    """
    try:
        from apps.config.models import SystemSetting
        return int(SystemSetting.get('transit_alert_max_days', 21))
    except Exception:
        return 21


def _get_item_names(item_codes: list) -> dict:
    """Bulk-resolve itemcode → itemname from local catalog."""
    if not item_codes:
        return {}
    try:
        from apps.catalog.models import Item
        return dict(
            Item.objects.filter(softech_id__in=item_codes)
            .values_list('softech_id', 'name')
        )
    except Exception:
        return {}


def _safe_date_iso(val):
    """Sybase date/datetime/str → 'YYYY-MM-DD' or None."""
    if not val:
        return None
    if isinstance(val, datetime.datetime):
        return val.date().isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    try:
        return datetime.date.fromisoformat(str(val)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _is_near_expiry(expiry_iso) -> bool:
    """True if the ISO expiry string falls within NEAR_EXPIRY_DAYS from today."""
    if not expiry_iso:
        return False
    try:
        exp = datetime.date.fromisoformat(expiry_iso)
    except (ValueError, TypeError):
        return False
    return exp <= datetime.date.today() + datetime.timedelta(days=NEAR_EXPIRY_DAYS)


def _safe_decimal(val):
    if val is None:
        return None
    try:
        from decimal import Decimal
        return Decimal(str(val))
    except Exception:
        return None


def _safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None
