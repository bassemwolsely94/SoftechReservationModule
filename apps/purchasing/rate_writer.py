"""
apps/purchasing/rate_writer.py

FEATURE 1 — Sales-rate (معدل الإستهلاك) writeback into SOFTECH.

Pushes our engine's per-branch `ItemDemandMetrics.monthly_avg` into SOFTECH's
`stkbal.monthlyqty` — the exact field the «معدلات البيع» screen's
«تحديث معدل الإستهلاك >> 2» button writes (verified via probe_sales_rate:
audit pair usercode_mq/trans_time_mq, per-store values, gate items.itemupdt_monthlyqty='1').

Because a better monthlyqty feeds SOFTECH's OWN required-qty suggestion
(maxnowqtymonths × monthlyqty − nowqty − onorderqty), this single write also
improves the native replenishment order that Feature 2 builds on.

DESIGN (locked with owner):
  • monthlyqty is recomputed MANUALLY only (never a SOFTECH scheduled job) → our
    written value persists until someone re-runs the screen. Safe to own.
  • The rate lives on EACH BRANCH's own Sybase server → we write to the branch
    node directly (Branch.effective_db_host), never a single HQ push. Mirrors the
    per-branch writes in apps/discount_approvals/replication.py.
  • Only items flagged items.itemupdt_monthlyqty='1' are eligible (respect
    SOFTECH's own auto-update gate); everything else is SKIPPED and reported.
  • Every write also stamps usercode_mq = our ERP service usercode and
    trans_time_mq = GETDATE(), so SOFTECH's audit of the rate stays truthful.

⚠️ SAFETY — GATED, NO PROD WRITE BY DEFAULT ⚠️
Guarded by settings.SALES_RATE_WRITER_ENABLED (default False). With the gate OFF,
push() only PREPARES + returns the dry-run plan (the exact UPDATEs it WOULD run) —
nothing is sent to SOFTECH. build_plan() and probe are READ-ONLY always. Live
writes are simple idempotent UPDATEs of one rate field (no financial posting, no
stock movement, no trigger side-effects like the stktrans path) — but stay gated
until the owner reviews a dry-run.

RESOLVED via probe_sales_rate --fingerprint (natively-written rows, no press needed):
  • store == branchcode on EVERY branch 100–220 (confirmed) → resolve_store default correct;
  • native precision = 1 dp → RATE_DECIMALS = 1;
  • native leaves usercode_mq/trans_time_mq NULL, so stamping them makes OUR writes
    SOFTECH-side identifiable as ours (a free audit gain) — kept, owner may opt out.
  • HQ (softech_branch_id '100') multi-warehouse (stores 101/102/104) DEFERRED — our
    engine yields one branch-level number; HQ excluded in v1 (main store 100 == branch).
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

RATE_DECIMALS = 1                     # SOFTECH stores monthlyqty to 1 dp (verified via fingerprint)
VERIFY_TOL    = 0.05                  # readback tolerance (half a decimal place)
_READ_CHUNK   = 400                   # itemcodes per IN() read
_UPDATE_CHUNK = 150                   # monthlyqty UPDATEs per batch (ASE procedure-cache safe)


def _lit(v):
    """Minimal inline SQL literal (numbers bare, strings quoted). For the batched
    monthlyqty UPDATEs — a 30k-row feed as per-item round-trips is too slow."""
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


# ── max stock (maxnowqty) kept in step with rate × coverage ─────────────────────
# SOFTECH stores maxnowqty as a plain number and does NOT recompute it when the rate
# or coverage changes (verified br130 2026-09-27: coverage 1.5 written, maxnowqty
# stayed 0 on every row). Its purchase-invoice screen reads the STORED maxnowqty, so
# we compute it ourselves: maxnowqty = that row's monthlyqty × that row's
# maxnowqtymonths (0 when the rate is ≤ 0; production-wide 0 behaves as "no limit").
MAXQTY_DECIMALS = 1
# Owner rule (2026-09-28): for an item that sells, the max is never below ONE pack.
# rate × coverage alone gave ~5,000 slow sellers a max under 1 (1 pen/month × 1.5 →
# 0.2), so SOFTECH warned on buying even a single unit. Items with no sales keep 0.
MAXQTY_FLOOR = 1.0


def _refresh_maxqty() -> bool:
    """True when we are allowed to write maxnowqty (settings.COVERAGE_WRITE_MAXQTY)."""
    return bool(getattr(settings, 'COVERAGE_WRITE_MAXQTY', False))


def _expected_maxqty(rate, months) -> float:
    """What maxnowqty should be for a row: rate × coverage (1dp, half-up) but never below
    MAXQTY_FLOOR (1 pack); 0 if the item has no sales (rate ≤ 0) or no coverage.

    Multiplies in EXACT decimals, like SOFTECH does. A float product would be wrong on
    halves: 0.3 × 1.5 is 0.44999999… in float (→ 0.4) but exactly 0.45 (→ 0.5, what
    SOFTECH stores). That float bug flagged 1,036 correct br130 rows as failed
    (2026-09-27)."""
    r = Decimal(str(rate or 0))
    m = Decimal(str(months or 0))
    if r <= 0 or m <= 0:
        return 0.0
    v = float((r * m).quantize(Decimal(10) ** -MAXQTY_DECIMALS, rounding=ROUND_HALF_UP))
    return max(v, MAXQTY_FLOOR)


def _refresh_maxqty_sql(bc_lit, st_lit, uc_lit, codes) -> str:
    """ONE server-side UPDATE recomputing maxnowqty from each row's own monthlyqty and
    maxnowqtymonths, for the given items that HAVE a coverage set (rows without one are
    never touched). Stamps the max-qty audit pair. Shared by the rate writer (after a
    rate change) and the coverage writer (after a coverage change)."""
    inlist = ','.join(_lit(c) for c in codes)
    prod = f"round(monthlyqty * maxnowqtymonths, {MAXQTY_DECIMALS})"
    return (f"UPDATE stkbal SET maxnowqty = CASE WHEN monthlyqty > 0 "
            f"THEN (CASE WHEN {prod} < {MAXQTY_FLOOR} THEN {MAXQTY_FLOOR} ELSE {prod} END) "
            f"ELSE 0 END, "
            f"usercode_xq={uc_lit}, trans_time_xq=getdate() "
            f"WHERE branchcode={bc_lit} AND storecode={st_lit} AND maxnowqtymonths > 0 "
            f"AND itemcode IN ({inlist})")


def _needs_write(new, olds, min_delta) -> bool:
    """Write an item when the new value differs from the current value on ANY targeted
    server (olds = one current value per server; None = row absent there)."""
    return any(abs(float(new) - float(o or 0)) >= min_delta for o in olds)


def _apply_rate_updates(conn, branchcode, storecode, items, usercode):
    """Write monthlyqty for many items on one server FAST: chunked multi-statement
    UPDATE batches (inline literals) + a bulk readback to verify each landed.
    items = [(itemcode, new_rate)]. Returns {itemcode: landed_bool}. Idempotent —
    each UPDATE auto-commits (no atomicity needed for a rate field), so re-runnable.

    When COVERAGE_WRITE_MAXQTY is on, the same batch also refreshes maxnowqty for the
    items that have a coverage set, and the readback verifies that too."""
    bc, st, uc = _lit(str(branchcode)), _lit(str(storecode)), _lit(str(usercode))
    intended = {str(c).strip(): float(r) for c, r in items}
    codes = [c for c in intended if c]
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _UPDATE_CHUNK):
            chunk = codes[i:i + _UPDATE_CHUNK]
            stmts = [
                f"UPDATE stkbal SET monthlyqty={_lit(intended[c])}, usercode_mq={uc}, "
                f"trans_time_mq=getdate() WHERE branchcode={bc} AND storecode={st} AND itemcode={_lit(c)}"
                for c in chunk
            ]
            if _refresh_maxqty():
                stmts.append(_refresh_maxqty_sql(bc, st, uc, chunk))
            cur.execute('\n'.join(stmts))
    finally:
        _safe_close(cur)
    return _verify_rates(conn, branchcode, storecode, intended)


def _verify_rates(conn, branchcode, storecode, intended) -> dict:
    """Read back monthlyqty (and the max for items with a coverage, when max writing is
    on). intended = {itemcode: rate}. Returns {itemcode: verified}; an absent row = False."""
    codes = [c for c in intended if c]
    refresh = _refresh_maxqty()
    landed = {c: False for c in codes}
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(f"SELECT itemcode, monthlyqty, maxnowqtymonths, maxnowqty FROM stkbal "
                        f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                        [str(branchcode), str(storecode), *chunk])
            for r in cur.fetchall():
                c = str(r[0]).strip()
                if c not in intended:
                    continue
                rate, months, maxqty = float(r[1] or 0), float(r[2] or 0), float(r[3] or 0)
                ok = abs(rate - intended[c]) < VERIFY_TOL
                if ok and refresh and months > 0:
                    ok = abs(maxqty - _expected_maxqty(rate, months)) < VERIFY_TOL
                landed[c] = ok
    finally:
        _safe_close(cur)
    return landed


# ── resume after a dropped connection (shared with coverage_writer) ─────────────
# A branch server can drop the connection mid-write (br140 at 89%, br150 JZ006 —
# 2026-09-27). Writes are idempotent, so after a drop we reconnect, ask SOFTECH what
# actually landed, and write only the rest. First try + 2 resumes.
MAX_WRITE_ATTEMPTS = 3


def _safe_close(obj):
    """Close a cursor/connection; a failure here must never discard finished work."""
    try:
        obj.close()
    except Exception:
        pass


def _write_surface_with_resume(branch, label, codes, *, write_fn, verify_fn):
    """Write one server (label 'node' | 'hq'), resuming after a dropped connection.
    write_fn(conn, codes) writes + verifies and returns {itemcode: verified};
    verify_fn(conn, codes) only reads back. After any failure a FRESH connection
    re-reads what actually landed, so the result reflects SOFTECH, not the failed
    attempt. Returns ({itemcode: verified}, [errors])."""
    landed = {c: False for c in codes}
    remaining = list(codes)
    errors = []
    bname = getattr(branch, 'softech_branch_id', branch)
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        conn = None
        try:
            conn = _read_conn_for_target(branch, label)
            landed.update(write_fn(conn, remaining))
        except Exception as exc:
            errors.append(f'attempt {attempt}: {str(exc)[:150]}')
            logger.warning('[writer] branch %s %s attempt %d failed: %s',
                           bname, label, attempt, exc)
            vconn = None
            try:
                vconn = _read_conn_for_target(branch, label)
                landed.update(verify_fn(vconn, remaining))
            except Exception as exc2:
                errors.append(f'attempt {attempt} re-check: {str(exc2)[:150]}')
            finally:
                if vconn is not None:
                    _safe_close(vconn)
        finally:
            if conn is not None:
                _safe_close(conn)
        remaining = [c for c in codes if not landed.get(c)]
        if not remaining:
            break
    return landed, errors


def _write_all_surfaces(branch, target, bc, store, intended, usercode):
    """Write rates to every targeted server of one branch with resume. A line counts as
    verified only when it landed on EVERY server. Returns ({itemcode: ok}, [errors])."""
    codes = [c for c in intended if c]
    labels = [TARGET_NODE, TARGET_HQ] if target == TARGET_BOTH else [target]
    ok_by_item = {c: True for c in codes}
    errors = []
    for label in labels:
        landed, errs = _write_surface_with_resume(
            branch, label, codes,
            write_fn=lambda cn, cs: _apply_rate_updates(
                cn, bc, store, [(c, intended[c]) for c in cs], usercode),
            verify_fn=lambda cn, cs: _verify_rates(cn, bc, store, {c: intended[c] for c in cs}))
        errors += [f'[{label}] {e}' for e in errs]
        for c in codes:
            ok_by_item[c] = ok_by_item[c] and bool(landed.get(c, False))
    return ok_by_item, errors


class WriterDisabled(RuntimeError):
    """Raised if a real SOFTECH write is attempted while the gate is off."""


def writer_enabled() -> bool:
    return bool(getattr(settings, 'SALES_RATE_WRITER_ENABLED', False))


def _service_usercode() -> str:
    """Same ERP service identity discount_approvals uses; falls back to '1'."""
    return str(getattr(settings, 'ERP_SERVICE_USERCODE', '') or '1').strip() or '1'


def _round(v) -> float:
    return float(Decimal(str(v or 0)).quantize(Decimal(10) ** -RATE_DECIMALS,
                                               rounding=ROUND_HALF_UP))


def resolve_store(branch) -> str:
    """
    The storecode whose monthlyqty holds this branch's selling rate.

    Default = the branch's own code (retail branches keep their main selling store
    at storecode == branchcode — confirmed by probe for 130/140/150/160/170). An
    explicit per-branch override map handles exceptions:
        settings.SALES_RATE_STORE_MAP = {'160': '161', ...}
    HQ multi-warehouse is intentionally NOT resolved here (see module docstring).
    """
    override = (getattr(settings, 'SALES_RATE_STORE_MAP', {}) or {})
    return str(override.get(branch.softech_branch_id, branch.softech_branch_id))


# ── source: latest successful engine run ────────────────────────────────────────
def _latest_run():
    from apps.purchasing.models import DemandCalculationRun
    return (DemandCalculationRun.objects
            .filter(status='success')
            .order_by('-finished_at', '-id')
            .first())


def _eligible_branches(branch_filter=None):
    """Operational branches with their own reachable db_host. HQ is excluded in v1
    (multi-warehouse rate mapping deferred). branch_filter = iterable of
    softech_branch_id to restrict to."""
    from apps.branches.models import Branch
    qs = (Branch.objects.filter(is_active=True, is_operational=True)
          .exclude(db_host='').exclude(db_host__isnull=True)
          .exclude(softech_branch_id='100'))          # HQ deferred
    if branch_filter:
        qs = qs.filter(softech_branch_id__in=[str(b) for b in branch_filter])
    return list(qs)


# ── write topology (Batch 3): which SOFTECH surface(s) receive the write ─────────
# The branch's own node and HQ's mirror hold INDEPENDENT, unsynced copies of the same
# (branchcode, storecode, itemcode) row (verified: values diverge), each feeding a
# different consumer (branch node → branch POS/replenishment; HQ mirror → HQ-level
# consolidated replenishment/reporting). DEFAULT 'both' (owner, 2026-09-27): every
# push keeps the branch server AND server 100 (192.168.1.8) in step; 'node' / 'hq'
# remain selectable to update just one of them.
# NB: branch 100's OWN rows (branchcode=100) are never written — _eligible_branches
# excludes HQ — while OTHER branches' rows on server 100 (e.g. branchcode=130) are.
TARGET_NODE = 'node'
TARGET_HQ   = 'hq'
TARGET_BOTH = 'both'
_VALID_TARGETS = {TARGET_NODE, TARGET_HQ, TARGET_BOTH}


def _read_conn_for_target(branch, target):
    """Connection to READ current state from (the primary surface for the target)."""
    from config.sybase import get_branch_connection, get_sybase_connection
    if target == TARGET_HQ:
        return get_sybase_connection()
    return get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                 branch.db_name or 'SOFTECHDB9')


def _write_conns_for_target(branch, target):
    """List of (label, conn) surfaces to WRITE for this target. Caller closes each."""
    from config.sybase import get_branch_connection, get_sybase_connection
    surfaces = []
    if target in (TARGET_NODE, TARGET_BOTH):
        surfaces.append(('node', get_branch_connection(
            branch.effective_db_host, branch.effective_db_port, branch.db_name or 'SOFTECHDB9')))
    if target in (TARGET_HQ, TARGET_BOTH):
        surfaces.append(('hq', get_sybase_connection()))
    return surfaces


# ── 1. BUILD PLAN — READ-ONLY (reads SOFTECH current state, computes deltas) ─────
# ── rate-method selection (Topic 1) ─────────────────────────────────────────────
# Two interchangeable ways to derive the per-item monthly rate we push:
#   'pivot'    — ItemDemandMetrics.monthly_avg (weighted 30/90/365 blend). Default.
#   'advanced' — advanced_engine policy_demand (Croston rate for intermittent/lumpy
#                items, else trend×seasonal forecast). Better for new/erratic items.
METHOD_PIVOT    = 'pivot'
METHOD_ADVANCED = 'advanced'

# Only these AdvancedConfig knobs (the ones that actually move policy_demand) may be
# set from an API request — everything else keeps the engine default.
_ADV_PARAM_WHITELIST = {
    'history_months', 'bulk_cap_factor', 'trend_months', 'trend_clamp',
    'base_rate_halflife_months',
}


def _make_adv_config(method_params):
    """Build an AdvancedConfig from a whitelisted params dict (ignores unknown keys)."""
    from apps.purchasing.advanced_engine import AdvancedConfig
    kw = {}
    for k, v in (method_params or {}).items():
        if k in _ADV_PARAM_WHITELIST and v is not None:
            kw[k] = v
    return AdvancedConfig(**kw)


def _real_stock_filter(qs):
    """Keep only items that are real stock (qs over ItemDemandMetrics):
      • is_stockable=True — drop non-stockable / service items,
      • pack_price > 0 — coupons/gifts carry a zero/negative price (118639 = −50),
      • medicine_type != '60' — هدايا عملاء (customer-gift/coupon category).
    One shared definition: the ISR writer uses it (plus its own supplier-status rule)
    and the coverage writer uses it so coupons never get a max-stock ceiling."""
    return (qs.filter(item__is_stockable=True, item__pack_price__gt=0)
              .exclude(item__medicine_type='60'))


def _pivot_want(run, branches, item_filter, *, stock_only=False):
    """branchcode -> {itemcode: (rate, name)} from the persisted monthly_avg.
    stock_only=True drops coupons / gifts / non-stockable items (_real_stock_filter)."""
    from apps.purchasing.models import ItemDemandMetrics
    want = {}
    qs = (ItemDemandMetrics.objects.filter(run=run, branch__in=branches)
          .select_related('item', 'branch')
          .only('monthly_avg', 'item__softech_id', 'item__name', 'branch__softech_branch_id'))
    if stock_only:
        qs = _real_stock_filter(qs)
    if item_filter:
        qs = qs.filter(item__softech_id__in=[str(i) for i in item_filter])
    for m in qs.iterator():
        code = str(m.item.softech_id or '').strip()
        if not code:
            continue
        want.setdefault(m.branch.softech_branch_id, {})[code] = (
            _round(m.monthly_avg), m.item.name or '')
    return want


def _advanced_want(run, branches, item_filter, method_params):
    """branchcode -> {itemcode: (rate, name)} from advanced_engine policy_demand
    (Croston / forecast). Read-only; one bulk series load inside run_advanced.
    Falls back to forecast_demand, then monthly_avg, when policy_demand is None."""
    from apps.purchasing.models import ItemDemandMetrics
    from apps.purchasing.advanced_engine import run_advanced
    qs = (ItemDemandMetrics.objects.filter(run=run, branch__in=branches)
          .select_related('item', 'branch'))
    if item_filter:
        qs = qs.filter(item__softech_id__in=[str(i) for i in item_filter])
    cfg = _make_adv_config(method_params)
    want = {}
    for metric, row in run_advanced(run, cfg, metrics_qs=qs):
        code = str((metric.item.softech_id if metric.item else '') or '').strip()
        if not code:
            continue
        rate = row.get('policy_demand')
        if rate is None:
            rate = row.get('forecast_demand')
        if rate is None:
            rate = float(metric.monthly_avg or 0)
        want.setdefault(metric.branch.softech_branch_id, {})[code] = (
            _round(rate), metric.item.name or '')
    return want


def build_plan(*, run=None, branch_filter=None, item_filter=None, min_delta=0.0005,
               method=METHOD_PIVOT, method_params=None, target=TARGET_BOTH):
    """
    Read the engine's per-branch rate for the latest successful run (by `method`),
    read the CURRENT stkbal.monthlyqty on every targeted server + the
    items.itemupdt_monthlyqty gate, and return the per-branch list of proposed rate
    changes. NEVER writes.

    method = 'pivot' (monthly_avg, default) | 'advanced' (Croston/forecast policy_demand).
    method_params = optional AdvancedConfig knobs (whitelisted) for the advanced method.
    target = 'both' (branch server + server 100, DEFAULT) | 'node' | 'hq'.
    With 'both', an item is included when its rate differs on EITHER server (server 100's
    copies of branch rates drift from the branch servers — 74–85% differed 2026-09-27).

    Returns:
      {
        'run_id': int, 'calc_date': str, 'method': str, 'method_params': dict, 'target': str,
        'branches': [ { 'branchcode','name','store','host','reachable':bool,
                        'changes': [ {itemcode,item_name,old,old_hq,new,delta,eligible,reason} ],
                        'eligible_count','skipped_count','error'? } ],
        'totals': {branches, eligible, skipped, unreachable},
      }
    `old` = current value on the primary server (branch server for node/both, server 100
    for hq); `old_hq` = server 100's current value when target='both', else None.
    item_filter = iterable of softech itemcodes to restrict to (debug/dry-run).
    """
    run = run or _latest_run()
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب (DemandCalculationRun).')

    method = (method or METHOD_PIVOT).lower()
    if method not in (METHOD_PIVOT, METHOD_ADVANCED):
        raise ValueError(f'طريقة معدل غير معروفة: {method}')
    target = (target or TARGET_BOTH).lower()
    if target not in _VALID_TARGETS:
        raise ValueError(f'وجهة كتابة غير معروفة: {target}')

    branches = _eligible_branches(branch_filter)
    bmap = {b.softech_branch_id: b for b in branches}

    # engine rate per (softech_branch_id, softech_itemcode) — by the chosen method
    if method == METHOD_ADVANCED:
        want = _advanced_want(run, branches, item_filter, method_params)
    else:
        want = _pivot_want(run, branches, item_filter)

    out_branches = []
    tot = {'branches': 0, 'eligible': 0, 'skipped': 0, 'unreachable': 0}

    for bc, items in want.items():
        branch = bmap[bc]
        store = resolve_store(branch)
        entry = {'branchcode': bc, 'name': branch.name, 'store': store,
                 'host': branch.effective_db_host, 'reachable': True,
                 'changes': [], 'eligible_count': 0, 'skipped_count': 0}
        tot['branches'] += 1

        codes = list(items.keys())
        try:
            conn = _read_conn_for_target(branch, target)   # node (default) or HQ mirror
        except Exception as exc:
            entry['reachable'] = False
            entry['error'] = str(exc)[:120]
            tot['unreachable'] += 1
            out_branches.append(entry)
            continue

        try:
            cur_rate = _read_current_rates(conn, bc, store, codes)   # itemcode -> monthlyqty
            gate = _read_update_gate(conn, codes)                    # itemcode -> '0'/'1'
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # 'both' → also read server 100's copy of this branch's rows; a both-push needs
        # both servers, so an unreachable server 100 makes the branch unreachable.
        cur_hq = None
        if target == TARGET_BOTH:
            try:
                from config.sybase import get_sybase_connection
                hconn = get_sybase_connection()
                try:
                    cur_hq = _read_current_rates(hconn, bc, store, codes)
                finally:
                    try:
                        hconn.close()
                    except Exception:
                        pass
            except Exception as exc:
                entry['reachable'] = False
                entry['error'] = f'[server 100] {str(exc)[:110]}'
                tot['unreachable'] += 1
                out_branches.append(entry)
                continue

        for code, (new_rate, name) in items.items():
            old = cur_rate.get(code)
            old_hq = cur_hq.get(code) if cur_hq is not None else None
            flag = gate.get(code, '0')
            if flag != '1':
                entry['changes'].append({
                    'itemcode': code, 'item_name': name, 'old': old, 'old_hq': old_hq,
                    'new': new_rate, 'delta': None, 'eligible': False,
                    'reason': 'itemupdt_monthlyqty!=1 (SOFTECH excludes this item)'})
                entry['skipped_count'] += 1
                tot['skipped'] += 1
                continue
            olds = [old] if cur_hq is None else [old, old_hq]
            if not _needs_write(new_rate, olds, min_delta):
                entry['skipped_count'] += 1
                tot['skipped'] += 1
                continue
            entry['changes'].append({
                'itemcode': code, 'item_name': name, 'old': old, 'old_hq': old_hq,
                'new': new_rate, 'delta': round(new_rate - float(old or 0), RATE_DECIMALS),
                'eligible': True, 'reason': ''})
            entry['eligible_count'] += 1
            tot['eligible'] += 1

        out_branches.append(entry)

    return {'run_id': run.id, 'calc_date': str(run.calc_date),
            'method': method, 'method_params': (method_params or {}), 'target': target,
            'branches': out_branches, 'totals': tot}


def _read_current_rates(conn, branchcode, storecode, itemcodes) -> dict:
    """READ stkbal.monthlyqty for (branchcode, storecode, itemcode…) chunked."""
    out = {}
    codes = [c for c in dict.fromkeys(str(x).strip() for x in itemcodes) if c]
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(
                f"SELECT itemcode, monthlyqty FROM stkbal "
                f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                [branchcode, storecode, *chunk])
            for r in cur.fetchall():
                out[str(r[0]).strip()] = float(r[1]) if r[1] is not None else 0.0
    finally:
        cur.close()
    return out


def _read_update_gate(conn, itemcodes) -> dict:
    """READ items.itemupdt_monthlyqty ('1' = SOFTECH allows monthlyqty update)."""
    out = {}
    codes = [c for c in dict.fromkeys(str(x).strip() for x in itemcodes) if c]
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(
                f"SELECT itemcode, itemupdt_monthlyqty FROM items "
                f"WHERE itemcode IN ({ph})", chunk)
            for r in cur.fetchall():
                out[str(r[0]).strip()] = str(r[1] or '').strip()
    finally:
        cur.close()
    return out


# ── persistence: snapshot a plan into the SalesRatePush audit spine ─────────────
def persist_plan(plan, *, created_by=None, scope=None, status=None):
    """Write a SalesRatePush (+ lines) recording this plan — proposed for a dry-run,
    executed for a commit. Returns the SalesRatePush. Pure PG; no SOFTECH contact."""
    from apps.purchasing.models import SalesRatePush, SalesRatePushLine
    from apps.catalog.models import Item
    from apps.branches.models import Branch

    t = plan['totals']
    executed = plan.get('mode') == 'commit'
    written = sum(b.get('written', 0) for b in plan['branches'])
    verified = sum(b.get('verified', 0) for b in plan['branches'])
    reverted = sum(b.get('reverted', 0) for b in plan['branches'])

    if status:
        st = status
    elif not executed:
        st = SalesRatePush.STATUS_PROPOSED
    elif written == 0 and (t['unreachable'] > 0 or any(b.get('error') for b in plan['branches'])):
        # a commit that reached nothing (all branches unreachable / errored) is a
        # failed attempt, not an execution — keep the audit list honest.
        st = SalesRatePush.STATUS_FAILED
    else:
        st = SalesRatePush.STATUS_EXECUTED

    push_obj = SalesRatePush.objects.create(
        run_id=plan.get('run_id'), status=st, created_by=created_by, scope=(scope or {}),
        method=plan.get('method', SalesRatePush.METHOD_PIVOT),
        method_params=plan.get('method_params') or {},
        target=plan.get('target', SalesRatePush.TARGET_BOTH),
        branches_count=t['branches'], eligible_count=t['eligible'], skipped_count=t['skipped'],
        unreachable_count=t['unreachable'], written_count=written, verified_count=verified,
        reverted_count=reverted,
        executed_at=(timezone.now() if st == SalesRatePush.STATUS_EXECUTED else None))

    codes = {c['itemcode'] for b in plan['branches'] for c in b['changes']}
    item_map = {i.softech_id: i.id for i in
                Item.objects.filter(softech_id__in=codes).only('id', 'softech_id')}
    bcodes = {b['branchcode'] for b in plan['branches']}
    branch_map = {b.softech_branch_id: b.id for b in
                  Branch.objects.filter(softech_branch_id__in=bcodes).only('id', 'softech_branch_id')}

    lines = []
    for b in plan['branches']:
        for c in b['changes']:
            lines.append(SalesRatePushLine(
                push=push_obj, item_id=item_map.get(c['itemcode']),
                branch_id=branch_map.get(b['branchcode']), itemcode=c['itemcode'],
                item_name=(c['item_name'] or '')[:120], branchcode=b['branchcode'],
                storecode=b['store'], old_rate=c['old'], old_rate_hq=c.get('old_hq'),
                new_rate=c['new'],
                eligible=c['eligible'], reason=(c['reason'] or '')[:120],
                written=bool(executed and c['eligible'] and 'verified' in c),
                verified=bool(c.get('verified')), error=(b.get('error') or '')[:200]))
    SalesRatePushLine.objects.bulk_create(lines, batch_size=500)
    plan['push_id'] = push_obj.id
    logger.info('[rate_writer] persisted SalesRatePush %d (%s, %d lines)',
                push_obj.id, st, len(lines))
    return push_obj


# ── 2. PUSH — guarded; dry-run plan unless gate on + dry_run=False ──────────────
def push(*, run=None, branch_filter=None, item_filter=None, dry_run=True,
         persist=False, created_by=None, method=METHOD_PIVOT, method_params=None,
         target=TARGET_BOTH):
    """
    Build the plan, then (only when writer_enabled() AND dry_run=False) apply the
    eligible UPDATEs on each branch node, with a per-row readback verify.

    Each write:
        UPDATE stkbal SET monthlyqty=?, usercode_mq=?, trans_time_mq=getdate()
        WHERE branchcode=? AND storecode=? AND itemcode=?
    then reads monthlyqty back and confirms it landed (branch triggers can revert
    direct writes — reported honestly, exactly like replication.force_replication).

    Returns the plan dict enriched per branch with 'written'/'verified'/'reverted'.
    """
    plan = build_plan(run=run, branch_filter=branch_filter, item_filter=item_filter,
                      method=method, method_params=method_params, target=target)
    scope = {'branch_filter': list(branch_filter) if branch_filter else None,
             'item_filter': list(item_filter) if item_filter else None}

    if not writer_enabled() or dry_run:
        plan['mode'] = 'dry_run'
        plan['wrote_to_softech'] = False
        logger.info('[rate_writer] DRY-RUN (enabled=%s dry_run=%s) — %d eligible across %d branches',
                    writer_enabled(), dry_run, plan['totals']['eligible'], plan['totals']['branches'])
        if persist:
            persist_plan(plan, created_by=created_by, scope=scope)
        return plan

    from apps.branches.models import Branch

    usercode = _service_usercode()
    plan['mode'] = 'commit'
    plan['wrote_to_softech'] = True
    plan['target'] = target

    for entry in plan['branches']:
        if not entry['reachable']:
            continue
        eligible = [c for c in entry['changes'] if c['eligible']]
        if not eligible:
            entry['written'] = 0
            continue
        branch = Branch.objects.get(softech_branch_id=entry['branchcode'])
        store = entry['store']
        intended = {str(c['itemcode']).strip(): float(c['new']) for c in eligible}
        # resumes after a dropped connection; verified only if landed on EVERY server
        ok_by_item, errors = _write_all_surfaces(branch, target, entry['branchcode'], store,
                                                 intended, usercode)
        if errors:
            entry['error'] = ' | '.join(errors)[:400]
            entry['connection_drops'] = len(errors)
        written = verified = reverted = 0
        for c in eligible:
            ok = ok_by_item.get(str(c['itemcode']).strip(), False)
            c['verified'] = ok
            written += 1
            verified += 1 if ok else 0
            reverted += 0 if ok else 1
        entry.update(written=written, verified=verified, reverted=reverted)

    logger.info('[rate_writer] COMMIT done (target=%s) — %d eligible across %d branches',
                target, plan['totals']['eligible'], plan['totals']['branches'])
    if persist:
        persist_plan(plan, created_by=created_by, scope=scope)
    return plan


# ── execute an APPROVED proposal (writes the reviewed snapshot lines) ───────────
def execute_push(push, *, executed_by=None):
    """
    Write the eligible lines of an APPROVED SalesRatePush to SOFTECH, per branch
    node, with per-line readback verify. Gate + status are checked BEFORE any
    SOFTECH connection (so a disabled gate / wrong status fails fast, no DB hit).
    Updates each line's written/verified/error and the push totals + status.
    """
    from apps.purchasing.models import SalesRatePush, SalesRatePushLine
    from apps.branches.models import Branch

    if not writer_enabled():
        raise WriterDisabled('SALES_RATE_WRITER_ENABLED is off — refusing to execute.')
    if push.status != SalesRatePush.STATUS_APPROVED:
        raise ValueError(f'الدفعة ليست معتمدة (الحالة={push.status}) — لا يمكن تنفيذها.')

    target = (push.target or TARGET_BOTH).lower()
    if target not in _VALID_TARGETS:
        target = TARGET_BOTH
    usercode = _service_usercode()
    lines = list(push.lines.filter(eligible=True))
    by_branch = {}
    for ln in lines:
        by_branch.setdefault(ln.branchcode, []).append(ln)

    written = verified = reverted = 0
    for bc, blines in by_branch.items():
        branch = Branch.objects.filter(softech_branch_id=bc).first()
        if branch is None:
            for ln in blines:
                ln.error = 'branch not found in PG'
            continue
        store = blines[0].storecode
        intended = {str(ln.itemcode).strip(): float(ln.new_rate) for ln in blines}
        # resumes after a dropped connection; verified only if landed on EVERY server
        ok_by_item, errors = _write_all_surfaces(branch, target, bc, store, intended, usercode)
        if errors:
            logger.warning('[rate_writer] execute_push branch %s: %d connection drop(s), resumed',
                           bc, len(errors))
        for ln in blines:
            ok = ok_by_item.get(str(ln.itemcode).strip(), False)
            ln.written = True
            ln.verified = ok
            # only lines that did NOT land carry an error — a recovered drop is not a failure
            ln.error = '' if ok else (' | '.join(errors)[:200] or 'not confirmed on readback')
            written += 1
            verified += 1 if ok else 0
            reverted += 0 if ok else 1

    SalesRatePushLine.objects.bulk_update(lines, ['written', 'verified', 'error'], batch_size=500)
    push.status = SalesRatePush.STATUS_EXECUTED
    push.executed_at = timezone.now()
    push.written_count, push.verified_count, push.reverted_count = written, verified, reverted
    push.save(update_fields=['status', 'executed_at', 'written_count',
                             'verified_count', 'reverted_count'])
    logger.info('[rate_writer] executed push %d — written=%d verified=%d reverted=%d',
                push.id, written, verified, reverted)
    return push


# ── 3. ROLLBACK WRITE-PROBE — real UPDATE on ONE node, then ALWAYS restore ──────
def probe_write(branch_softech_id, itemcode, *, confirm=False):
    """
    Rehearse a single monthlyqty write on one branch node with ZERO residue:
    read the current value, UPDATE it to a marker, read it back, then restore the
    ORIGINAL value (and original usercode_mq/trans_time_mq). Reveals whether direct
    writes land or a branch trigger reverts them — the same lesson invoices.probe
    teaches for stktrans. Requires confirm=True; ignores the writer gate (it always
    restores). Runs off-peak.
    """
    if not confirm:
        raise ValueError('probe_write requires confirm=True (real UPDATE, then restores original).')
    from apps.branches.models import Branch
    from config.sybase import get_branch_connection

    branch = Branch.objects.get(softech_branch_id=str(branch_softech_id))
    store = resolve_store(branch)
    conn = get_branch_connection(branch.effective_db_host, branch.effective_db_port,
                                 branch.db_name or 'SOFTECHDB9')
    res = {'branchcode': branch.softech_branch_id, 'store': store, 'itemcode': str(itemcode)}
    try:
        cur = conn.cursor()
        cur.execute("SELECT monthlyqty, usercode_mq, trans_time_mq FROM stkbal "
                    "WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [branch.softech_branch_id, store, str(itemcode)])
        row = cur.fetchone()
        if row is None:
            res['error'] = 'no stkbal row for that (branch, store, item)'
            return res
        orig_rate = float(row[0]) if row[0] is not None else 0.0
        orig_user = str(row[1] or '')
        orig_time = row[2]
        res['original'] = {'monthlyqty': orig_rate, 'usercode_mq': orig_user,
                           'trans_time_mq': str(orig_time)}

        # Marker must differ from the original AT the stored precision (1 dp), else
        # the readback "verifies" a no-op. Use a full 1-dp step.
        marker = round(orig_rate + 0.1, RATE_DECIMALS) if orig_rate < 9999 else round(orig_rate - 0.1, RATE_DECIMALS)
        cur.execute("UPDATE stkbal SET monthlyqty=?, usercode_mq=?, trans_time_mq=getdate() "
                    "WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [marker, _service_usercode(), branch.softech_branch_id, store, str(itemcode)])
        cur.execute("SELECT monthlyqty FROM stkbal "
                    "WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [branch.softech_branch_id, store, str(itemcode)])
        rb = cur.fetchone()
        landed = rb is not None and abs(float(rb[0] or 0) - marker) < VERIFY_TOL
        res['write_landed'] = bool(landed)
        res['readback'] = float(rb[0]) if rb and rb[0] is not None else None

        # RESTORE the original. usercode_mq/trans_time_mq restored via INLINE literals
        # (jConnect cannot bind a Python datetime as a parameter); NULL when the row had
        # none (the native state per fingerprint). monthlyqty binds fine as a float.
        uc_lit = 'NULL' if not orig_user else "'" + str(orig_user).replace("'", "''") + "'"
        if orig_time is None:
            tt_lit = 'NULL'
        else:
            try:
                tt_lit = f"convert(datetime, '{orig_time:%Y-%m-%d %H:%M:%S}')"
            except Exception:
                tt_lit = 'NULL'
        cur.execute(f"UPDATE stkbal SET monthlyqty=?, usercode_mq={uc_lit}, trans_time_mq={tt_lit} "
                    f"WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [orig_rate, branch.softech_branch_id, store, str(itemcode)])
        cur.execute("SELECT monthlyqty FROM stkbal "
                    "WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [branch.softech_branch_id, store, str(itemcode)])
        fin = cur.fetchone()
        res['restored'] = fin is not None and abs(float(fin[0] or 0) - orig_rate) < VERIFY_TOL
        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.info('[rate_writer] probe_write br=%s item=%s landed=%s restored=%s',
                res.get('branchcode'), res.get('itemcode'),
                res.get('write_landed'), res.get('restored'))
    return res
