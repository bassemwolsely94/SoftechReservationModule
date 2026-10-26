"""
apps/purchasing/isr_writer.py

FEATURE 2 — Stage A: generate a SOFTECH ISR (طلب توريد, table `stockisr`) from our
engine, for a REQUESTING branch. The ISR then flows through the native طلب-توريد
screen → «اعتماد الطلب» → «إذن الصرف» (fulfilled from HQ br100 main store).

Reverse-engineered via probe_isr (see docs / memory softech_isr_replenishment):
  • isrdocnumber = str(YY) + str(creating/requesting branchcode) + str(serial)
    (plain concat, no zero-pad; serial per-branch-per-year). 2615041 = 26|150|41.
  • one stockisr row per item: itemqty (order qty), itemqty_cfarma (signed raw need),
    nowqty (branch balance), prices/supplier from item master, itemsource=4 (Report),
    item_topo=0, itemqty_tobr=0, itemsalestax=0, ash_sff/table_dumped NULL.

Serial allocation is race-safe: a single unchained batch reads max(isrdocnumber)
for the branch/year prefix under HOLDLOCK, extracts+increments the serial IN SQL
(handles the 999→1000 width rollover), inserts all lines, verifies the row count,
then COMMIT (do_commit) or ROLLBACK. Mirrors apps/invoices/writer.py.

⚠️ GATED — settings.ISR_WRITER_ENABLED (default False). build_plan() is READ-ONLY
always; push_isr() returns the dry-run plan unless the gate is on AND dry_run=False.
probe_isr_write() runs the REAL batch then ALWAYS rolls back (zero residue) to
validate field mapping + serial alloc before any live commit.

Stage B (write the معتمد stockordersm/stockorders order so إذن الصرف can pull it)
is a separate step, gated the same way, added after Stage A's rollback probe
validates the field mapping on a real serial.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

# Store codes excluded from "current stock" (quarantine/expiry) — same as the engine.
_EXCLUDED_STORES = {'102', '103', '105'}
HQ_CODE = '100'      # the main warehouse (was referenced below but never defined → NameError)


LOCK_ISR_PUSH = 7_301_006   # pg advisory lock, × 1e6 + IsrPush pk: one push of a draft at a time (P-15)


class WriterDisabled(RuntimeError):
    """Raised if a real SOFTECH ISR write is attempted while the gate is off."""


def writer_enabled() -> bool:
    return bool(getattr(settings, 'ISR_WRITER_ENABLED', False))


def auto_approve_enabled() -> bool:
    return bool(getattr(settings, 'ISR_AUTO_APPROVE_ENABLED', False))


def _service_usercode() -> str:
    return str(getattr(settings, 'ERP_SERVICE_USERCODE', '') or '1').strip() or '1'


def _int_qty(v) -> int:
    """Order quantities are whole packs — round half-up to int."""
    return int(Decimal(str(v or 0)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ── serial helpers ──────────────────────────────────────────────────────────────
def isr_prefix(branchcode, on_date=None) -> str:
    """'{YY}{branchcode}' — e.g. 2026 + br150 → '26150'."""
    d = on_date or timezone.localdate()
    return f'{d:%y}{branchcode}'


# ── SQL literal discipline (identical to invoices/writer.py) ────────────────────
class _Raw:
    def __init__(self, sql):
        self.sql = sql


def _sql_literal(val):
    if isinstance(val, _Raw):
        return val.sql
    if val is None:
        return 'NULL'
    if isinstance(val, bool):
        return '1' if val else '0'
    if isinstance(val, int):
        return str(val)
    if isinstance(val, (float, Decimal)):
        return str(float(val))
    return "'" + str(val).replace("'", "''") + "'"


_NOW = _Raw('getdate()')
_TODAY_MIDNIGHT = _Raw("convert(datetime, convert(char(8), getdate(), 112))")


def _header_row(source_branch, dest_branch, new_isr, docvalue, usercode, israpp=0):
    """The stockisrm HEADER row (required for retrievability). branchcode = SOURCE
    (preparer/node), forbranchcode = DEST (receiver). israpp=0 = unapproved (native
    review queue); 1 = approved. docvalue = Σ(qty × cost)."""
    return {
        'branchcode': str(source_branch), 'forbranchcode': str(dest_branch),
        'isrdocnumber': int(new_isr),
        'docdate': _TODAY_MIDNIGHT, 'usercode': usercode, 'trans_time': _NOW,
        'docvalue': round(float(docvalue), 3), 'docstatuscode': 0,
        'statususercode': usercode, 'statustrans_time': _NOW,
        'israpp': int(israpp), 'isrusercode': usercode, 'isrtrans_time': _NOW,
    }


def _insert_sql(table, row: dict) -> str:
    cols = list(row.keys())
    vals = [_sql_literal(row[c]) for c in cols]
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"


_INSERT_CHUNK = 150   # stockisr INSERTs per batch — ASE procedure-cache safe (a
                      # single 2800-line batch overruns the cache)
_READ_CHUNK = 400     # itemcodes per IN (...) when reading a node's stkbal (build_items_plan)


def _next_isrdocnumber(mx, prefix: str) -> int:
    """Extract-and-increment the per-branch/year serial (handles the 999→1000 width
    rollover, so NOT mx+1). mx = current max isrdocnumber for the prefix, or None."""
    if mx is None:
        return int(f'{prefix}1')
    s = str(int(mx))
    tail = s[len(prefix):]
    serial = int(tail) if (s.startswith(prefix) and tail.isdigit()) else 0
    return int(f'{prefix}{serial + 1}')


# ── 1. BUILD PLAN — READ-ONLY (engine gaps → stockisr line list) ────────────────
def build_plan(branchcode, *, run=None, positive_only=True, item_filter=None, max_lines=None,
               coverage_months=None):
    """
    Build the stockisr line list for a requesting branch from the latest successful
    engine run's ItemDemandMetrics. NEVER writes to SOFTECH (reads engine metrics +
    item master from PG). Returns:
      { 'branchcode','prefix','run_id','coverage_months',
        'lines':[{itemcode,item_name,itemqty,itemqty_cfarma,nowqty,itemsaleprice,
        itemcostprice,suppcode,gap}], 'line_count' }
    positive_only=True → only items the branch needs (gap>0), i.e. a supply request.

    coverage_months: None → use the engine run's frozen `gap` (default, unchanged).
    A positive value RE-SCALES each line's order qty to that many months of cover
    via calc_gap(current_stock, safety_stock, monthly_avg, coverage_months) — the
    max-stock ceiling = monthly_avg × coverage_months — WITHOUT re-running the engine.
    """
    from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
    from apps.branches.models import Branch
    from apps.purchasing.engine import calc_gap

    branch = Branch.objects.filter(softech_branch_id=str(branchcode)).first()
    if branch is None:
        raise ValueError(f'الفرع {branchcode} غير موجود.')

    run = run or (DemandCalculationRun.objects.filter(status='success')
                  .order_by('-finished_at', '-id').first())
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب.')

    recompute = coverage_months is not None and float(coverage_months) > 0
    cov = float(coverage_months) if recompute else None

    qs = (ItemDemandMetrics.objects.filter(run=run, branch=branch)
          .select_related('item')
          .only('gap', 'current_stock', 'safety_stock', 'monthly_avg',
                'item__softech_id', 'item__name', 'item__supplier_code',
                'item__pack_price', 'item__cost_price', 'item__supplier_trans',
                'item__is_stockable'))
    if item_filter:
        qs = qs.filter(item__softech_id__in=[str(i) for i in item_filter])
    else:
        # Orderability guard: a supply request lists only real, purchasable stock —
        # the shared real-stock rule (stockable, price > 0, not a coupon/gift) plus
        # supplier_trans (itemtrans2) not 2=return-only / 3=إيقاف كامل.
        from apps.purchasing.rate_writer import _real_stock_filter
        qs = _real_stock_filter(qs).exclude(item__supplier_trans__in=['2', '3'])
    # With a coverage override we recompute gap per row, so the frozen-gap DB filter
    # would wrongly exclude items whose need only appears at the new coverage window.
    if positive_only and not recompute:
        qs = qs.filter(gap__gt=0)
    qs = qs.order_by('-gap')

    lines = []
    for m in qs.iterator():
        it = m.item
        code = str(it.softech_id or '').strip()
        if not code:
            continue
        if recompute:
            gap = calc_gap(float(m.current_stock or 0), float(m.safety_stock or 0),
                           float(m.monthly_avg or 0), cov)
        else:
            gap = float(m.gap or 0)
        order_qty = _int_qty(max(gap, 0)) if positive_only else _int_qty(gap)
        if positive_only and order_qty <= 0:
            continue
        lines.append({
            'itemcode': code, 'item_name': it.name or '',
            'itemqty': order_qty,                       # order qty
            'itemqty_cfarma': round(gap, 2),            # signed raw need
            'nowqty': round(float(m.current_stock or 0), 3),
            'itemsaleprice': float(it.pack_price or 0),
            'itemcostprice': float(it.cost_price or 0),
            'suppcode': str(it.supplier_code or '').strip(),
            'gap': round(gap, 2),
        })
        if max_lines and len(lines) >= max_lines:
            break

    return {'branchcode': str(branchcode), 'prefix': isr_prefix(branchcode),
            'run_id': run.id, 'coverage_months': cov,
            'lines': lines, 'line_count': len(lines)}


def _line_row(ln, new_isr, idx, usercode):
    """One stockisr row dict → inline-literal INSERT."""
    return {
        'isrdocnumber': int(new_isr), 'isrdblitemflag': idx,
        'itemcode': ln['itemcode'], 'itemqty': float(ln['itemqty']),
        'itemqty_cfarma': float(ln['itemqty_cfarma']), 'nowqty': float(ln['nowqty']),
        'itemqty_tobr': 0, 'item_topo': 0,
        'itemsaleprice': float(ln['itemsaleprice']), 'itemsalestax': 0,
        'itemcostprice': float(ln['itemcostprice']),
        'usercode': usercode, 'trans_time': _NOW,
        'suppcode': (ln['suppcode'] or None), 'posuppcode': (ln['suppcode'] or None),
        'itemsource': 4,
    }


def _write_isr(conn, source_branch, dest_branch, lines, usercode, *, do_commit, approved=False):
    """
    Write the ISR in ONE chained transaction, inserting in _INSERT_CHUNK batches
    (a single 2800-line batch overruns ASE's procedure cache). Serial allocated once
    under HOLDLOCK (range lock held for the tran → race-safe), verify the row count,
    then commit (do_commit and verified) or rollback. Returns a result dict.

    Chained mode (setAutoCommit False) groups the multi-statement writes into one
    tran; stockisr has no financial trigger so the sp_expirytrans CHAINED trap that
    the stktrans writers avoid does not apply here.
    """
    prefix = isr_prefix(source_branch)                # isrdocnumber middle = SOURCE branch
    n = len(lines)
    jconn = conn._conn
    jconn.setAutoCommit(False)                        # chained: share one tran
    try:
        cur = conn.cursor()
        # allocate serial under HOLDLOCK (lock held until commit/rollback)
        cur.execute("SELECT max(isrdocnumber) FROM stockisrm holdlock "
                    "WHERE convert(varchar(14), isrdocnumber) LIKE ?", [prefix + '%'])
        row = cur.fetchone()
        new_isr = _next_isrdocnumber(row[0] if row and row[0] is not None else None, prefix)

        # HEADER first (stockisrm) — required for the ISR to be retrievable
        docvalue = sum(float(ln['itemqty']) * float(ln['itemcostprice']) for ln in lines)
        cur.execute(_insert_sql('stockisrm',
                                _header_row(source_branch, dest_branch, new_isr, docvalue,
                                            usercode, israpp=1 if approved else 0)))

        for i in range(0, n, _INSERT_CHUNK):
            chunk = lines[i:i + _INSERT_CHUNK]
            stmts = [_insert_sql('stockisr', _line_row(ln, new_isr, i + j + 1, usercode))
                     for j, ln in enumerate(chunk)]
            cur.execute('\n'.join(stmts))

        cur.execute("SELECT count(*) FROM stockisr WHERE isrdocnumber = ?", [int(new_isr)])
        cnt = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM stockisrm WHERE isrdocnumber = ?", [int(new_isr)])
        hdr = int(cur.fetchone()[0])
        verified = (cnt == n and hdr == 1)
        committed = False
        if do_commit and verified:
            jconn.commit()
            committed = True
        else:
            jconn.rollback()
        cur.close()
        return {'isrdocnumber': int(new_isr), 'lines_found': cnt, 'lines_expected': n,
                'verified': verified, 'committed': committed}
    except Exception:
        try:
            jconn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            jconn.setAutoCommit(True)
        except Exception:
            pass


# ── 2. PUSH — guarded; dry-run plan unless gate on + dry_run=False ──────────────
def push_isr(branchcode, *, run=None, dry_run=True, positive_only=True,
             item_filter=None, max_lines=None):
    """Build the plan; when writer_enabled() AND dry_run=False, write the stockisr
    ISR in one race-safe batch (serial alloc + inserts + verify + commit)."""
    plan = build_plan(branchcode, run=run, positive_only=positive_only,
                      item_filter=item_filter, max_lines=max_lines)
    if not plan['lines']:
        plan.update(mode='empty', wrote_to_softech=False)
        return plan

    if not dry_run:
        # The direct write had no IsrPush record, no duplicate guard and no audit — every run
        # wrote a NEW ISR (Batch 2, P-15). ISRs reach SOFTECH only as recorded drafts:
        # create_proposal → approve → push_isr_record (/supply, generate_isr --auto-approve).
        raise WriterDisabled('push_isr writes no ISR any more — push a recorded draft (/supply or '
                             'generate_isr --auto-approve).')
    plan.update(mode='dry_run', wrote_to_softech=False)
    logger.info('[isr_writer] DRY-RUN branch=%s (enabled=%s) — %d lines',
                branchcode, writer_enabled(), plan['line_count'])
    return plan


# ── push an APPROVED IsrPush record's snapshot to SOFTECH (israpp=1) ────────────
def push_isr_record(isr_push, *, executed_by=None, force_reason=''):
    """Write an APPROVED IsrPush's stored line snapshot to SOFTECH (stockisrm header
    israpp=1 + stockisr lines), record the allocated isrdocnumber, update the record.
    Gate + status checked before any SOFTECH connection. One push of a draft at a time:
    an advisory lock per draft, and the status is re-read inside it — a caller's stale
    APPROVED copy never writes a second ISR (Batch 2, P-15)."""
    if not writer_enabled():
        raise WriterDisabled('ISR_WRITER_ENABLED is off — refusing to push ISR.')
    from apps.vouchers.coupon_dashboard import pg_lock
    with pg_lock(LOCK_ISR_PUSH * 1_000_000 + isr_push.pk) as got:
        if not got:
            raise ValueError('هذا الطلب قيد الترحيل من عملية أخرى — لم يُرحَّل مرة ثانية.')
        isr_push.refresh_from_db()
        return _push_isr_record(isr_push, executed_by=executed_by, force_reason=force_reason)


def _push_isr_record(isr_push, *, executed_by=None, force_reason=''):
    from apps.purchasing.models import IsrPush
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection

    if not writer_enabled():
        raise WriterDisabled('ISR_WRITER_ENABLED is off — refusing to push ISR.')
    if isr_push.status != IsrPush.STATUS_APPROVED:
        raise ValueError(f'الطلب ليس معتمداً (الحالة={isr_push.status}) — لا يمكن ترحيله.')
    lines = isr_push.lines_snapshot or []
    if not lines:
        raise ValueError('لا توجد أسطر في المقترح.')
    # never the same ISR twice; a forwarding leg never before its feeding leg (isr_guards)
    from apps.purchasing import isr_guards
    isr_guards.check_push(isr_push, user=executed_by, force_reason=force_reason)

    branch = Branch.objects.get(softech_branch_id=isr_push.branchcode)
    usercode = _service_usercode()
    conn = None
    try:
        conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                     branch.db_name or 'SOFTECHDB9')
        w = _write_isr(conn, isr_push.branchcode, (isr_push.dest_branchcode or isr_push.branchcode), lines, usercode, do_commit=True, approved=True)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if w['verified'] and w['committed']:
        isr_push.status = IsrPush.STATUS_PUSHED
        isr_push.isrdocnumber = w['isrdocnumber']
        isr_push.pushed_at = timezone.now()
        isr_push.readback = w
        isr_push.error = ''
    else:
        isr_push.status = IsrPush.STATUS_FAILED
        isr_push.readback = w
        isr_push.error = f'verify/commit failed: {w}'[:300]
    isr_push.save(update_fields=['status', 'isrdocnumber', 'pushed_at', 'readback', 'error'])
    if isr_push.status == IsrPush.STATUS_PUSHED:                # who pushed it (Batch 2, P-16)
        from core.softech_audit import audit_softech_write
        audit_softech_write('softech_isr_pushed', actor=executed_by, obj=isr_push,
                            after={'isrdocnumber': w.get('isrdocnumber'), 'lines': len(lines)},
                            route=f'{isr_push.branchcode}→{isr_push.dest_branchcode or isr_push.branchcode}')
    logger.info('[isr_writer] push_isr_record %s → isr=%s status=%s',
                isr_push.pk, w.get('isrdocnumber'), isr_push.status)
    return isr_push


# ── item-list plan (for L2 transfer legs: lines come from an allocation) ────────
def build_items_plan(node_branch, items):
    """Build stockisr lines from an explicit [(itemcode, qty), …] allocation, reading
    nowqty from the SOURCE node's stkbal and pricing/supplier from the item master.
    Used for L2 legs (surplus→HQ, HQ→deficit) where lines come from TransferEngine,
    not per-branch gaps. node_branch = the source node whose stock feeds nowqty."""
    from apps.catalog.models import Item
    from config.sybase import get_branch_connection
    from apps.branches.models import Branch

    pairs = [(str(c).strip(), _int_qty(q)) for c, q in items if str(c).strip() and _int_qty(q) > 0]
    codes = [c for c, _ in pairs]
    if not codes:
        return []
    imap = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)
            .only('softech_id', 'name', 'supplier_code', 'pack_price', 'cost_price')}

    # nowqty at the source node (best-effort; 0 if unreachable)
    nowqty = {}
    b = Branch.objects.filter(softech_branch_id=str(node_branch)).first()
    if b:
        try:
            conn = get_branch_connection(b.effective_db_host, b.effective_db_port,
                                         b.db_name or 'SOFTECHDB9')
            cur = conn.cursor()
            for i in range(0, len(codes), _READ_CHUNK):
                chunk = codes[i:i + _READ_CHUNK]
                ph = ','.join('?' for _ in chunk)
                cur.execute(f"SELECT itemcode, sum(nowqty) FROM stkbal WHERE branchcode=? "
                            f"AND storecode NOT IN ('102','103','105') AND itemcode IN ({ph}) "
                            f"GROUP BY itemcode", [str(node_branch), *chunk])
                for r in cur.fetchall():
                    nowqty[str(r[0]).strip()] = float(r[1] or 0)
            cur.close(); conn.close()
        except Exception as exc:
            logger.warning('[isr_writer] build_items_plan nowqty read failed (%s) — using 0', exc)

    lines = []
    for code, qty in pairs:
        it = imap.get(code)
        if it is None:
            continue
        lines.append({
            'itemcode': code, 'item_name': it.name or '', 'itemqty': qty,
            'itemqty_cfarma': float(qty), 'nowqty': round(nowqty.get(code, 0.0), 3),
            'itemsaleprice': float(it.pack_price or 0), 'itemcostprice': float(it.cost_price or 0),
            'suppcode': str(it.supplier_code or '').strip(), 'gap': float(qty),
        })
    return lines


# ── create a proposal (PG only) + optional auto-approve+push ────────────────────
def _persist_proposal(*, source, dest, kind, lines, run_id=None, created_by=None, linked=None,
                      coverage_months=None, params=None, origin_isr=None, origin_request=None,
                      origin_donor='', notes=''):
    """Save one PROPOSED draft. Guards (isr_guards, doc 30 phase A): the route must be valid
    (never HQ → HQ); a GENERAL draft (no origin request) supersedes an older proposed draft
    on the same route and is refused while an approved one waits there. Drafts tied to a
    branch request / WhatsApp request keep their own per-request rules (DB constraints)."""
    from django.db import transaction
    from apps.purchasing.models import IsrPush
    from apps.branches.models import Branch
    from apps.purchasing import isr_guards
    if not lines:
        return None
    isr_guards.validate_route(kind, source, dest)
    docvalue = sum(float(l['itemqty']) * float(l['itemcostprice']) for l in lines)
    branch = Branch.objects.filter(softech_branch_id=str(source)).first()
    general = origin_isr is None and origin_request is None
    with transaction.atomic():
        older = isr_guards.check_route_free(kind, source, dest) if general else []
        isr_guards.retire(older, user=created_by)        # one live draft per route, always
        p = IsrPush.objects.create(
            branch=branch, branchcode=str(source), dest_branchcode=str(dest), kind=kind,
            run_id=run_id, status=IsrPush.STATUS_PROPOSED, line_count=len(lines),
            docvalue=round(docvalue, 3), lines_snapshot=lines, created_by=created_by, linked_push=linked,
            coverage_months=coverage_months, params=params or {}, origin_isr=origin_isr,
            origin_request=origin_request, origin_donor=origin_donor or '', notes=notes or '')
        isr_guards.link_superseded(older, p)
    return p


def create_proposal(branchcode, *, created_by=None, max_lines=None, run=None, from_hq=False,
                    coverage_months=None, rule='engine', rule_data=None, return_plan=False):
    """Replenishment proposal for a branch's needs. from_hq=True → source=HQ 100 (HQ
    prepares, branch receives, kind=hq_to_branch); else self (branchcode==dest, kind=self).
      rule='softech' (the /supply screen, owner 2026-10-24): SOFTECH's rule read live from
        server 100 — max − stock − transit, < 0.16 pack → 0, whole packs, HQ stock options
        and the screen filters (isr_softech.py). rule_data = the screen's settings.
      rule='engine': the engine gap, re-scaled by coverage_months (see build_plan).
    Writes PG only. Returns IsrPush or None (with return_plan: (IsrPush|None, plan))."""
    from apps.purchasing.models import IsrPush
    if rule == 'softech':
        from apps.purchasing import isr_softech
        data = dict(rule_data or {})
        data.setdefault('coverage_months', coverage_months)
        plan = isr_softech.build_plan(branchcode, data, max_lines=max_lines)
        params = {k: plan[k] for k in ('rule', 'settings', 'stats', 'as_of', 'transit_days')}
    else:
        plan = build_plan(branchcode, run=run, max_lines=max_lines, coverage_months=coverage_months)
        params = {'rule': 'engine'}
    if not plan['lines']:
        return (None, plan) if return_plan else None
    source = '100' if from_hq else str(branchcode)
    kind = IsrPush.KIND_HQ_TO_BRANCH if from_hq else IsrPush.KIND_SELF
    p = _persist_proposal(source=source, dest=str(branchcode), kind=kind,
                          lines=plan['lines'], run_id=plan.get('run_id'), created_by=created_by,
                          coverage_months=plan.get('coverage_months'), params=params)
    return (p, plan) if return_plan else p


def generate_transfers_from_run(*, run=None, from_branch=None, to_branch=None,
                                min_qty=1.0, max_pairs=None, created_by=None, skipped=None):
    """Read a TransferRecommendationRun (latest if None), group items by (surplus A →
    deficit B), and create two linked ISR proposals per pair. Returns a list of dicts
    {from, to, items, leg1_id, leg2_id}. Shared by the /supply endpoint + CLI command."""
    from collections import defaultdict
    from apps.purchasing.models import TransferRecommendationRun, TransferRecommendation

    run = run or (TransferRecommendationRun.objects.filter(status='success')
                  .order_by('-id').first())
    if run is None:
        raise ValueError('لا يوجد تشغيل توصيات تحويل ناجح — شغّل محرك الطلب أولاً.')
    qs = (TransferRecommendation.objects.filter(run=run)
          .select_related('item', 'from_branch', 'to_branch')
          .only('quantity', 'item__softech_id', 'from_branch__softech_branch_id',
                'to_branch__softech_branch_id'))
    if from_branch:
        qs = qs.filter(from_branch__softech_branch_id=str(from_branch))
    if to_branch:
        qs = qs.filter(to_branch__softech_branch_id=str(to_branch))

    pairs = defaultdict(list)
    for r in qs.iterator():
        a = r.from_branch.softech_branch_id if r.from_branch_id else None
        b = r.to_branch.softech_branch_id if r.to_branch_id else None
        code = str(r.item.softech_id or '').strip() if r.item_id else ''
        q = float(r.quantity or 0)
        if a and b and code and q >= min_qty:
            pairs[(a, b)].append((code, q))

    out = []
    for (a, b), items in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
        if max_pairs and len(out) >= max_pairs:
            break
        try:
            leg1, leg2 = create_transfer_proposals(a, b, items, created_by=created_by)
        except ValueError as exc:                # a guard refused this route (isr_guards)
            if skipped is not None:
                skipped.append({'route': f'{a} ← {b}', 'path': [a, b], 'reason': str(exc)})
            continue
        if leg1 or leg2:
            out.append({'from': a, 'to': b, 'items': len(items),
                        'leg1_id': (leg1.id if leg1 else None),
                        'leg2_id': (leg2.id if leg2 else None)})
    return out


def create_transfer_proposals(from_branch, to_branch, items, *, created_by=None):
    """L2: two linked ISR proposals for a surplus→HQ→deficit allocation.
      Leg 1: source=from_branch (surplus, prepares), dest=100 (HQ receives)  [branch_to_hq]
      Leg 2: source=100 (HQ prepares),      dest=to_branch (deficit receives) [hq_to_branch]
    items = [(itemcode, qty)]. Returns (leg1, leg2) IsrPush, or (None, None) if empty.
    A pair that TOUCHES HQ needs one leg only (2026-10-24: the transfer engine also pairs
    branch → 100 and 100 → branch; two legs made a «100 → 100» ISR). Same branch → nothing."""
    from django.db import transaction
    from apps.purchasing.models import IsrPush
    src, dst = str(from_branch), str(to_branch)
    if src == dst:
        return None, None
    if dst == HQ_CODE:                                       # surplus branch → HQ only
        return _persist_proposal(source=src, dest=HQ_CODE, kind=IsrPush.KIND_BRANCH_TO_HQ,
                                 lines=build_items_plan(src, items), created_by=created_by), None
    if src == HQ_CODE:                                       # HQ → deficit branch only
        return None, _persist_proposal(source=HQ_CODE, dest=dst, kind=IsrPush.KIND_HQ_TO_BRANCH,
                                       lines=build_items_plan(HQ_CODE, items), created_by=created_by)
    leg1_lines = build_items_plan(src, items)                # nowqty from surplus branch
    leg2_lines = build_items_plan(HQ_CODE, items)            # nowqty from HQ
    if not leg1_lines and not leg2_lines:
        return None, None
    with transaction.atomic():                               # both legs or neither
        leg1 = _persist_proposal(source=src, dest=HQ_CODE, kind=IsrPush.KIND_BRANCH_TO_HQ,
                                 lines=leg1_lines, created_by=created_by)
        leg2 = _persist_proposal(source=HQ_CODE, dest=dst, kind=IsrPush.KIND_HQ_TO_BRANCH,
                                 lines=leg2_lines, created_by=created_by, linked=leg1)
        if leg1 and leg2:
            leg1.linked_push = leg2
            leg1.save(update_fields=['linked_push'])
    return leg1, leg2


def create_distribution_proposals(*, categories=None, limit=None, created_by=None, skipped=None):
    """L3 توزيعة: turn distribution suggestions into ISR proposals, grouped by route.
      • HQ source (100)  → ONE HQ→branch ISR (kind=hq_to_branch) with all its items.
      • branch source A  → two-leg (A→HQ, HQ→branch) via create_transfer_proposals.
    Returns a list of {route, kind, ids, items}."""
    from collections import defaultdict
    from apps.purchasing.models import IsrPush
    from apps.purchasing import distribution

    sugs = distribution.analyze(categories=categories, limit=limit)
    routes = defaultdict(dict)   # (source, dest) -> {itemcode: qty}  (dedup items per route)
    for s in sugs:
        src = str(s['from_branch'])
        for t in s['to_branches']:
            # per-target qty (over_piled: up to that branch's room under its ceiling)
            routes[(src, str(t['code']))][s['itemcode']] = t.get('qty', s['qty_each'])

    created = []
    for (src, dest), item_map in routes.items():
        items = list(item_map.items())
        try:
            if src == HQ_CODE:
                lines = build_items_plan(HQ_CODE, items)
                p = _persist_proposal(source=HQ_CODE, dest=dest, kind=IsrPush.KIND_HQ_TO_BRANCH,
                                      lines=lines, created_by=created_by)
                if p:
                    created.append({'route': f'{HQ_CODE} ← {dest}', 'path': [HQ_CODE, dest], 'kind': 'hq_to_branch',
                                    'ids': [p.id], 'items': len(items)})
                continue
            leg1, leg2 = create_transfer_proposals(src, dest, items, created_by=created_by)
        except ValueError as exc:                # a guard refused this route (isr_guards)
            if skipped is not None:
                skipped.append({'route': f'{src} ← {dest}', 'path': [src, dest], 'reason': str(exc)})
            continue
        if leg1 or leg2:
            created.append({'route': f'{src} ← {HQ_CODE} ← {dest}', 'path': [src, HQ_CODE, dest], 'kind': 'transfer',
                            'ids': [x.id for x in (leg1, leg2) if x], 'items': len(items)})
    return created


def auto_generate(branchcode, *, created_by=None, max_lines=None, auto_approve=False):
    """Scheduled/CLI generation. Creates a proposal; when auto_approve (and both
    ISR_AUTO_APPROVE_ENABLED + ISR_WRITER_ENABLED are on) approves it and pushes to
    SOFTECH (israpp=1). Otherwise leaves it as a PG proposal for human review in /supply."""
    from apps.purchasing.models import IsrPush
    p = create_proposal(branchcode, created_by=created_by, max_lines=max_lines)
    if p is None:
        return None
    if auto_approve:
        if not auto_approve_enabled():
            raise WriterDisabled('ISR_AUTO_APPROVE_ENABLED is off — refusing to auto-approve.')
        p.status = IsrPush.STATUS_APPROVED
        p.approved_by = created_by
        p.approved_at = timezone.now()
        p.save(update_fields=['status', 'approved_by', 'approved_at'])
        push_isr_record(p, executed_by=created_by)   # gated ISR_WRITER_ENABLED → israpp=1
    return p


# ── Stage B — APPROVE an ISR (native «اعتماد الطلب» = stockisrm.israpp=1) ────────
# The modern طلب-توريد flow has NO separate order table (stockordersm is dead legacy,
# last write 2023). «اعتماد الطلب» simply sets stockisrm.israpp=1 (+isrusercode +
# isrtrans_time), which makes the ISR available for HQ إذن الصرف. Verified: the owner's
# اعتماد on #261306 flipped israpp 0→1.
def approve_isr(branchcode, isrdocnumber, *, executed_by=None):
    """Set stockisrm.israpp=1 for an ISR (the approval), gated + readback-verified."""
    if not writer_enabled():
        raise WriterDisabled('ISR_WRITER_ENABLED is off — refusing to approve.')
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection
    branch = Branch.objects.get(softech_branch_id=str(branchcode))
    usercode = _service_usercode()
    conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                 branch.db_name or 'SOFTECHDB9')
    try:
        cur = conn.cursor()
        cur.execute("SELECT israpp FROM stockisrm WHERE branchcode=? AND isrdocnumber=?",
                    [str(branchcode), int(isrdocnumber)])
        row = cur.fetchone()
        if row is None:
            return {'ok': False, 'error': 'ISR header not found', 'isrdocnumber': int(isrdocnumber)}
        already = int(row[0] or 0) == 1
        cur.execute("UPDATE stockisrm SET israpp=1, isrusercode=?, isrtrans_time=getdate() "
                    "WHERE branchcode=? AND isrdocnumber=?", [usercode, str(branchcode), int(isrdocnumber)])
        cur.execute("SELECT israpp FROM stockisrm WHERE branchcode=? AND isrdocnumber=?",
                    [str(branchcode), int(isrdocnumber)])
        approved = int(cur.fetchone()[0] or 0) == 1
        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    from core.softech_audit import audit_softech_write          # Batch 2, P-16
    audit_softech_write('softech_isr_approved', actor=executed_by, before={'israpp': 1 if already else 0},
                        after={'israpp': 1 if approved else 0}, branchcode=str(branchcode),
                        isrdocnumber=int(isrdocnumber))
    logger.info('[isr_writer] approve isr=%s branch=%s approved=%s (was %s)',
                isrdocnumber, branchcode, approved, 'approved' if already else 'pending')
    return {'ok': bool(approved), 'isrdocnumber': int(isrdocnumber),
            'was_already_approved': already, 'israpp': 1 if approved else 0}


def probe_approve_isr(branchcode, isrdocnumber, *, confirm=False):
    """Rehearse the approval with ZERO residue: read israpp, set 1, readback, then
    RESTORE the original israpp. Ignores the gate (always restores). confirm=True."""
    from core.softech_switches import require_probes
    require_probes('purchasing.isr_writer.probe_approve_isr')    # real DML on SOFTECH (Batch 2, P-7)
    if not confirm:
        raise ValueError('probe_approve_isr requires confirm=True (real UPDATE, then restores).')
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection
    branch = Branch.objects.get(softech_branch_id=str(branchcode))
    conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                 branch.db_name or 'SOFTECHDB9')
    res = {'branchcode': str(branchcode), 'isrdocnumber': int(isrdocnumber)}
    try:
        cur = conn.cursor()
        cur.execute("SELECT israpp FROM stockisrm WHERE branchcode=? AND isrdocnumber=?",
                    [str(branchcode), int(isrdocnumber)])
        row = cur.fetchone()
        if row is None:
            res['error'] = 'ISR header not found'
            return res
        orig = int(row[0] or 0)
        res['original_israpp'] = orig
        try:
            cur.execute("UPDATE stockisrm SET israpp=1 WHERE branchcode=? AND isrdocnumber=?",
                        [str(branchcode), int(isrdocnumber)])
            cur.execute("SELECT israpp FROM stockisrm WHERE branchcode=? AND isrdocnumber=?",
                        [str(branchcode), int(isrdocnumber)])
            res['write_landed'] = int(cur.fetchone()[0] or 0) == 1
        finally:
            # ALWAYS put the original israpp back — a failed readback must not leave a
            # pending ISR approved in SOFTECH (Batch 2, P-13).
            cur.execute("UPDATE stockisrm SET israpp=? WHERE branchcode=? AND isrdocnumber=?",
                        [orig, str(branchcode), int(isrdocnumber)])
        cur.execute("SELECT israpp FROM stockisrm WHERE branchcode=? AND isrdocnumber=?",
                    [str(branchcode), int(isrdocnumber)])
        res['restored'] = int(cur.fetchone()[0] or 0) == orig
        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.info('[isr_writer] probe_approve isr=%s landed=%s restored=%s',
                isrdocnumber, res.get('write_landed'), res.get('restored'))
    return res


# ── 3. ROLLBACK PROBE — real batch on the branch node, then ALWAYS rollback ─────
def probe_isr_write(branchcode, *, sample_n=3, confirm=False):
    """
    Rehearse the ISR write with ZERO residue: run the REAL serial-alloc + stockisr
    INSERTs + verify, then ROLLBACK. Reveals the allocated isrdocnumber and whether
    the inserts land (trigger behaviour) before any live commit. Requires confirm=True.
    """
    from core.softech_switches import require_probes
    require_probes('purchasing.isr_writer.probe_isr_write')    # real DML on SOFTECH (Batch 2, P-7)
    if not confirm:
        raise ValueError('probe_isr_write requires confirm=True (real INSERTs, then rolls back).')
    plan = build_plan(branchcode, max_lines=sample_n)
    if not plan['lines']:
        return {'mode': 'rollback_probe', 'branchcode': str(branchcode),
                'error': 'no engine lines with gap>0 for this branch'}
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection
    branch = Branch.objects.get(softech_branch_id=str(branchcode))
    conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                 branch.db_name or 'SOFTECHDB9')
    try:
        w = _write_isr(conn, branchcode, branchcode, plan["lines"], _service_usercode(), do_commit=False)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.info('[isr_writer] PROBE branch=%s isr=%s verified=%s — ROLLED BACK',
                branchcode, w['isrdocnumber'], w['verified'])
    return {'mode': 'rollback_probe', 'branchcode': str(branchcode), 'rolled_back': True,
            'sample_lines': len(plan['lines']), 'readback': w,
            'allocated_isrdocnumber': w['isrdocnumber'], 'ok': w['verified']}
