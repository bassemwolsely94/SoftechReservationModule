"""
apps/transfers/erp_matcher.py

ERP Match Verification — checks whether a transfer request's erp_reference
actually exists in SOFTECHDB9.dbo.stktransm (document header) and cross-
references the line items from stktrans against the items in the request.

Called by:
  - `check_erp_match` view action (admin manual trigger)
  - `_poll_erp_matches()` in apps/sync/tasks.py (runs every 30 min)

ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT/UPDATE/DELETE.
"""

import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.transfers')

# Quantity tolerance: erp_qty within ±TOLERANCE of requested_qty → full match
_QTY_TOLERANCE = 0.20  # 20%


class ERPMatcher:
    """
    Verify a TransferRequest's ERP reference against SOFTECH stktransm + stktrans.

    Usage:
        result = ERPMatcher(transfer_request).run()

    Returns a dict:
        {
            status:        'matched' | 'partial' | 'not_found',
            doc_code:      str,                         # e.g. '110'
            doc_date:      date | None,
            doc_value:     float | None,                # total value in SOFTECH
            user_code:     str,                         # who entered it in SOFTECH
            store_code:    str,
            matched_items: [                            # one entry per transfer item
                {itemcode, itemname, requested_qty, erp_qty, match_level}
            ],
            detail:        str,                         # Arabic human-readable summary
        }

    This method does NOT write to the database — the caller persists the result.
    """

    def __init__(self, transfer):
        self.transfer = transfer

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        doc_number  = (self.transfer.erp_reference or '').strip()
        branch_code = self._supplying_branch_code()

        if not branch_code:
            return _not_found('رمز الفرع المصدر غير مُعرَّف في SOFTECH — تحقق من إعدادات الفرع')

        discovered_doc = None  # set when auto-search finds the document

        if doc_number:
            header, lines, branch_matched, user_info = self._fetch_sybase(doc_number, branch_code)
        else:
            # Auto-search mode: no erp_reference entered — scan stktransm by items + branch + date
            header, lines, branch_matched, user_info, discovered_doc = \
                self._auto_search(branch_code)
            if header is not None:
                doc_number = discovered_doc  # use it for display / result

        if header is None:
            if doc_number:
                return _not_found(
                    f'المستند رقم {doc_number} غير موجود في SOFTECH '
                    f'(تم البحث للفرع {branch_code} وبدون تصفية فرع — '
                    f'نوع المستند المطلوب: 125 صرف تبادل بين الفروع)'
                )
            else:
                return _not_found(
                    f'لم يُعثر تلقائياً على مستند صرف تبادل (كود 125) في SOFTECH '
                    f'يطابق أصناف هذا الطلب للفرع {branch_code}. '
                    f'يرجى إدخال رقم المستند يدوياً.'
                )

        doc_code        = str(header[1] or '')
        actual_branch   = str(header[2] or '').strip()
        # Sybase returns docdate as a datetime; model field is DateField — extract .date()
        _raw_date       = header[3]
        doc_date        = _raw_date.date() if hasattr(_raw_date, 'date') else _raw_date

        # Extract trans_time from the earliest non-null line row [4]
        # trans_time is a datetime (carries actual clock time; docdate is date-only midnight)
        trans_time = next(
            (row[4] for row in lines if len(row) > 4 and row[4] is not None),
            None
        )

        logger.info(
            f'ERPMatcher: TR {self.transfer.request_number} — '
            f'doc {doc_number} found: doccode={doc_code}, branch={actual_branch}, '
            f'branch_matched={branch_matched}, lines={len(lines)}, '
            f'trans_time={trans_time}, user_info={user_info}'
        )
        doc_value       = _to_float(header[4])
        user_code       = str(header[5] or '')
        store_code      = str(header[6] or '')
        user_id         = user_info.get('user_id', '')   if user_info else ''
        user_name       = user_info.get('user_name', '') if user_info else ''

        matched_items, status = self._match_items(lines)

        # Note if the document was found under a different branch than expected
        branch_note = ''
        if not branch_matched and actual_branch and actual_branch != branch_code:
            branch_note = (
                f' ⚠️ ملاحظة: المستند مُسجَّل تحت الفرع {actual_branch} '
                f'في SOFTECH (الفرع المتوقع: {branch_code}) — '
                f'قد يكون تم إدخاله مركزياً.'
            )
            logger.info(
                f'ERPMatcher: TR {self.transfer.request_number} — '
                f'doc {doc_number} found under branch {actual_branch}, '
                f'expected branch {branch_code}'
            )

        auto_note = ' 🔎 (تم اكتشاف رقم المستند تلقائياً)' if discovered_doc else ''

        if status == 'matched':
            n = len(matched_items)
            detail = (
                f'✅ تم التأكيد: المستند {doc_number} موجود في SOFTECH '
                f'وجميع الأصناف مطابقة ({n}/{n})'
            ) + auto_note + branch_note
        elif status == 'partial':
            full  = sum(1 for m in matched_items if m['match_level'] == 'full')
            total = len(matched_items)
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
            'status':         status,
            'doc_code':       doc_code,
            'doc_date':       doc_date,
            'doc_value':      doc_value,
            'user_code':      user_code,
            'user_id':        user_id,
            'user_name':      user_name,
            'trans_time':     trans_time,
            'store_code':     store_code,
            'matched_items':  matched_items,
            'detail':         detail,
            'branch_matched': branch_matched,
            'actual_branch':  actual_branch,
            'discovered_doc': discovered_doc,  # set only when auto-search found the docnumber
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _auto_search(self, branch_code: str):
        """
        Auto-search mode — called when erp_reference is empty.

        Two-step approach (stktrans-free scoring for speed):

        Step 1 — stktransm (header table, one row per document):
          Query by doccode=125 + branch + ±3-day date window.
          Returns a handful of candidate rows very quickly.
          Tries supplying branch first, then any branch as fallback.

        Step 2 — Pick winner from stktransm data alone:
          Sort candidates: branch-exact matches first, then by date proximity
          to the transfer's submission time.  No stktrans scan needed here —
          querying stktrans by docnumber without a covering index causes a
          full table scan that hangs for minutes.

        Step 3 — Fetch lines for the winner ONCE (bounded by SET ROWCOUNT):
          Uses SET ROWCOUNT 2000 so the scan is capped even without an index.
          Lines are used for trans_time + item matching in run().

        Returns a 5-tuple: (header_row, lines, branch_matched, user_info, discovered_doc).
        Never raises — returns (None, [], False, None, None) on any error.
        ABSOLUTE RULE: SELECT ONLY. Never INSERT/UPDATE/DELETE on Sybase.
        """
        import datetime as _dt
        from config.sybase import get_sybase_connection
        from apps.sync.sybase_queries import QUERY_STKTRANS_LINES

        tr     = self.transfer
        tr_num = tr.request_number

        # ── collect item codes ────────────────────────────────────────────────
        transfer_items = list(tr.items.select_related('item').all())
        item_codes = [
            str(ti.item.softech_id).strip()
            for ti in transfer_items
            if ti.item.softech_id
        ]
        if not item_codes:
            logger.info(f'ERPMatcher [{tr_num}]: auto-search skipped — no item softech_ids')
            return None, [], False, None, None

        # ── date window: ±3 days around transfer submission (7-day window) ─────
        ref_dt    = tr.sent_to_erp_at or tr.created_at
        ref_date  = ref_dt.date() if hasattr(ref_dt, 'date') else ref_dt
        date_from = str(ref_date - _dt.timedelta(days=3))
        date_to   = str(ref_date + _dt.timedelta(days=3))

        logger.info(
            f'ERPMatcher [{tr_num}]: auto-search — branch={branch_code}, '
            f'window={date_from}…{date_to}, items={item_codes}'
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
                                  sm.docdate, sm.docvalue, sm.usercode, sm.storecode
                           FROM SOFTECHDB9.dbo.stktransm sm
                           WHERE sm.doccode = '125'
                             AND sm.branchcode = ?
                             AND sm.docdate >= ?
                             AND sm.docdate <= ?""",
                        [bc, date_from, date_to]
                    )
                else:
                    cur.execute(
                        """SELECT sm.docnumber, sm.doccode, sm.branchcode,
                                  sm.docdate, sm.docvalue, sm.usercode, sm.storecode
                           FROM SOFTECHDB9.dbo.stktransm sm
                           WHERE sm.doccode = '125'
                             AND sm.docdate >= ?
                             AND sm.docdate <= ?""",
                        [date_from, date_to]
                    )
                return cur.fetchall() or []

            candidates = _candidates(branch_code) or _candidates(None)

            if not candidates:
                logger.info(
                    f'ERPMatcher [{tr_num}]: auto-search — no stktransm candidates '
                    f'for doccode=125, window={date_from}…{date_to}'
                )
                return None, [], False, None, None

            logger.info(
                f'ERPMatcher [{tr_num}]: auto-search — {len(candidates)} candidate(s); '
                f'scoring by item overlap (QUERY_STKTRANS_LINES per candidate — uses composite index)'
            )

            # ── Step 2: score each candidate by item overlap ──────────────────
            # Use QUERY_STKTRANS_LINES (docnumber + branchcode) for each candidate.
            # stktrans has a composite index on (branchcode, docnumber) so each
            # per-candidate query is fast — no full table scan.
            # Each candidate's branchcode comes from its own stktransm row.
            target_codes     = set(item_codes)
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
                    date_dist = abs((d - ref_date).days)
                except Exception:
                    date_dist = 9999

                cur2 = conn.cursor()
                try:
                    cur2.execute(QUERY_STKTRANS_LINES, [doc_num_param, hdr_branch])
                    lines = cur2.fetchall() or []
                except Exception as se:
                    logger.warning(
                        f'ERPMatcher [{tr_num}]: scoring query failed for '
                        f'doc={doc_num_param} branch={hdr_branch}: {se}'
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
                    f'ERPMatcher [{tr_num}]: candidate doc={doc_num_param} '
                    f'branch={hdr_branch} score={score}/{len(target_codes)} dist={date_dist}d'
                )

                # Better score → prefer; tie → prefer closer date
                if score > best_score or (score == best_score and date_dist < best_date_dist):
                    best_score       = score
                    best_date_dist   = date_dist
                    best_header      = hdr
                    best_lines       = lines
                    best_branch_matched = hdr_branch == branch_code

            # Score=0 means no candidate contains any item from this transfer —
            # refuse to auto-discover to avoid persisting a wrong docnumber.
            if best_score <= 0 or best_header is None:
                logger.info(
                    f'ERPMatcher [{tr_num}]: auto-search — no item overlap with any '
                    f'candidate; user must enter docnumber manually'
                )
                return None, [], False, None, None

            raw_best = best_header[0]
            try:
                discovered_doc = str(int(float(str(raw_best))))
            except (ValueError, TypeError):
                discovered_doc = str(raw_best)

            # ── User lookup ───────────────────────────────────────────────────
            best_user_info = self._lookup_user(cur, best_header[5], None, tr_num)

            logger.info(
                f'ERPMatcher [{tr_num}]: auto-search SUCCESS — '
                f'doc={discovered_doc}, score={best_score}/{len(target_codes)}, '
                f'lines={len(best_lines)}, branch_matched={best_branch_matched}'
            )
            return best_header, best_lines, best_branch_matched, best_user_info, discovered_doc

        except Exception as exc:
            logger.warning(
                f'ERPMatcher [{tr_num}]: auto-search error: {exc}',
                exc_info=True,
            )
            return None, [], False, None, None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _supplying_branch_code(self) -> str:
        sb = self.transfer.supplying_branch
        if sb and sb.softech_branch_id:
            return str(sb.softech_branch_id).strip()
        return ''

    def _fetch_sybase(self, doc_number: str, branch_code: str):
        """
        4-pass fallback strategy — finds the document even when stktransm
        branchcode or doccode doesn't match expectations.

        Pass 1: stktransm  docnumber + branchcode + doccode='125'
        Pass 2: stktransm  docnumber + doccode='125'  (any branch)
        Pass 3: stktransm  docnumber only             (any branch, any doccode)
        Pass 4: stktrans   docnumber only             (header derived from line table)

        After finding the document, looks up the SOFTECH users table to resolve
        usercode → userid (login name) and username (display name).

        Returns (header_row | None, lines_rows, branch_matched: bool, user_info: dict | None).
        user_info keys: 'user_id' (login), 'user_name' (full name).
        Never raises — returns (None, [], False, None) on any error.
        ABSOLUTE RULE: SELECT ONLY. Never INSERT/UPDATE/DELETE on Sybase.
        """
        from config.sybase import get_sybase_connection
        from apps.sync.sybase_queries import (
            QUERY_VALIDATE_STKTRANS,
            QUERY_VALIDATE_STKTRANS_ANY,
            QUERY_VALIDATE_STKTRANS_RAW,
            QUERY_STKTRANS_DIRECT_HEADER,
            QUERY_STKTRANS_LINES,
            QUERY_STKTRANS_LINES_ANY,
        )
        tr_num = self.transfer.request_number

        # stktransm.docnumber is a DECIMAL column in Sybase ASE.
        # Passing a Python str causes "Implicit conversion from CHAR to DECIMAL".
        # Convert to int so jConnect sends it as a numeric parameter.
        try:
            doc_num_param = int(doc_number)
        except (ValueError, TypeError):
            doc_num_param = doc_number  # non-numeric docnumber: pass as-is

        conn = None
        try:
            conn = get_sybase_connection()
            cur  = conn.cursor()

            # ── Pass 1: stktransm — exact branch + doccode=125 ───────────────
            cur.execute(QUERY_VALIDATE_STKTRANS, [doc_num_param, branch_code])
            header = cur.fetchone()
            if header is not None:
                logger.info(f'ERPMatcher [{tr_num}]: Pass 1 hit — doc={doc_number} branch={branch_code}')
                cur.execute(QUERY_STKTRANS_LINES, [doc_num_param, branch_code])
                lines = cur.fetchall() or []
                user_info = self._lookup_user(cur, header[5], None, tr_num)
                return header, lines, True, user_info

            logger.info(f'ERPMatcher [{tr_num}]: Pass 1 miss — trying Pass 2 (any branch, doccode=125)')

            # ── Pass 2: stktransm — any branch, doccode=125 ──────────────────
            cur.execute(QUERY_VALIDATE_STKTRANS_ANY, [doc_num_param])
            header = cur.fetchone()
            if header is not None:
                found_branch = str(header[2] or '').strip()
                logger.info(f'ERPMatcher [{tr_num}]: Pass 2 hit — doc={doc_number} branch={found_branch}')
                cur.execute(QUERY_STKTRANS_LINES_ANY, [doc_num_param])
                lines = cur.fetchall() or []
                user_info = self._lookup_user(cur, header[5], None, tr_num)
                return header, lines, False, user_info

            logger.info(f'ERPMatcher [{tr_num}]: Pass 2 miss — trying Pass 3 (stktransm, no filters)')

            # ── Pass 3: stktransm — docnumber only, zero filters ─────────────
            cur.execute(QUERY_VALIDATE_STKTRANS_RAW, [doc_num_param])
            header = cur.fetchone()
            if header is not None:
                found_branch = str(header[2] or '').strip()
                found_code   = str(header[1] or '').strip()
                logger.info(
                    f'ERPMatcher [{tr_num}]: Pass 3 hit — doc={doc_number} '
                    f'branch={found_branch} doccode={found_code}'
                )
                cur.execute(QUERY_STKTRANS_LINES_ANY, [doc_num_param])
                lines = cur.fetchall() or []
                user_info = self._lookup_user(cur, header[5], None, tr_num)
                return header, lines, False, user_info

            logger.info(
                f'ERPMatcher [{tr_num}]: Pass 3 miss — stktransm has nothing for doc={doc_number}. '
                f'Trying Pass 4 (stktrans direct)'
            )

            # ── Pass 4: stktrans direct — header derived from line table ──────
            # stktransm may lag behind stktrans replication, or the header may
            # simply not exist for this document type.
            cur.execute(QUERY_STKTRANS_DIRECT_HEADER, [doc_num_param])
            header = cur.fetchone()
            if header is not None:
                found_branch = str(header[2] or '').strip()
                logger.info(
                    f'ERPMatcher [{tr_num}]: Pass 4 hit — doc={doc_number} found in stktrans '
                    f'(no stktransm header). branch={found_branch}'
                )
                cur.execute(QUERY_STKTRANS_LINES_ANY, [doc_num_param])
                lines = cur.fetchall() or []
                # Pass 4 has no usercode in header (NULL) — skip user lookup
                return header, lines, False, None

            logger.warning(
                f'ERPMatcher [{tr_num}]: All 4 passes exhausted — doc={doc_number} '
                f'not found in stktransm OR stktrans.'
            )
            return None, [], False, None

        except Exception as exc:
            logger.warning(
                f'ERPMatcher [{tr_num}]: Sybase error for doc={doc_number}: {exc}',
                exc_info=True,
            )
            return None, [], False, None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _lookup_user(cur, usercode, _unused_query, tr_num) -> dict | None:
        """
        Look up SOFTECH users table to resolve usercode → userid + display name.

        Uses SELECT TOP 1 * so column names are discovered dynamically at runtime —
        this avoids InvalidColumn errors when SOFTECH versions have different schemas.

        Returns {'user_id': str, 'user_name': str} or None on any error.
        SELECT ONLY — never modifies Sybase.
        """
        if not usercode:
            return None
        try:
            # Sybase ASE 12.5 doesn't reliably support SELECT TOP 1 * with parameters.
            # Use SET ROWCOUNT 1 instead (session-level, reset in finally).
            cur.execute("SET ROWCOUNT 1")
            cur.execute(
                "SELECT * FROM SOFTECHDB9.dbo.users WHERE usercode = ?",
                [str(usercode).strip()]
            )
            row = cur.fetchone()
            if row is None or not cur.description:
                return None

            # Build lowercase column name → index map
            cols = {d[0].lower(): i for i, d in enumerate(cur.description)}
            logger.debug(f'ERPMatcher [{tr_num}]: users table columns: {list(cols.keys())}')

            # Resolve login ID — try common SOFTECH column name variants
            user_id = ''
            for cname in ('userid', 'user_id', 'loginid', 'loginname', 'login', 'logname'):
                if cname in cols:
                    user_id = str(row[cols[cname]] or '').strip()
                    break

            # Resolve display name — prefer Arabic name columns
            user_name = ''
            for cname in ('userfullname', 'fullnamear', 'fullname_ar', 'arabicname',
                          'arname', 'namear', 'fullname', 'full_name',
                          'username_ar', 'usernamear', 'displayname'):
                if cname in cols:
                    val = str(row[cols[cname]] or '').strip()
                    if val:
                        user_name = val
                        break

            logger.info(
                f'ERPMatcher [{tr_num}]: user resolved — '
                f'usercode={usercode} → userid={user_id!r}, name={user_name!r}'
            )
            return {'user_id': user_id, 'user_name': user_name}

        except Exception as exc:
            # Degrade gracefully — caller still has usercode from stktransm
            logger.warning(
                f'ERPMatcher [{tr_num}]: user lookup failed for usercode={usercode}: {exc}'
            )
        finally:
            try:
                cur.execute("SET ROWCOUNT 0")
            except Exception:
                pass
        return None

    def _match_items(self, stk_rows) -> tuple[list, str]:
        """
        Cross-reference stktrans lines against TransferRequestItem list.

        Returns:
            matched_items: list of dicts
            status:        'matched' | 'partial' | 'not_found'
        """
        # Build lookup: itemcode → {erp_qty, itemname}
        # Sum qty across all rows for the same itemcode — this handles the case where
        # QUERY_STKTRANS_LINES_ANY returns rows for both supplying AND requesting branch
        # (SOFTECH records صرف at source and استلام at destination under the same docnumber).
        # Row layout from QUERY_STKTRANS_LINES / QUERY_STKTRANS_LINES_ANY:
        # [0] itemcode, [1] transqty, [2] transprice_total, [3] storecode
        # (stktrans has no itemname column — name comes from local catalog via ti.item.name)
        stk_map: dict[str, dict] = {}
        for row in stk_rows:
            itemcode = str(row[0] or '').strip()
            if not itemcode:
                continue
            qty = _to_float(row[1]) or 0.0
            if itemcode in stk_map:
                # Accumulate — take the max rather than sum, because صرف + استلام
                # would double-count the same physical movement.
                stk_map[itemcode]['erp_qty'] = max(stk_map[itemcode]['erp_qty'], qty)
            else:
                stk_map[itemcode] = {
                    'erp_qty': qty,
                    'price':   _to_float(row[2]) or 0.0,
                }

        transfer_items = list(
            self.transfer.items.select_related('item').all()
        )

        if not transfer_items:
            # No items to verify — header match is enough
            return [], 'matched'

        result      = []
        full_count  = 0
        found_count = 0  # full + partial

        for ti in transfer_items:
            itemcode  = str(ti.item.softech_id or '').strip()
            req_qty   = float(ti.quantity)
            stk       = stk_map.get(itemcode)

            if stk:
                erp_qty = stk['erp_qty']
                found_count += 1

                if req_qty > 0:
                    diff_pct = abs(erp_qty - req_qty) / req_qty
                else:
                    diff_pct = 0.0 if erp_qty == 0 else 1.0

                if diff_pct <= _QTY_TOLERANCE:
                    level = 'full'
                    full_count += 1
                else:
                    level = 'partial'

                result.append({
                    'itemcode':      itemcode,
                    'itemname':      ti.item.name,
                    'requested_qty': req_qty,
                    'erp_qty':       erp_qty,
                    'match_level':   level,
                })
            else:
                result.append({
                    'itemcode':      itemcode,
                    'itemname':      ti.item.name,
                    'requested_qty': req_qty,
                    'erp_qty':       None,
                    'match_level':   'not_found',
                })

        total = len(transfer_items)

        if full_count == total:
            status = 'matched'
        elif found_count > 0:
            status = 'partial'
        else:
            # Header found in stktransm but no items in stktrans —
            # treat as partial (the document exists, items may be in a different
            # store code or the data hasn't replicated yet)
            status = 'partial'

        return result, status


# ── helpers ────────────────────────────────────────────────────────────────────

def _not_found(detail: str) -> dict:
    return {
        'status':        'not_found',
        'doc_code':      '',
        'doc_date':      None,
        'doc_value':     None,
        'user_code':     '',
        'store_code':    '',
        'matched_items': [],
        'detail':        detail,
    }


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def apply_match_result(transfer, result: dict) -> None:
    """
    Write ERPMatcher result dict into a TransferRequest instance in memory.
    Does NOT call .save() — caller handles that.

    Exported here so both the view action and the background task share
    identical field-mapping logic.
    """
    from django.utils import timezone

    status = result['status']
    transfer.erp_match_status    = status
    transfer.erp_match_detail    = result.get('detail', '')
    transfer.erp_last_checked    = timezone.now()
    transfer.erp_check_attempts  = (transfer.erp_check_attempts or 0) + 1

    if status in ('matched', 'partial'):
        transfer.erp_matched_at       = timezone.now()
        transfer.erp_match_doc_code   = result.get('doc_code', '')
        transfer.erp_match_doc_date   = result.get('doc_date')
        transfer.erp_match_user_code  = result.get('user_code', '')
        transfer.erp_match_user_id    = result.get('user_id', '')
        transfer.erp_match_user_name  = result.get('user_name', '')
        transfer.erp_match_trans_time = result.get('trans_time')
        transfer.erp_match_store_code = result.get('store_code', '')
        transfer.erp_matched_items    = result.get('matched_items', [])
        raw_val = result.get('doc_value')
        if raw_val is not None:
            try:
                transfer.erp_match_doc_value = Decimal(str(raw_val))
            except InvalidOperation:
                transfer.erp_match_doc_value = None
        else:
            transfer.erp_match_doc_value = None
    # if 'not_found': leave existing match fields intact (preserves any previous partial data)


# Fields to pass to .save(update_fields=[...]) after apply_match_result
ERP_MATCH_UPDATE_FIELDS = [
    'erp_match_status', 'erp_match_detail',
    'erp_last_checked', 'erp_check_attempts',
    'erp_matched_at', 'erp_match_doc_code', 'erp_match_doc_date',
    'erp_match_doc_value', 'erp_match_user_code', 'erp_match_user_id',
    'erp_match_user_name', 'erp_match_trans_time',
    'erp_match_store_code', 'erp_matched_items', 'updated_at',
]
