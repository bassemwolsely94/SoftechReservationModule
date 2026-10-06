"""
apps/insurance/reprice_service.py

SOFTECH insurance-receipt re-price — preview (read-only) + gated writeback.

Safety model (highest-risk write in the system):
  * `build_preview()` is READ-ONLY — computes every field change on HQ + branch.
  * `apply_reprice()` writes, and is disabled unless ALL hold:
      - settings.INSURANCE_SOFTECH_WRITE_ENABLED is True (default False),
      - the caller passes confirm=True,
      - the claim is a DRAFT (submitted/paid are blocked),
      - the branch node is reachable (can't keep HQ/branch consistent otherwise).
  * Every field write is recorded (SoftechRepriceRun + SoftechRepriceEdit) for revert.
  * `personnewbal` is NOT touched here — it is fixed by the separate, idempotent
    `rebalance_contract_clients()` forward-rebuild after the price edits.

See docs/architecture/21_SOFTECH_INSURANCE_REPRICE_WRITEBACK.md.
"""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .reprice import recompute_line, refoot_header, _d, r2
from .models import (
    InsuranceClaim, SoftechRepriceRun, SoftechRepriceEdit,
)
from apps.branches.models import Branch

_DOCCODE = '115'
_LINE_COLS = ['itemcode', 'transqty', 'itemsaleprice', 'itemsaleprice_tax', 'itemsalestax',
              'transprice', 'transprice_total', 'additionaldiscp', 'custdiscp', 'newcostprice',
              'bonusqty',      # per-strip price SOFTECH prints on the receipt for pack-split
                               # items = itemsaleprice/packing; must scale with the new price
              'dblitemflag']   # SOFTECH's duplicate-line discriminator (1,2,… per item)
_HDR_COLS = ['docvalue', 'docvalue1', 'docvalue2', 'docvalue3', 'cust_branch_code', 'trans_time']


class RepriceError(Exception):
    pass


def write_enabled() -> bool:
    return bool(getattr(settings, 'INSURANCE_SOFTECH_WRITE_ENABLED', False))


def _hq_conn(charset=None):
    """HQ connection; charset='cp1256' for the write paths (importer._get_connection
    takes no args, so go straight to the charset-aware factory)."""
    from config.sybase import get_sybase_connection
    return get_sybase_connection(charset=charset)


def _branch_host(branch):
    m = {b.softech_branch_id: b for b in Branch.objects.all()}
    b = m.get(branch)
    return (b.effective_db_host if b else None), (b.effective_db_port if b else 5000)


def _open_branch(branch, charset=None):
    from config.sybase import get_branch_connection
    host, port = _branch_host(branch)
    return get_branch_connection(host, port, charset=charset)


def _read_receipt(cur, docno, branch, doccode):
    cur.execute("SELECT " + ",".join(_LINE_COLS) +
                " FROM SOFTECHDB9.dbo.stktrans WHERE docnumber=CONVERT(numeric(6),?) "
                "AND branchcode=? AND doccode=?", [docno, branch, doccode])
    lines = [dict(zip(_LINE_COLS, r)) for r in cur.fetchall()]
    cur.execute("SELECT " + ",".join(_HDR_COLS) +
                " FROM SOFTECHDB9.dbo.stktransm WHERE docnumber=CONVERT(numeric(6),?) "
                "AND branchcode=? AND doccode=?", [docno, branch, doccode])
    hr = cur.fetchone()
    return lines, (dict(zip(_HDR_COLS, hr)) if hr else None)


def _compute(lines, header, new_prices):
    """
    Return (new_lines, new_header_fields, per-line diff list).

    The header is re-footed INCREMENTALLY — old header value + the edited line's
    delta — NOT as an absolute Σ of the lines.  This is essential: a receipt's
    stored docvalue can differ from Σ transprice_total (partial-pack / bonus lines
    carry an adjusted transprice_total that doesn't equal transprice×qty), so an
    absolute re-foot would silently rewrite docvalue to a wrong base.  Incremental
    deltas preserve whatever base the receipt has and touch only the edited line.

    Refuses to edit a "quirk" line whose stored transprice_total ≠ transprice×qty
    (partial-pack / bonus) — its true header contribution isn't recoverable, so a
    re-price could corrupt the total.
    """
    # Duplicate item lines on one receipt are targeted individually by SOFTECH's own
    # dblitemflag (1,2,… per item — e.g. a sale line + a reservation line).  We only
    # refuse if that STILL doesn't make a line unique — i.e. two lines share the same
    # (itemcode, dblitemflag) — which we can't safely target.
    from collections import Counter
    _keycounts = Counter((str(l['itemcode']).strip(), str(_d(l.get('dblitemflag'))))
                         for l in lines)
    for l in lines:
        code = str(l['itemcode']).strip()
        if code in new_prices and _keycounts[(code, str(_d(l.get('dblitemflag'))))] > 1:
            raise RepriceError(
                f'الصنف {code} مكرَّر ببنود غير قابلة للتمييز فى هذا الإيصال — '
                'لا يمكن إعادة تسعيره تلقائياً (عدّله يدوياً).')

    new_lines, diffs = [], []
    d_gross = d_net = d_vat = Decimal('0')
    for ln in lines:
        code = str(ln['itemcode']).strip()
        if code in new_prices:
            qty = _d(ln['transqty'])
            # guard: only edit lines whose total is the clean transprice×qty
            clean_total = r2(_d(ln['transprice']) * qty)
            if clean_total != r2(_d(ln['transprice_total'])):
                raise RepriceError(
                    f'الصنف {code} بند عبوة جزئية/بونص (إجمالى غير قياسى) — '
                    'لا يمكن إعادة تسعيره بأمان.')
            rc = recompute_line(new_price=new_prices[code], transqty=qty,
                                custdiscp=ln['custdiscp'], vat_rate=ln['additionaldiscp'])
            # bonusqty = the per-strip price the RECEIPT prints for pack-split items,
            # kept by SOFTECH at itemsaleprice/packing.  Re-pricing itemsaleprice must
            # scale it by the same ratio or the printed strip price goes stale (the
            # receipt under/over-prints while the header total is already correct).
            old_price = _d(ln['itemsaleprice'])
            old_bonus = _d(ln.get('bonusqty'))
            if old_bonus > 0 and old_price > 0:
                rc['bonusqty'] = r2(old_bonus * _d(new_prices[code]) / old_price)
            merged = dict(ln); merged.update(rc)
            new_lines.append(merged)
            d_gross += (_d(rc['itemsaleprice']) - _d(ln['itemsaleprice'])) * qty
            d_net += _d(rc['transprice_total']) - _d(ln['transprice_total'])
            d_vat += (_d(rc['itemsalestax']) - _d(ln['itemsalestax'])) * qty
            diffs.append({
                'itemcode': code, 'item_name': '',
                'changes': {f: {'old': str(_d(ln[f])), 'new': str(rc[f])}
                            for f in ('itemsaleprice', 'itemsaleprice_tax', 'itemsalestax',
                                      'transprice', 'transprice_total', 'bonusqty')
                            if f in rc and r2(_d(ln.get(f))) != r2(rc[f])},
                'transqty': str(qty),
                'vat_rate': str(_d(ln['additionaldiscp'])),
            })
        else:
            new_lines.append(ln)
    h = {'docvalue1': r2(_d(header['docvalue1']) + d_gross),   # gross
         'docvalue':  r2(_d(header['docvalue']) + d_net),      # net (tender)
         'docvalue3': r2(_d(header['docvalue3']) + d_vat)}     # VAT total
    return new_lines, h, diffs


def build_preview(docno, branch, new_prices, doccode=_DOCCODE):
    """READ-ONLY: full old→new diff on HQ (+ branch consistency + cascade footprint)."""
    from .importer import _get_connection
    new_prices = {str(k).strip(): _d(v) for k, v in new_prices.items()}
    hq = _get_connection(); hcur = hq.cursor()
    try:
        lines, header = _read_receipt(hcur, docno, branch, doccode)
        if not lines or not header:
            raise RepriceError(f'الإيصال #{docno} فرع {branch} غير موجود فى HQ')
        new_lines, h, diffs = _compute(lines, header, new_prices)
        old_net = r2(_d(header['docvalue']))
        net_delta = r2(h['docvalue']) - old_net
        ccode = str(header['cust_branch_code']).strip() if header['cust_branch_code'] else None
        # NOTE: the personnewbal cascade footprint (a slow unindexed cust_branch_code
        # scan) is intentionally NOT computed here — it is shown in rebalance_preview
        # only when the user actually opens the optional rebalance, so the price preview
        # stays fast.

        # motalba snapshot rows (HQ) — their المطلوب سداده is synced on apply
        try:
            hcur.execute("SELECT COUNT(*) FROM SOFTECHDB9.dbo.motalba "
                         "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                         [docno, branch, doccode])
            motalba_rows = hcur.fetchone()[0]
        except Exception:
            motalba_rows = 0

        # branch consistency (best-effort)
        consistency = {'reachable': False, 'consistent': None}
        try:
            bconn = _open_branch(branch); bcur = bconn.cursor()
            _, bheader = _read_receipt(bcur, docno, branch, doccode)
            consistency = {'reachable': True,
                           'consistent': bool(bheader and r2(_d(bheader['docvalue'])) == old_net)}
            bcur.close(); bconn.close()
        except Exception as e:
            consistency = {'reachable': False, 'consistent': None, 'error': str(e)[:80]}

        return {
            'docnumber': docno, 'branch': branch, 'doccode': doccode,
            'cust_branch_code': ccode,
            'lines': diffs,
            'header': {f: {'old': str(_d(header[f])), 'new': str(h[f])}
                       for f in ('docvalue1', 'docvalue', 'docvalue3')},
            'docvalue2_cost': str(_d(header['docvalue2'])),
            'tender_new': str(h['docvalue']),
            'net_delta': str(net_delta),
            'branch_consistency': consistency,
            'motalba_rows': motalba_rows,
            'write_enabled': write_enabled(),
        }
    finally:
        hcur.close(); hq.close()


# ── gated write (P3) ─────────────────────────────────────────────────────────

def _guard(claim, branch, confirm):
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة (INSURANCE_SOFTECH_WRITE_ENABLED=False).')
    if not confirm:
        raise RepriceError('التأكيد مطلوب (confirm=True).')
    if claim is not None and claim.status != InsuranceClaim.STATUS_DRAFT:
        raise RepriceError('المطالبة ليست مسودة — تعديل سوفتك محظور على المطالبات المُرسَلة/المدفوعة.')


def _write_receipt(cur, docno, branch, doccode, new_lines, header_new, tender_new, record):
    """Apply line + header + tender updates on ONE node's open (autocommit-off) cursor.
    `record(table, row_key, field, before, after)` logs each change for revert."""
    for ln in new_lines:
        code = str(ln['itemcode']).strip()
        flag = int(_d(ln.get('dblitemflag')))
        for f in ('itemsaleprice', 'itemsaleprice_tax', 'itemsalestax', 'transprice', 'transprice_total', 'bonusqty'):
            if f in ln and isinstance(ln[f], Decimal):   # only recomputed fields carry Decimals
                cur.execute(f"UPDATE SOFTECHDB9.dbo.stktrans SET {f}=? "
                            "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=? "
                            "AND itemcode=? AND dblitemflag=?",
                            [float(ln[f]), docno, branch, doccode, code, flag])
    for f in ('docvalue1', 'docvalue', 'docvalue3'):
        cur.execute(f"UPDATE SOFTECHDB9.dbo.stktransm SET {f}=? "
                    "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                    [float(header_new[f]), docno, branch, doccode])
    cur.execute("UPDATE SOFTECHDB9.dbo.branchesales SET paymentvalue=? "
                "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                [float(tender_new), docno, branch, doccode])


def apply_reprice(claim, docno, branch, new_prices, user=None, confirm=False, doccode=_DOCCODE):
    """
    GATED writeback of a receipt re-price to HQ + branch (transactional, audited).
    Does NOT rebalance personnewbal — call rebalance_contract_clients() afterwards.
    """
    from .importer import _get_connection
    _guard(claim, branch, confirm)
    new_prices = {str(k).strip(): _d(v) for k, v in new_prices.items()}

    # preview must be consistent + branch reachable before we touch anything
    pv = build_preview(docno, branch, new_prices, doccode)
    if not pv['branch_consistency'].get('reachable'):
        raise RepriceError('عُقدة الفرع غير متاحة — لا يمكن الحفاظ على تطابق HQ/الفرع؛ التطبيق محظور.')

    hq = _hq_conn(charset='cp1256')
    bconn = _open_branch(branch, charset='cp1256')
    hcur, bcur = hq.cursor(), bconn.cursor()
    lines, header = _read_receipt(hcur, docno, branch, doccode)
    new_lines, h, _diffs = _compute(lines, header, new_prices)
    tender_new = h['docvalue']

    # motalba snapshot (HQ-ONLY): each motalba that included this receipt stored its
    # payable (docvaluerequired = المطلوب سداده) + grand total (docvalue_grandtotal)
    # when generated.  Sync them to the new net/gross so a reprinted motalba matches
    # the re-priced receipt.  No rows = receipt not yet in any motalba (skip).
    hcur.execute("SELECT docvaluerequired, docvalue_grandtotal FROM SOFTECHDB9.dbo.motalba "
                 "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                 [docno, branch, doccode])
    _mrow = hcur.fetchone()
    mot_old_req   = _d(_mrow[0]) if _mrow else None
    mot_old_grand = _d(_mrow[1]) if _mrow else None

    run = SoftechRepriceRun.objects.create(
        claim=claim, docnumber=str(docno), branchcode=branch, doccode=doccode,
        cust_branch_code=pv['cust_branch_code'] or '', new_prices={k: str(v) for k, v in new_prices.items()},
        net_delta=_d(pv['net_delta']), nodes=['HQ', branch],
        applied_by=getattr(user, 'staff_profile', None) if user else None,
        status=SoftechRepriceRun.STATUS_PREVIEW)
    edits = []

    # Read the branch node's own before-values (it may differ from HQ if a prior
    # edit was one-sided) so a revert restores each node to ITS own prior state.
    bl_lines, bl_header = _read_receipt(bcur, docno, branch, doccode)
    b_line = {str(l['itemcode']).strip(): l for l in bl_lines}

    def _before(node, ln_map, hdr, field, table, code=None):
        src = ln_map.get(code) if table == 'stktrans' else hdr
        return str(_d(src[field])) if src and field in src else ''

    try:
        # Record before→after per PHYSICAL line, keyed by (itemcode, dblitemflag) so a
        # duplicated item (e.g. sale line + reservation line) is targeted individually.
        _flag = lambda l: int(_d(l.get('dblitemflag')))
        hq_line = {(str(l['itemcode']).strip(), _flag(l)): l for l in lines}
        br_line = {(str(l['itemcode']).strip(), _flag(l)): l for l in bl_lines}
        for nl in new_lines:
            code = str(nl['itemcode']).strip()
            if code not in new_prices:          # untouched line
                continue
            flag = _flag(nl)
            rk = {'docnumber': str(docno), 'branchcode': branch, 'doccode': doccode,
                  'itemcode': code, 'dblitemflag': flag}
            hqs, brs = hq_line.get((code, flag)), br_line.get((code, flag))
            for f in ('itemsaleprice', 'itemsaleprice_tax', 'itemsalestax', 'transprice', 'transprice_total', 'bonusqty'):
                # bonusqty is recorded only when it was actually scaled (Decimal on nl)
                if f == 'bonusqty' and not isinstance(nl.get('bonusqty'), Decimal):
                    continue
                edits.append(SoftechRepriceEdit(run=run, node='HQ', table='stktrans', row_key=rk,
                    field=f, before=str(_d(hqs[f])) if hqs else '', after=str(nl[f])))
                edits.append(SoftechRepriceEdit(run=run, node=branch, table='stktrans', row_key=rk,
                    field=f, before=str(_d(brs[f])) if brs else '', after=str(nl[f])))
        rk_h = {'docnumber': str(docno), 'branchcode': branch, 'doccode': doccode}
        for f in ('docvalue1', 'docvalue', 'docvalue3'):
            edits.append(SoftechRepriceEdit(run=run, node='HQ', table='stktransm', row_key=rk_h,
                field=f, before=str(_d(header[f])), after=str(h[f])))
            edits.append(SoftechRepriceEdit(run=run, node=branch, table='stktransm', row_key=rk_h,
                field=f, before=str(_d(bl_header[f])) if bl_header else '', after=str(h[f])))
        edits.append(SoftechRepriceEdit(run=run, node='HQ', table='branchesales', row_key=rk_h,
            field='paymentvalue', before=str(_d(header['docvalue'])), after=str(tender_new)))
        edits.append(SoftechRepriceEdit(run=run, node=branch, table='branchesales', row_key=rk_h,
            field='paymentvalue', before=str(_d(bl_header['docvalue'])) if bl_header else '', after=str(tender_new)))
        if mot_old_req is not None:
            edits.append(SoftechRepriceEdit(run=run, node='HQ', table='motalba', row_key=rk_h,
                field='docvaluerequired', before=str(mot_old_req), after=str(h['docvalue'])))
            edits.append(SoftechRepriceEdit(run=run, node='HQ', table='motalba', row_key=rk_h,
                field='docvalue_grandtotal', before=str(mot_old_grand), after=str(h['docvalue1'])))

        hq.begin(); bconn.begin()
        _write_receipt(hcur, docno, branch, doccode, new_lines, h, tender_new, None)
        _write_receipt(bcur, docno, branch, doccode, new_lines, h, tender_new, None)
        if mot_old_req is not None:   # motalba lives on HQ only
            hcur.execute("UPDATE SOFTECHDB9.dbo.motalba SET docvaluerequired=?, docvalue_grandtotal=? "
                         "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                         [float(h['docvalue']), float(h['docvalue1']), docno, branch, doccode])
        bconn.commit(); hq.commit()

        SoftechRepriceEdit.objects.bulk_create(edits, batch_size=500)
        run.status = SoftechRepriceRun.STATUS_APPLIED
        run.save(update_fields=['status'])
    except Exception as e:
        try: hq.rollback()
        except Exception: pass
        try: bconn.rollback()
        except Exception: pass
        run.status = SoftechRepriceRun.STATUS_FAILED
        run.error = str(e)[:2000]
        run.save(update_fields=['status', 'error'])
        raise
    finally:
        hcur.close(); bcur.close(); hq.close(); bconn.close()

    return {'run_id': run.pk, 'net_delta': str(run.net_delta),
            'cust_branch_code': run.cust_branch_code}


# ── rebalance (personnewbal add-Δ shift) ─────────────────────────────────────
#
# personnewbal is the contract client's cumulative running balance, keyed on
# cust_branch_code, HQ-ONLY (branch nodes store 0 — verified).  Recurrence: sales
# (115) add docvalue, returns (30) subtract docvalue.  Its native order is the
# personnewbal VALUE ITSELF (a clean running sum), NOT trans_time — SOFTECH's HQ
# consolidation scrambles trans_time by minutes (proven live).  So the rows "after"
# an edited receipt = rows whose balance is >= the edited receipt's balance; we ADD
# the sale's net Δ to those.  This is exact for the (dominant) sales chain; a return
# that dips below the edit's balance is the only residual imperfection (a few EGP).


def _edit_balance(cur, docno, branch, doccode):
    """The edited receipt's own personnewbal (B_edit) — the balance-order cut point."""
    cur.execute("SELECT personnewbal FROM SOFTECHDB9.dbo.stktransm "
                "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                [docno, branch, doccode])
    r = cur.fetchone()
    return _d(r[0]) if r else None


def verify_running_balance(cur, cust_branch_code, b_edit, span=Decimal('20000')):
    """
    Self-validating guard: is this client's personnewbal a genuine running Σdocvalue?

    Model-FREE discriminator (personnewbal is moved by several doc types — sales,
    returns, payments — so we do NOT assume a sales-only recurrence): a genuine
    running-balance ledger has MANY rows whose personnewbal accumulates across a WIDE
    range around b_edit, and b_edit itself is a large accumulated figure.  A non-ledger
    account (e.g. one whose personnewbal holds tiny local values) has few rows and a
    tiny balance span, and fails.  Deliberately conservative — only clearly-accumulating
    accounts pass; the human still confirms in the preview.
    Returns (ok: bool, checked: int).
    """
    cur.execute("SELECT COUNT(*), MIN(personnewbal), MAX(personnewbal) "
                "FROM SOFTECHDB9.dbo.stktransm "
                "WHERE cust_branch_code=? AND personnewbal >= ? AND personnewbal <= ?",
                [cust_branch_code, float(b_edit - span), float(b_edit + span)], timeout=180)
    cnt, mn, mx = cur.fetchone()
    cnt = int(cnt or 0)
    balspan = _d(mx) - _d(mn)
    ok = (cnt >= 10 and balspan >= (span / 4) and b_edit >= span)
    return ok, cnt


def rebalance_preview(run):
    """READ-ONLY: rows the balance-order add-Δ shift would touch + ledger-guard result."""
    from .importer import _get_connection
    hq = _get_connection(); cur = hq.cursor()
    try:
        b_edit = _edit_balance(cur, run.docnumber, run.branchcode, run.doccode)
        if not run.cust_branch_code or _d(run.net_delta) == 0 or b_edit is None:
            return {'affected': 0, 'net_delta': str(run.net_delta), 'is_ledger': None}
        is_ledger, checked = verify_running_balance(cur, run.cust_branch_code, b_edit)
        cur.execute("SELECT COUNT(*) FROM SOFTECHDB9.dbo.stktransm "
                    "WHERE cust_branch_code=? AND personnewbal >= ?",
                    [run.cust_branch_code, float(b_edit)], timeout=180)
        n = cur.fetchone()[0]
        return {'affected': n, 'net_delta': str(run.net_delta),
                'is_ledger': is_ledger, 'ledger_checked': checked,
                'edit_balance': str(b_edit)}
    finally:
        cur.close(); hq.close()


def rebalance_run(run, user=None, confirm=False):
    """
    Shift `personnewbal` by the run's net Δ on the edited receipt and every LATER row
    of the same contract client (all doc types), across HQ + each branch node.
    Records each change onto the run so revert undoes the rebalance too.  Idempotent
    only in the sense that it is applied once per run (guarded by run.rebalanced).
    """
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')
    if not confirm:
        raise RepriceError('التأكيد مطلوب.')
    if run.status != SoftechRepriceRun.STATUS_APPLIED:
        raise RepriceError('إعادة الضبط تتم فقط بعد تطبيق ناجح.')
    if run.rebalanced:
        raise RepriceError('سبق إعادة ضبط رصيد هذه العملية.')
    delta = _d(run.net_delta)
    if delta == 0 or not run.cust_branch_code:
        run.rebalanced = True; run.save(update_fields=['rebalanced'])
        return {'updated': 0, 'note': 'لا حاجة (Δ=0)'}

    # personnewbal (contract running balance) lives ONLY on HQ — branch nodes store
    # 0 for it (verified live). So the rebalance is a pure HQ operation: no branch
    # connections, no flaky-link dependency.  Rows "after" the edit are selected by
    # BALANCE order (personnewbal >= b_edit), the ledger's true order — not trans_time.
    hq = _hq_conn(charset='cp1256'); cur = hq.cursor()
    b_edit = _edit_balance(cur, run.docnumber, run.branchcode, run.doccode)
    if b_edit is None:
        cur.close(); hq.close()
        raise RepriceError('تعذّر تحديد رصيد الإيصال.')
    ok, checked = verify_running_balance(cur, run.cust_branch_code, b_edit)
    if not ok:
        cur.close(); hq.close()
        raise RepriceError(f'هذا الحساب لا يحمل رصيداً تراكمياً صالحاً (فحص {checked} عملية) — '
                           'أُلغيت إعادة الضبط لتجنّب إفساد رصيد غير دفتري.')
    cur.execute("SELECT branchcode,docnumber,doccode,personnewbal FROM SOFTECHDB9.dbo.stktransm "
                "WHERE cust_branch_code=? AND personnewbal >= ? ORDER BY personnewbal",
                [run.cust_branch_code, float(b_edit)], timeout=180)
    rows = [(str(r[0]), str(int(_d(r[1]))), str(r[2]).strip(), _d(r[3])) for r in cur.fetchall()]

    edits, updated = [], 0
    hq.begin()
    try:
        for br, dn, dc, oldbal in rows:
            newbal = oldbal + delta
            cur.execute("UPDATE SOFTECHDB9.dbo.stktransm SET personnewbal=? "
                        "WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?",
                        [float(newbal), dn, br, dc])
            edits.append(SoftechRepriceEdit(run=run, node='HQ', table='stktransm',
                         row_key={'docnumber': dn, 'branchcode': br, 'doccode': dc},
                         field='personnewbal', before=str(oldbal), after=str(newbal)))
            updated += 1
        hq.commit()
        SoftechRepriceEdit.objects.bulk_create(edits, batch_size=500)
        run.rebalanced = True; run.rebalance_count = updated
        run.save(update_fields=['rebalanced', 'rebalance_count'])
    except Exception:
        try: hq.rollback()
        except Exception: pass
        raise
    finally:
        cur.close(); hq.close()
    return {'updated': updated, 'net_delta': str(delta)}


# ── revert ───────────────────────────────────────────────────────────────────

def revert_run(run, user=None):
    """Restore every field this run changed, on each node, to its recorded `before`."""
    from .importer import _get_connection
    if run.status != SoftechRepriceRun.STATUS_APPLIED:
        raise RepriceError('لا يمكن التراجع إلا عن عملية مُطبَّقة.')
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')

    edits = list(run.edits.all())
    branch_codes = {e.node for e in edits if e.node != 'HQ'}   # rebalance can span branches
    hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()
    bconns = {}
    for br in branch_codes:
        bc = _open_branch(br, charset='cp1256'); bc.begin(); bconns[br] = bc
    try:
        hq.begin()
        for e in edits:
            if e.before == '':
                continue
            conn = hq if e.node == 'HQ' else bconns[e.node]
            cur = hcur if e.node == 'HQ' else conn.cursor()
            rk = e.row_key
            where = "docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=?"
            params = [float(e.before), rk['docnumber'], rk['branchcode'], rk['doccode']]
            if e.table == 'stktrans':
                where += " AND itemcode=?"; params.append(rk['itemcode'])
                if 'dblitemflag' in rk:      # target the exact duplicate line
                    where += " AND dblitemflag=?"; params.append(int(rk['dblitemflag']))
            cur.execute(f"UPDATE SOFTECHDB9.dbo.{e.table} SET {e.field}=? WHERE {where}", params)
            if e.node != 'HQ':
                cur.close()
        for bc in bconns.values():
            bc.commit()
        hq.commit()
        run.status = SoftechRepriceRun.STATUS_REVERTED
        run.reverted_at = timezone.now()
        run.save(update_fields=['status', 'reverted_at'])
    except Exception:
        try: hq.rollback()
        except Exception: pass
        for bc in bconns.values():
            try: bc.rollback()
            except Exception: pass
        raise
    finally:
        hcur.close(); hq.close()
        for bc in bconns.values():
            try: bc.close()
            except Exception: pass
    return {'run_id': run.pk, 'status': run.status}


# ── receipt-driven & item-driven helpers (UI automation) ─────────────────────

def list_receipt_lines(docno, branch, doccode=_DOCCODE):
    """READ-ONLY: the item lines on a receipt so the UI can offer them to pick from
    (itemcode, name, qty, current public price, current net)."""
    from .importer import _get_connection, _safe
    from .sybase_queries import QUERY_PRESCRIPTION_LINES_CLASSIFIED
    hq = _get_connection(); cur = hq.cursor()
    try:
        cur.execute(QUERY_PRESCRIPTION_LINES_CLASSIFIED, [str(docno), str(branch)])
        out = []
        for r in cur.fetchall():
            out.append({
                'itemcode':          _safe(r[0]),
                'item_name':         _safe(r[1]),
                'qty':               str(_d(r[2])),
                'itemsaleprice':     str(_d(r[10])),   # current public price
                'transprice_total':  str(_d(r[4])),    # current SOFTECH net
            })
        return out
    finally:
        cur.close(); hq.close()


def find_item_receipts(claim, itemcode):
    """The claim's receipts (prescriptions) that contain `itemcode` — the candidate
    set for a batch re-price of that item across many receipts.  Uses our stored
    frozen lines (fast, no SOFTECH round-trip)."""
    from .models import InsuranceClaimLine
    code = str(itemcode).strip()
    lines = (InsuranceClaimLine.objects
             .filter(prescription__claim=claim, softech_itemcode=code)
             .select_related('prescription'))
    seen, out = set(), []
    for ln in lines:
        rx = ln.prescription
        key = (rx.softech_docnumber, rx.softech_branchcode)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            'docno':      rx.softech_docnumber,
            'branch':     rx.softech_branchcode,
            'patient':    rx.patient_name,
            'docdate':    rx.softech_docdate.isoformat() if rx.softech_docdate else None,
            'item_name':  ln.item_name,
            'unit_price': str(_d(ln.unit_price)),
            'quantity':   str(_d(ln.quantity)),
        })
    out.sort(key=lambda r: (r['branch'] or '', str(r['docno'])))
    return {'itemcode': code, 'receipts': out}


def apply_batch(claim, itemcode, new_price, receipts, user=None, confirm=False, doccode=_DOCCODE):
    """Apply the same new price for `itemcode` across several receipts.  Each receipt
    is its own transactional, revertible run (via apply_reprice), so a failure on one
    (e.g. an unreachable branch, a quirk line) does not block the others."""
    if not write_enabled():
        raise RepriceError('الكتابة إلى سوفتك معطّلة.')
    if not confirm:
        raise RepriceError('التأكيد مطلوب.')
    code = str(itemcode).strip()
    results = []

    def _log_failure(docno, branch, err):
        """Persist a FAILED run so the failed modification is auditable + exportable.
        apply_reprice already logs failures that occur AFTER its run row is created
        (write phase); this covers the EARLIER failures (guard/preview/read/compute
        duplicate-line) that raise before any run row exists — otherwise they would
        vanish from the log entirely."""
        try:
            already = SoftechRepriceRun.objects.filter(
                claim=claim, docnumber=str(docno), branchcode=str(branch),
                status=SoftechRepriceRun.STATUS_FAILED,
            ).order_by('-id').first()
            # apply_reprice may have already recorded this failure — don't double-log
            # a fresh one from the same attempt.
            if already and (timezone.now() - already.applied_at).total_seconds() < 30:
                return already.pk
            r = SoftechRepriceRun.objects.create(
                claim=claim, docnumber=str(docno), branchcode=str(branch), doccode=doccode,
                new_prices={code: str(new_price)}, nodes=['HQ', str(branch)],
                applied_by=getattr(user, 'staff_profile', None) if user else None,
                status=SoftechRepriceRun.STATUS_FAILED, error=str(err)[:2000],
            )
            return r.pk
        except Exception:
            return None

    # A flaky branch VPN link drops the connection mid-write (JZ0C0 "Connection is
    # already closed" / SybConnectionDeadException).  That failure is SAFE — the
    # transaction rolls back, both nodes stay unchanged (verified) — so a single
    # fresh-connection retry is a legitimate way to ride out the flap.
    _TRANSIENT = ('JZ0C0', 'ConnectionDead', 'Connection is already closed',
                  'JZ006', 'IOException', 'socket', 'timed out', 'timeout')
    def _is_transient(msg):
        return any(t.lower() in str(msg).lower() for t in _TRANSIENT)

    for rc in receipts:
        docno, branch = str(rc['docno']), str(rc['branch'])
        try:
            try:
                res = apply_reprice(claim, docno, branch, {code: new_price},
                                    user=user, confirm=True, doccode=doccode)
            except Exception as first:
                if not _is_transient(first):
                    raise
                # one retry with fresh connections after the link flapped
                res = apply_reprice(claim, docno, branch, {code: new_price},
                                    user=user, confirm=True, doccode=doccode)
            results.append({'docno': docno, 'branch': branch, 'ok': True,
                            'run_id': res['run_id'], 'net_delta': res['net_delta']})
        except RepriceError as e:
            results.append({'docno': docno, 'branch': branch, 'ok': False,
                            'error': str(e), 'run_id': _log_failure(docno, branch, e)})
        except Exception as e:
            results.append({'docno': docno, 'branch': branch, 'ok': False,
                            'error': str(e)[:120], 'run_id': _log_failure(docno, branch, e)})
    return {'itemcode': code, 'applied': sum(1 for r in results if r['ok']),
            'failed': sum(1 for r in results if not r['ok']), 'results': results}
