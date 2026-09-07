"""
apps/reservations/erp_matcher.py

ERP Match Verification for Reservations — checks whether a fulfilled
reservation was actually processed in SOFTECHDB9 as a sales document
(doccode 115 — مبيعات نقدية).

Auto-search mode: when no erp_reference is set, scans stktransm for
doccode=115 documents in a ±3-day window around fulfillment, scores
candidates by item overlap using the (branchcode, docnumber) composite
index in stktrans, and returns the best match.

Called by:
  - `check_erp_match` view action (admin manual trigger)

ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT/UPDATE/DELETE.
"""

import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.reservations')

_QTY_TOLERANCE = 0.20   # 20%
ERP_DOCCODE    = '115'  # مبيعات نقدية — cash sales in SOFTECH


# ── public helpers ─────────────────────────────────────────────────────────────

def apply_match_result(reservation, result: dict) -> None:
    """
    Write ERPMatcher result dict into a Reservation instance in memory.
    Does NOT call .save() — caller handles that.
    """
    from django.utils import timezone

    res_status = result['status']
    reservation.erp_match_status   = res_status
    reservation.erp_match_detail   = result.get('detail', '')
    reservation.erp_last_checked   = timezone.now()
    reservation.erp_check_attempts = (reservation.erp_check_attempts or 0) + 1

    if res_status in ('matched', 'partial'):
        reservation.erp_matched_at       = timezone.now()
        reservation.erp_match_doc_code   = result.get('doc_code', '')
        reservation.erp_match_doc_date   = result.get('doc_date')
        reservation.erp_match_user_code  = result.get('user_code', '')
        reservation.erp_match_user_id    = result.get('user_id', '')
        reservation.erp_match_user_name  = result.get('user_name', '')
        reservation.erp_match_trans_time = result.get('trans_time')
        reservation.erp_match_store_code = result.get('store_code', '')
        reservation.erp_matched_items    = result.get('matched_items', [])
        reservation.erp_receipt_lines    = result.get('receipt_lines', [])
        reservation.erp_customer_info    = result.get('erp_customer') or {}
        raw_val = result.get('doc_value')
        if raw_val is not None:
            try:
                reservation.erp_match_doc_value = Decimal(str(raw_val))
            except InvalidOperation:
                reservation.erp_match_doc_value = None
        else:
            reservation.erp_match_doc_value = None
    else:
        # Clear stale receipt/customer data on not_found re-checks
        reservation.erp_receipt_lines = []
        reservation.erp_customer_info = {}


# Fields to pass to .save(update_fields=[...]) after apply_match_result
ERP_MATCH_UPDATE_FIELDS = [
    'erp_match_status', 'erp_match_detail',
    'erp_last_checked', 'erp_check_attempts',
    'erp_matched_at', 'erp_match_doc_code', 'erp_match_doc_date',
    'erp_match_doc_value', 'erp_match_user_code', 'erp_match_user_id',
    'erp_match_user_name', 'erp_match_trans_time',
    'erp_match_store_code', 'erp_matched_items',
    'erp_receipt_lines', 'erp_customer_info',
    'updated_at',
]


# ── main class ────────────────────────────────────────────────────────────────

class ReservationERPMatcher:
    """
    Verify that a fulfilled Reservation was processed in SOFTECH as a
    sales document (doccode 115 — مبيعات نقدية).

    Usage:
        result = ReservationERPMatcher(reservation).run()

    Returns a dict with keys: status, doc_code, doc_date, doc_value,
    user_code, user_id, user_name, trans_time, store_code,
    matched_items, detail, discovered_doc.
    """

    def __init__(self, reservation):
        self.reservation = reservation

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        res         = self.reservation
        doc_number  = (res.erp_reference or '').strip()
        branch_code = self._branch_code()

        if not branch_code:
            return _not_found(
                'رمز الفرع غير مُعرَّف في SOFTECH — تحقق من إعدادات الفرع'
            )

        discovered_doc = None
        customer_info  = None

        if doc_number:
            header, lines, branch_matched, user_info, customer_info = self._fetch_sybase(
                doc_number, branch_code
            )
        else:
            header, lines, branch_matched, user_info, discovered_doc, customer_info = \
                self._auto_search(branch_code)
            if header is not None:
                doc_number = discovered_doc

        if header is None:
            if doc_number:
                return _not_found(
                    f'المستند رقم {doc_number} غير موجود في SOFTECH '
                    f'(تم البحث للفرع {branch_code} — '
                    f'نوع المستند المطلوب: {ERP_DOCCODE} مبيعات نقدية)'
                )
            else:
                return _not_found(
                    f'لم يُعثر تلقائياً على مستند مبيعات (كود {ERP_DOCCODE}) '
                    f'في SOFTECH يطابق هذا الحجز للفرع {branch_code}. '
                    f'يرجى إدخال رقم المستند يدوياً.'
                )

        doc_code      = str(header[1] or '')
        actual_branch = str(header[2] or '').strip()
        _raw_date     = header[3]
        doc_date      = _raw_date.date() if hasattr(_raw_date, 'date') else _raw_date
        phcode        = str(header[7] or '').strip() if len(header) > 7 else ''

        trans_time = next(
            (row[4] for row in lines if len(row) > 4 and row[4] is not None),
            None
        )

        # Build full receipt lines (all items in the document, names from local catalog)
        receipt_lines = _build_receipt_lines(lines)

        logger.info(
            f'ReservationERPMatcher [#{res.id}]: doc {doc_number} found — '
            f'doccode={doc_code}, branch={actual_branch}, '
            f'branch_matched={branch_matched}, lines={len(lines)}, '
            f'trans_time={trans_time}'
        )

        doc_value  = _to_float(header[4])
        user_code  = str(header[5] or '')
        store_code = str(header[6] or '')
        user_id    = user_info.get('user_id', '')   if user_info else ''
        user_name  = user_info.get('user_name', '') if user_info else ''

        matched_items, match_status = self._match_items(lines)

        branch_note = ''
        if not branch_matched and actual_branch and actual_branch != branch_code:
            branch_note = (
                f' ⚠️ ملاحظة: المستند مُسجَّل تحت الفرع {actual_branch} '
                f'في SOFTECH (الفرع المتوقع: {branch_code})'
            )

        auto_note = ' 🔎 (تم اكتشاف رقم المستند تلقائياً)' if discovered_doc else ''

        if match_status == 'matched':
            n = len(matched_items) or 1
            detail = (
                f'✅ تم التأكيد: المستند {doc_number} موجود في SOFTECH '
                f'والأصناف مطابقة ({n}/{n})'
            ) + auto_note + branch_note
        elif match_status == 'partial':
            full  = sum(1 for m in matched_items if m['match_level'] == 'full')
            total = len(matched_items) or 1
            detail = (
                f'⚠️ تأكيد جزئي: المستند {doc_number} موجود في SOFTECH '
                f'({full} من {total} صنف متطابق كلياً)'
            ) + auto_note + branch_note
        else:
            detail = (
                f'🔍 المستند {doc_number} موجود في SOFTECH '
                f'لكن لا توجد أصناف مطابقة في تفاصيل المستند'
            ) + auto_note + branch_note

        return {
            'status':         match_status,
            'doc_code':       doc_code,
            'doc_date':       doc_date,
            'doc_value':      doc_value,
            'user_code':      user_code,
            'user_id':        user_id,
            'user_name':      user_name,
            'trans_time':     trans_time,
            'store_code':     store_code,
            'matched_items':  matched_items,
            'receipt_lines':  receipt_lines,
            'erp_customer':   customer_info,
            'phcode':         phcode,
            'detail':         detail,
            'branch_matched': branch_matched,
            'actual_branch':  actual_branch,
            'discovered_doc': discovered_doc,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _branch_code(self) -> str:
        b = self.reservation.branch
        if b and b.softech_branch_id:
            return str(b.softech_branch_id).strip()
        return ''

    def _fetch_sybase(self, doc_number: str, branch_code: str):
        """
        4-pass fallback strategy — finds the document even when stktransm
        branchcode or doccode doesn't perfectly match.

        Pass 1: stktransm  docnumber + branchcode + doccode=115
        Pass 2: stktransm  docnumber + doccode=115  (any branch)
        Pass 3: stktransm  docnumber only            (any branch, any doccode)
        Pass 4: stktrans   docnumber + branchcode    (header derived from line table)

        Returns (header_row | None, lines, branch_matched: bool, user_info | None).
        ABSOLUTE RULE: SELECT ONLY. Never INSERT/UPDATE/DELETE on Sybase.
        """
        from config.sybase import get_sybase_connection
        from apps.sync.sybase_queries import QUERY_STKTRANS_LINES, QUERY_STKTRANS_LINES_ANY
        res_id = self.reservation.id

        try:
            doc_num_param = int(doc_number)
        except (ValueError, TypeError):
            doc_num_param = doc_number

        conn = None
        try:
            conn = get_sybase_connection()
            cur  = conn.cursor()

            # ── Pass 1: stktransm — exact branch + doccode=115 ───────────────
            cur.execute(
                """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                          sm.docdate, sm.docvalue, sm.usercode, sm.storecode, sm.phcode
                   FROM SOFTECHDB9.dbo.stktransm sm
                   WHERE sm.docnumber = ?
                     AND sm.branchcode = ?
                     AND sm.doccode = ?""",
                [doc_num_param, branch_code, ERP_DOCCODE]
            )
            header = cur.fetchone()
            if header is not None:
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: Pass 1 hit — '
                    f'doc={doc_number} branch={branch_code}'
                )
                cur.execute(QUERY_STKTRANS_LINES, [doc_num_param, branch_code])
                lines         = cur.fetchall() or []
                user_info     = _lookup_user(cur, header[5], res_id)
                customer_info = _fetch_customer_info(cur, str(header[7] or '').strip(), res_id)
                return header, lines, True, user_info, customer_info

            # ── Pass 2: stktransm — any branch, doccode=115 ──────────────────
            cur.execute(
                """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                          sm.docdate, sm.docvalue, sm.usercode, sm.storecode, sm.phcode
                   FROM SOFTECHDB9.dbo.stktransm sm
                   WHERE sm.docnumber = ?
                     AND sm.doccode = ?""",
                [doc_num_param, ERP_DOCCODE]
            )
            header = cur.fetchone()
            if header is not None:
                found_branch = str(header[2] or '').strip()
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: Pass 2 hit — '
                    f'doc={doc_number} branch={found_branch}'
                )
                cur.execute(QUERY_STKTRANS_LINES_ANY, [doc_num_param])
                lines         = cur.fetchall() or []
                user_info     = _lookup_user(cur, header[5], res_id)
                customer_info = _fetch_customer_info(cur, str(header[7] or '').strip(), res_id)
                return header, lines, False, user_info, customer_info

            # ── Pass 3: stktransm — docnumber only, zero filters ─────────────
            cur.execute(
                """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                          sm.docdate, sm.docvalue, sm.usercode, sm.storecode, sm.phcode
                   FROM SOFTECHDB9.dbo.stktransm sm
                   WHERE sm.docnumber = ?""",
                [doc_num_param]
            )
            header = cur.fetchone()
            if header is not None:
                found_branch = str(header[2] or '').strip()
                found_code   = str(header[1] or '').strip()
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: Pass 3 hit — '
                    f'doc={doc_number} branch={found_branch} doccode={found_code}'
                )
                cur.execute(QUERY_STKTRANS_LINES_ANY, [doc_num_param])
                lines         = cur.fetchall() or []
                user_info     = _lookup_user(cur, header[5], res_id)
                customer_info = _fetch_customer_info(cur, str(header[7] or '').strip(), res_id)
                return header, lines, False, user_info, customer_info

            # ── Pass 4: stktrans direct — branchcode+docnumber (hits composite index)
            # No stktransm row → no phcode/customer info available
            cur.execute("SET ROWCOUNT 1")
            cur.execute(
                """SELECT st.docnumber, NULL AS doccode, st.branchcode,
                          NULL AS docdate, NULL AS docvalue,
                          NULL AS usercode, st.storecode
                   FROM SOFTECHDB9.dbo.stktrans st
                   WHERE st.docnumber = ? AND st.branchcode = ?""",
                [doc_num_param, branch_code]
            )
            header = cur.fetchone()
            cur.execute("SET ROWCOUNT 0")
            if header is not None:
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: Pass 4 hit — '
                    f'stktrans direct doc={doc_number}'
                )
                cur.execute(QUERY_STKTRANS_LINES, [doc_num_param, branch_code])
                lines = cur.fetchall() or []
                return header, lines, False, None, None

            logger.warning(
                f'ReservationERPMatcher [#{res_id}]: all 4 passes failed for doc={doc_number}'
            )
            return None, [], False, None, None

        except Exception as exc:
            logger.warning(
                f'ReservationERPMatcher [#{res_id}]: Sybase error for doc={doc_number}: {exc}',
                exc_info=True,
            )
            return None, [], False, None, None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _auto_search(self, branch_code: str):
        """
        Auto-search mode — called when erp_reference is empty.

        Step 1 — stktransm (small header table):
          Query by doccode=115 + branch + date window (created_at → +7 days).
          A sale can only occur AFTER the reservation is created — no lookback.
          Fast because stktransm is tiny (one row per document header).
          Falls back to any branch if the reservation branch returns nothing.

        Step 2 — score each candidate by item overlap:
          Queries stktrans using QUERY_STKTRANS_LINES (branchcode + docnumber)
          which hits the composite index → fast, no full table scan.

        Returns 5-tuple: (header, lines, branch_matched, user_info, discovered_doc).
        Returns (None, [], False, None, None) if no match found.
        ABSOLUTE RULE: SELECT ONLY. Never INSERT/UPDATE/DELETE on Sybase.
        """
        import datetime as _dt
        from config.sybase import get_sybase_connection
        from apps.sync.sybase_queries import QUERY_STKTRANS_LINES

        res    = self.reservation
        res_id = res.id

        # Need a catalogued item to match by softech_id
        if not res.item_id or not res.item.softech_id:
            logger.info(
                f'ReservationERPMatcher [#{res_id}]: auto-search skipped — '
                f'no item softech_id (manual item)'
            )
            return None, [], False, None, None, None

        item_code    = str(res.item.softech_id).strip()
        target_codes = {item_code}

        # Window: reservation created_at → +7 days forward only.
        # A sales transaction can only exist AFTER the reservation was created —
        # no lookback into prior days is needed or correct.
        created_dt = res.created_at
        created_date = created_dt.date() if hasattr(created_dt, 'date') else created_dt
        date_from    = str(created_date)
        date_to      = str(created_date + _dt.timedelta(days=7))

        logger.info(
            f'ReservationERPMatcher [#{res_id}]: auto-search — '
            f'branch={branch_code}, window={date_from}…{date_to} '
            f'(created_at → +7d), item={item_code}'
        )

        conn = None
        try:
            conn = get_sybase_connection()
            cur  = conn.cursor()

            # ── Step 1: stktransm candidates ─────────────────────────────────
            def _candidates(bc):
                if bc:
                    cur.execute(
                        """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                                  sm.docdate, sm.docvalue, sm.usercode, sm.storecode, sm.phcode
                           FROM SOFTECHDB9.dbo.stktransm sm
                           WHERE sm.doccode = ?
                             AND sm.branchcode = ?
                             AND sm.docdate >= ?
                             AND sm.docdate <= ?""",
                        [ERP_DOCCODE, bc, date_from, date_to]
                    )
                else:
                    cur.execute(
                        """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                                  sm.docdate, sm.docvalue, sm.usercode, sm.storecode, sm.phcode
                           FROM SOFTECHDB9.dbo.stktransm sm
                           WHERE sm.doccode = ?
                             AND sm.docdate >= ?
                             AND sm.docdate <= ?""",
                        [ERP_DOCCODE, date_from, date_to]
                    )
                return cur.fetchall() or []

            candidates = _candidates(branch_code) or _candidates(None)

            if not candidates:
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: auto-search — no stktransm '
                    f'candidates for doccode={ERP_DOCCODE}, window={date_from}…{date_to}'
                )
                return None, [], False, None, None, None

            logger.info(
                f'ReservationERPMatcher [#{res_id}]: auto-search — '
                f'{len(candidates)} candidate(s); scoring by item overlap '
                f'(QUERY_STKTRANS_LINES per candidate — composite index)'
            )

            # ── Step 2: score each candidate by item overlap ──────────────────
            best_header      = None
            best_lines       = []
            best_score       = -1
            best_date_dist   = 9999
            best_branch_matched = False

            for hdr in candidates:
                raw_doc = hdr[0]
                try:
                    doc_num_param = int(float(str(raw_doc)))
                except (ValueError, TypeError):
                    doc_num_param = raw_doc

                hdr_branch = str(hdr[2] or '').strip()

                raw_d = hdr[3]
                try:
                    d = raw_d.date() if hasattr(raw_d, 'date') else raw_d
                    date_dist = abs((d - created_date).days)
                except Exception:
                    date_dist = 9999

                cur2 = conn.cursor()
                try:
                    cur2.execute(QUERY_STKTRANS_LINES, [doc_num_param, hdr_branch])
                    lines = cur2.fetchall() or []
                except Exception as se:
                    logger.warning(
                        f'ReservationERPMatcher [#{res_id}]: scoring error '
                        f'for doc={doc_num_param} branch={hdr_branch}: {se}'
                    )
                    lines = []
                finally:
                    try:
                        cur2.close()
                    except Exception:
                        pass

                found_codes = {str(r[0] or '').strip() for r in lines if r[0]}
                score = len(target_codes & found_codes)

                logger.debug(
                    f'ReservationERPMatcher [#{res_id}]: candidate '
                    f'doc={doc_num_param} branch={hdr_branch} '
                    f'score={score}/1 dist={date_dist}d'
                )

                if score > best_score or (score == best_score and date_dist < best_date_dist):
                    best_score       = score
                    best_date_dist   = date_dist
                    best_header      = hdr
                    best_lines       = lines
                    best_branch_matched = hdr_branch == branch_code

            if best_score <= 0 or best_header is None:
                logger.info(
                    f'ReservationERPMatcher [#{res_id}]: auto-search — '
                    f'no item overlap in any candidate; manual entry required'
                )
                return None, [], False, None, None, None

            raw_best = best_header[0]
            try:
                discovered_doc = str(int(float(str(raw_best))))
            except (ValueError, TypeError):
                discovered_doc = str(raw_best)

            best_user_info     = _lookup_user(cur, best_header[5], res_id)
            best_customer_info = _fetch_customer_info(
                cur, str(best_header[7] or '').strip() if len(best_header) > 7 else '', res_id
            )

            logger.info(
                f'ReservationERPMatcher [#{res_id}]: auto-search SUCCESS — '
                f'doc={discovered_doc}, score={best_score}/1, '
                f'lines={len(best_lines)}, branch_matched={best_branch_matched}, '
                f'customer={best_customer_info}'
            )
            return best_header, best_lines, best_branch_matched, best_user_info, discovered_doc, best_customer_info

        except Exception as exc:
            logger.warning(
                f'ReservationERPMatcher [#{res_id}]: auto-search error: {exc}',
                exc_info=True,
            )
            return None, [], False, None, None, None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _match_items(self, stk_rows) -> tuple[list, str]:
        """
        Cross-reference stktrans lines against the reservation item.
        A reservation has a single item, so we get a single-element result list.

        Row layout from QUERY_STKTRANS_LINES / QUERY_STKTRANS_LINES_ANY:
          [0]=itemcode, [1]=transqty, [2]=transprice_total, [3]=storecode, [4]=trans_time
        """
        res = self.reservation

        if not res.item_id or not res.item.softech_id:
            # Manual item — cannot verify by itemcode; header existence is enough
            return [], 'matched'

        # Build itemcode → max qty map (take max across rows to avoid double-counting)
        stk_map: dict[str, dict] = {}
        for row in stk_rows:
            itemcode = str(row[0] or '').strip()
            if not itemcode:
                continue
            qty = _to_float(row[1]) or 0.0
            if itemcode in stk_map:
                stk_map[itemcode]['erp_qty'] = max(stk_map[itemcode]['erp_qty'], qty)
            else:
                stk_map[itemcode] = {
                    'erp_qty': qty,
                    'price':   _to_float(row[2]) or 0.0,
                }

        itemcode = str(res.item.softech_id).strip()
        req_qty  = float(res.quantity_requested)
        stk      = stk_map.get(itemcode)

        if stk:
            erp_qty = stk['erp_qty']
            diff_pct = (
                abs(erp_qty - req_qty) / req_qty
                if req_qty > 0
                else (0.0 if erp_qty == 0 else 1.0)
            )
            level = 'full' if diff_pct <= _QTY_TOLERANCE else 'partial'
            return (
                [{
                    'itemcode':      itemcode,
                    'itemname':      res.item.name,
                    'requested_qty': req_qty,
                    'erp_qty':       erp_qty,
                    'match_level':   level,
                }],
                'matched' if level == 'full' else 'partial',
            )
        else:
            return (
                [{
                    'itemcode':      itemcode,
                    'itemname':      res.item.name,
                    'requested_qty': req_qty,
                    'erp_qty':       None,
                    'match_level':   'not_found',
                }],
                # Header found in stktransm but item not in stktrans lines —
                # treat as partial (replication lag or sold under different store)
                'partial',
            )


# ── module-level helpers ───────────────────────────────────────────────────────

def _lookup_user(cur, usercode, res_id) -> dict | None:
    """
    Resolve SOFTECH usercode → userid (login) + display name.

    Uses SET ROWCOUNT 1 for ASE 12.5 compatibility (SELECT TOP 1 with
    parameters is not reliably supported). Column names are discovered
    dynamically via cursor.description to survive schema differences.

    SELECT ONLY — never modifies Sybase.
    """
    if not usercode:
        return None
    try:
        cur.execute("SET ROWCOUNT 1")
        cur.execute(
            "SELECT * FROM SOFTECHDB9.dbo.users WHERE usercode = ?",
            [str(usercode).strip()]
        )
        row = cur.fetchone()
        if row is None or not cur.description:
            return None

        cols = {d[0].lower(): i for i, d in enumerate(cur.description)}
        logger.debug(f'ReservationERPMatcher [#{res_id}]: users cols: {list(cols.keys())}')

        user_id = ''
        for cn in ('userid', 'user_id', 'loginid', 'loginname', 'login', 'logname'):
            if cn in cols:
                user_id = str(row[cols[cn]] or '').strip()
                break

        user_name = ''
        for cn in ('userfullname', 'fullnamear', 'fullname_ar', 'arabicname',
                   'arname', 'namear', 'fullname', 'full_name',
                   'username_ar', 'usernamear', 'displayname'):
            if cn in cols:
                val = str(row[cols[cn]] or '').strip()
                if val:
                    user_name = val
                    break

        logger.info(
            f'ReservationERPMatcher [#{res_id}]: user resolved — '
            f'usercode={usercode} → userid={user_id!r}, name={user_name!r}'
        )
        return {'user_id': user_id, 'user_name': user_name}

    except Exception as exc:
        logger.warning(
            f'ReservationERPMatcher [#{res_id}]: user lookup failed '
            f'for usercode={usercode}: {exc}'
        )
    finally:
        try:
            cur.execute("SET ROWCOUNT 0")
        except Exception:
            pass
    return None


def _fetch_customer_info(cur, phcode: str, res_id) -> dict | None:
    """
    Resolve SOFTECH PIC code (phcode) → customer name + phone.

    Queries SOFTECHDB9.dbo.localcustomers which holds per-branch customer records.
    Column names discovered dynamically via cursor.description.

    SELECT ONLY — never modifies Sybase.
    """
    if not phcode:
        return None
    try:
        cur.execute("SET ROWCOUNT 1")
        cur.execute(
            "SELECT * FROM SOFTECHDB9.dbo.localcustomers WHERE phcode = ?",
            [phcode]
        )
        row = cur.fetchone()
        if row is None or not cur.description:
            return {'phcode': phcode, 'name': '', 'phone': ''}

        cols = {d[0].lower(): i for i, d in enumerate(cur.description)}
        logger.debug(
            f'ReservationERPMatcher [#{res_id}]: localcustomers cols: {list(cols.keys())}'
        )

        name = ''
        for cn in ('branchcustname', 'custname', 'name', 'customername', 'customer_name', 'namear', 'arabicname'):
            if cn in cols:
                v = str(row[cols[cn]] or '').strip()
                if v:
                    name = v
                    break

        phone = ''
        for cn in ('branchcustphone', 'custphone', 'phone', 'mobile', 'tel', 'telephone'):
            if cn in cols:
                v = str(row[cols[cn]] or '').strip()
                if v:
                    phone = v
                    break

        logger.info(
            f'ReservationERPMatcher [#{res_id}]: customer resolved — '
            f'phcode={phcode!r} → name={name!r}, phone={phone!r}'
        )
        return {'phcode': phcode, 'name': name, 'phone': phone}

    except Exception as exc:
        logger.warning(
            f'ReservationERPMatcher [#{res_id}]: customer lookup failed '
            f'for phcode={phcode}: {exc}'
        )
    finally:
        try:
            cur.execute("SET ROWCOUNT 0")
        except Exception:
            pass
    return {'phcode': phcode, 'name': '', 'phone': ''}


def _build_receipt_lines(stk_rows: list) -> list:
    """
    Build the full list of items from a SOFTECH document (all stktrans lines).
    Enriches itemcode with local catalog name; merges duplicate itemcode rows by summing qty.

    Row layout from QUERY_STKTRANS_LINES / QUERY_STKTRANS_LINES_ANY:
      [0]=itemcode, [1]=transqty, [2]=transprice_total, [3]=storecode, [4]=trans_time

    Returns list of dicts: {itemcode, itemname, qty, price, storecode}
    """
    from apps.catalog.models import Item

    if not stk_rows:
        return []

    # Collect unique item codes
    unique_codes = list({str(r[0] or '').strip() for r in stk_rows if r[0]})

    # Bulk-fetch names from local catalog
    name_map: dict[str, str] = {}
    if unique_codes:
        qs = Item.objects.filter(softech_id__in=unique_codes).values('softech_id', 'name')
        name_map = {row['softech_id']: row['name'] for row in qs}

    # Build lines, merging duplicate itemcodes by summing qty
    lines: list[dict] = []
    seen: dict[str, int] = {}   # itemcode → index in lines

    for row in stk_rows:
        itemcode = str(row[0] or '').strip()
        if not itemcode:
            continue
        qty       = round(_to_float(row[1]) or 0.0, 4)
        price     = round(_to_float(row[2]) or 0.0, 4)
        storecode = str(row[3] or '').strip()

        if itemcode in seen:
            lines[seen[itemcode]]['qty'] = round(lines[seen[itemcode]]['qty'] + qty, 4)
        else:
            seen[itemcode] = len(lines)
            lines.append({
                'itemcode':  itemcode,
                'itemname':  name_map.get(itemcode, ''),
                'qty':       qty,
                'price':     price,
                'storecode': storecode,
            })

    return lines


def _not_found(detail: str) -> dict:
    return {
        'status':         'not_found',
        'doc_code':       '',
        'doc_date':       None,
        'doc_value':      None,
        'user_code':      '',
        'store_code':     '',
        'user_id':        '',
        'user_name':      '',
        'trans_time':     None,
        'matched_items':  [],
        'receipt_lines':  [],
        'erp_customer':   None,
        'phcode':         '',
        'detail':         detail,
        'discovered_doc': None,
    }


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
