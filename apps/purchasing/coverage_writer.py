"""
apps/purchasing/coverage_writer.py

BATCH 2b — max-stock COVERAGE (maxnowqtymonths) writeback into SOFTECH.

Writes our chosen coverage window into SOFTECH's per-(branchcode, storecode, itemcode)
`stkbal.maxnowqtymonths` — the field SOFTECH multiplies by `monthlyqty` (the sales
rate Feature 1 maintains) to derive the `maxnowqty` max-stock ceiling that caps a
branch's holding. In production this field is DORMANT (≈0% populated), so writing it
activates SOFTECH's own overstock guard for the first time — hence it is GATED and
dry-run by default (owner reviews the plan before the gate is flipped).

Field map (verified read-only, 2026-09-20):
  • stkbal.maxnowqtymonths — coverage in months (what we write).
  • stkbal.maxnowqty       — max stock = monthlyqty × maxnowqtymonths, STORED. SOFTECH
                             does NOT recompute it (verified br130 2026-09-27: coverage
                             written, maxnowqty stayed 0) and its purchase-invoice screen
                             reads the stored value (above-max warning) → we write it when
                             settings.COVERAGE_WRITE_MAXQTY is on, and the rate writer
                             keeps it in step on every rate change.
  • stkbal.usercode_xq / trans_time_xq — the max-qty audit pair (xq = max qty), the
    analogue of monthlyqty's usercode_mq/trans_time_mq. We stamp them so our writes
    stay SOFTECH-identifiable.
  • NO items.itemupdt_maxnowqty gate exists (unlike monthlyqty) → the coverage field
    has no per-item eligibility flag; every stocked item is writable.

⚠️ SAFETY — GATED, NO PROD WRITE BY DEFAULT ⚠️
Guarded by settings.COVERAGE_WRITER_ENABLED (default False). With the gate OFF,
push_coverage() only PREPARES + returns the dry-run plan. build_coverage_plan() and
probe_coverage_write() are READ-ONLY / self-restoring. HQ (branchcode 100) is NEVER
targeted — a branch-100 write double-counts SOFTECH's all-branch ordering.

Mirrors the proven apps/purchasing/rate_writer.py structure and reuses its helpers.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.utils import timezone

from apps.purchasing.rate_writer import (
    _lit, _service_usercode, resolve_store, _eligible_branches, _pivot_want,
    _latest_run, WriterDisabled, _READ_CHUNK, _UPDATE_CHUNK,
    _read_conn_for_target,
    _refresh_maxqty, _refresh_maxqty_sql, _expected_maxqty, MAXQTY_DECIMALS,
    # resume after a dropped connection — one shared copy with the rate writer
    _safe_close, _write_surface_with_resume, MAX_WRITE_ATTEMPTS,
    TARGET_NODE, TARGET_HQ, TARGET_BOTH, _VALID_TARGETS,
)

logger = logging.getLogger('elrezeiky.purchasing')

COVERAGE_DECIMALS = 2       # maxnowqtymonths precision (1.5, 2.0, 0.75…)
VERIFY_TOL        = 0.005   # readback tolerance for coverage months
MAXQTY_TOL        = 0.05    # readback / "already correct" tolerance for maxnowqty (1dp)


def coverage_writer_enabled() -> bool:
    return bool(getattr(settings, 'COVERAGE_WRITER_ENABLED', False))


def _write_maxqty_too() -> bool:
    return _refresh_maxqty()


def _round(v, dp) -> float:
    return float(Decimal(str(v or 0)).quantize(Decimal(10) ** -dp, rounding=ROUND_HALF_UP))


def _cov_needs_write(cov, surfaces, write_maxqty, min_delta=0.005) -> bool:
    """
    Should this item be written? Yes when, on ANY targeted server:
      • its coverage differs from `cov`, or
      • we also write the max (COVERAGE_WRITE_MAXQTY) and its stored maxnowqty differs
        from that server's own rate × cov.
    surfaces = [(months, rate, maxqty) or None-if-row-absent, ...] — one per server.
    (Fix 2: before, only coverage was compared, so a re-run after coverage was already
    set skipped every item and maxnowqty never got written.)
    """
    for s in surfaces:
        if s is None:
            return True
        months, rate, maxqty = s
        if abs(cov - months) >= min_delta:
            return True
        if write_maxqty and abs(maxqty - _expected_maxqty(rate, cov)) >= MAXQTY_TOL:
            return True
    return False


# ── 1. BUILD PLAN — READ-ONLY ───────────────────────────────────────────────────
def build_coverage_plan(*, coverage_months, branch_filter=None, item_filter=None,
                        run=None, min_delta=0.005, target=TARGET_BOTH):
    """
    Read the CURRENT stkbal.maxnowqtymonths / monthlyqty / maxnowqty on every targeted
    server for the engine-run items, and return the per-branch list of proposed coverage
    changes. NEVER writes. `coverage_months` is the flat window to set on every item.
    target = 'both' (branch server + server 100, DEFAULT) | 'node' | 'hq'.

    Returns:
      { 'coverage_months', 'run_id', 'target', 'write_maxqty', 'branches':[{branchcode,
        name,store,host,reachable, 'changes':[{itemcode,item_name,old_months,new_months,
        cur_rate,old_maxqty,implied_maxqty, (…_hq twins when target='both'),eligible}],
        'eligible_count','skipped_count','error'?}], 'totals':{…} }
    Primary values = branch server (node/both) or server 100 (hq). implied_maxqty is
    each server's OWN rate × cov (the two servers' rates may differ).
    """
    cov = _round(coverage_months, COVERAGE_DECIMALS)
    if cov <= 0:
        raise ValueError('حدّد عدد أشهر تغطية موجب.')
    target = (target or TARGET_BOTH).lower()
    if target not in _VALID_TARGETS:
        raise ValueError(f'وجهة كتابة غير معروفة: {target}')
    write_maxqty = _write_maxqty_too()

    run = run or _latest_run()
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب (DemandCalculationRun).')

    branches = _eligible_branches(branch_filter)      # excludes HQ 100 by design
    # real stock only — coupons / gifts / non-stockable items never get a ceiling
    want = _pivot_want(run, branches, item_filter, stock_only=True)
    bmap = {b.softech_branch_id: b for b in branches}

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
            cur = _read_current(conn, bc, store, codes)   # itemcode -> (months, rate, maxqty)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # 'both' → also read server 100's copy; an unreachable server 100 makes the
        # branch unreachable for a both-push.
        cur_hq = None
        if target == TARGET_BOTH:
            try:
                from config.sybase import get_sybase_connection
                hconn = get_sybase_connection()
                try:
                    cur_hq = _read_current(hconn, bc, store, codes)
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

        for code, (_, name) in items.items():
            prim = cur.get(code)
            hq = cur_hq.get(code) if cur_hq is not None else None
            surfaces = [prim] if cur_hq is None else [prim, hq]
            if not _cov_needs_write(cov, surfaces, write_maxqty, min_delta):
                entry['skipped_count'] += 1
                tot['skipped'] += 1
                continue
            months, rate, maxqty = prim or (0.0, 0.0, 0.0)
            change = {
                'itemcode': code, 'item_name': name,
                'old_months': months, 'new_months': cov,
                'cur_rate': rate, 'old_maxqty': maxqty,
                'implied_maxqty': _expected_maxqty(rate, cov), 'eligible': True}
            if cur_hq is not None:
                h_months, h_rate, h_maxqty = hq or (0.0, 0.0, 0.0)
                change.update(old_months_hq=h_months, cur_rate_hq=h_rate,
                              old_maxqty_hq=h_maxqty,
                              implied_maxqty_hq=_expected_maxqty(h_rate, cov))
            entry['changes'].append(change)
            entry['eligible_count'] += 1
            tot['eligible'] += 1
        out_branches.append(entry)

    return {'coverage_months': cov, 'run_id': run.id, 'target': target,
            'write_maxqty': write_maxqty, 'branches': out_branches, 'totals': tot}


def _read_current(conn, branchcode, storecode, itemcodes) -> dict:
    """READ (maxnowqtymonths, monthlyqty, maxnowqty) per itemcode, chunked."""
    out = {}
    codes = [c for c in dict.fromkeys(str(x).strip() for x in itemcodes) if c]
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(
                f"SELECT itemcode, maxnowqtymonths, monthlyqty, maxnowqty FROM stkbal "
                f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                [branchcode, storecode, *chunk])
            for r in cur.fetchall():
                out[str(r[0]).strip()] = (
                    float(r[1]) if r[1] is not None else 0.0,
                    float(r[2]) if r[2] is not None else 0.0,
                    float(r[3]) if r[3] is not None else 0.0)
    finally:
        cur.close()
    return out


# ── 2. PUSH — gated; dry-run plan unless gate on + dry_run=False ─────────────────
def push_coverage(*, coverage_months, branch_filter=None, item_filter=None,
                  dry_run=True, run=None, target=TARGET_BOTH):
    """
    Build the plan, then (only when coverage_writer_enabled() AND dry_run=False) apply
    the maxnowqtymonths UPDATEs on each targeted server, with a per-row readback verify
    (a row is verified only when it lands on EVERY server). When
    settings.COVERAGE_WRITE_MAXQTY is on, the same batch also sets maxnowqty = that
    server's own rate × coverage. A dropped connection is resumed (see
    _write_surface_with_resume). Returns the plan enriched per branch with
    'written'/'verified'/'not_confirmed' (+ 'error'/'connection_drops' when a server
    dropped). target = both (default) | node | hq.
    """
    plan = build_coverage_plan(coverage_months=coverage_months, branch_filter=branch_filter,
                               item_filter=item_filter, run=run, target=target)

    if not coverage_writer_enabled() or dry_run:
        plan['mode'] = 'dry_run'
        plan['wrote_to_softech'] = False
        logger.info('[coverage_writer] DRY-RUN (enabled=%s dry_run=%s) — %d eligible across %d branches @ cov=%s target=%s',
                    coverage_writer_enabled(), dry_run, plan['totals']['eligible'],
                    plan['totals']['branches'], plan['coverage_months'], plan['target'])
        return plan

    from apps.branches.models import Branch

    usercode = _service_usercode()
    cov = plan['coverage_months']
    tgt = plan['target']
    also_maxqty = _write_maxqty_too()
    plan['mode'] = 'commit'
    plan['wrote_to_softech'] = True
    plan['wrote_maxqty'] = also_maxqty

    for entry in plan['branches']:
        if not entry['reachable']:
            continue
        eligible = [c for c in entry['changes'] if c['eligible']]
        if not eligible:
            entry['written'] = 0
            continue
        branch = Branch.objects.get(softech_branch_id=entry['branchcode'])
        codes = [str(c['itemcode']).strip() for c in eligible]
        labels = [TARGET_NODE, TARGET_HQ] if tgt == TARGET_BOTH else [tgt]
        ok_by_item = {c: True for c in codes}
        errors = []
        bc, st = entry['branchcode'], entry['store']
        for label in labels:
            landed, errs = _write_surface_with_resume(
                branch, label, codes,
                write_fn=lambda conn, cs: _apply_coverage_updates(
                    conn, bc, st, cs, cov, usercode, also_maxqty),
                verify_fn=lambda conn, cs: _verify_coverage(
                    conn, bc, st, cs, cov, also_maxqty))
            errors += [f'[{label}] {e}' for e in errs]
            for c in codes:
                ok_by_item[c] = ok_by_item[c] and bool(landed.get(c, False))
        if errors:
            entry['error'] = ' | '.join(errors)[:400]
            entry['connection_drops'] = len(errors)
        v = 0
        for c in eligible:
            ok = ok_by_item.get(str(c['itemcode']).strip(), False)
            c['verified'] = ok
            v += 1 if ok else 0
        entry['written'] = len(eligible)
        entry['verified'] = v
        entry['not_confirmed'] = len(eligible) - v
    return plan


def _apply_coverage_updates(conn, branchcode, storecode, codes, cov, usercode, also_maxqty):
    """Write maxnowqtymonths for many items on one server (chunked multi-statement
    UPDATEs). When also_maxqty, each chunk ends with the shared server-side statement
    that sets maxnowqty = that row's own monthlyqty × maxnowqtymonths. Then reads back
    to verify. Returns {itemcode: verified_bool}."""
    bc, st, uc = _lit(str(branchcode)), _lit(str(storecode)), _lit(str(usercode))
    covlit = _lit(cov)
    codes = [str(c).strip() for c in codes]

    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _UPDATE_CHUNK):
            chunk = codes[i:i + _UPDATE_CHUNK]
            stmts = [
                f"UPDATE stkbal SET maxnowqtymonths={covlit}, usercode_xq={uc}, "
                f"trans_time_xq=getdate() WHERE branchcode={bc} AND storecode={st} "
                f"AND itemcode={_lit(code)}"
                for code in chunk
            ]
            if also_maxqty:
                stmts.append(_refresh_maxqty_sql(bc, st, uc, chunk))
            cur.execute('\n'.join(stmts))
    finally:
        _safe_close(cur)
    return _verify_coverage(conn, branchcode, storecode, codes, cov, also_maxqty)


def _verify_coverage(conn, branchcode, storecode, codes, cov, also_maxqty) -> dict:
    """Read back coverage (and the max when written) for the given items.
    Returns {itemcode: verified_bool}; a row that isn't there counts as not verified."""
    codes = [str(c).strip() for c in codes]
    landed = {c: False for c in codes}
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(f"SELECT itemcode, maxnowqtymonths, monthlyqty, maxnowqty FROM stkbal "
                        f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                        [str(branchcode), str(storecode), *chunk])
            for r in cur.fetchall():
                months = float(r[1]) if r[1] is not None else 0.0
                rate = float(r[2]) if r[2] is not None else 0.0
                maxqty = float(r[3]) if r[3] is not None else 0.0
                ok = abs(months - cov) <= VERIFY_TOL
                if ok and also_maxqty:
                    ok = abs(maxqty - _expected_maxqty(rate, months)) < MAXQTY_TOL
                landed[str(r[0]).strip()] = ok
    finally:
        _safe_close(cur)
    return landed


# ── 3. ROLLBACK PROBE — real write then restore, zero residue ───────────────────
def probe_coverage_write(branchcode, itemcode, *, confirm=False, target=TARGET_NODE):
    """
    Prove the maxnowqtymonths write lands (and can be restored) on ONE real row of the
    chosen surface, leaving NO residue: read original → write a marker (original+1.0) →
    read back → restore original → confirm restored. Requires confirm=True AND the gate
    on. target = 'node' (default) | 'hq'. ('both' is not a probe surface — probe each.)
    """
    if not confirm:
        raise ValueError('probe_coverage_write requires confirm=True (it performs a real write).')
    if not coverage_writer_enabled():
        raise WriterDisabled('COVERAGE_WRITER_ENABLED is off — refusing to probe-write.')
    target = (target or TARGET_NODE).lower()
    if target not in (TARGET_NODE, TARGET_HQ):
        raise ValueError("probe target must be 'node' or 'hq'.")

    from apps.branches.models import Branch

    branch = Branch.objects.get(softech_branch_id=str(branchcode))
    store = resolve_store(branch)
    code = str(itemcode).strip()
    usercode = _service_usercode()
    conn = _read_conn_for_target(branch, target)
    cur = conn.cursor()
    try:
        cur.execute("SELECT maxnowqtymonths FROM stkbal "
                    "WHERE branchcode=? AND storecode=? AND itemcode=?",
                    [str(branchcode), store, code])
        row = cur.fetchone()
        if row is None:
            raise ValueError(f'stkbal row not found for branch {branchcode}/{store} item {code}.')
        original = float(row[0]) if row[0] is not None else 0.0
        marker = _round(original + 1.0, COVERAGE_DECIMALS)   # 1dp-distinct from original

        def _set(v):
            cur.execute(
                f"UPDATE stkbal SET maxnowqtymonths={_lit(v)}, usercode_xq={_lit(usercode)}, "
                f"trans_time_xq=getdate() WHERE branchcode={_lit(str(branchcode))} "
                f"AND storecode={_lit(store)} AND itemcode={_lit(code)}")

        def _get():
            cur.execute("SELECT maxnowqtymonths FROM stkbal "
                        "WHERE branchcode=? AND storecode=? AND itemcode=?",
                        [str(branchcode), store, code])
            r = cur.fetchone()
            return float(r[0]) if r and r[0] is not None else 0.0

        _set(marker); wrote = _get()
        _set(original); restored = _get()
        landed = abs(wrote - marker) <= VERIFY_TOL
        clean = abs(restored - original) <= VERIFY_TOL
        logger.info('[coverage_writer] probe branch=%s item=%s original=%s marker=%s wrote=%s restored=%s landed=%s clean=%s',
                    branchcode, code, original, marker, wrote, restored, landed, clean)
        return {'branchcode': str(branchcode), 'store': store, 'itemcode': code,
                'target': target, 'original': original, 'marker': marker, 'wrote_back': wrote,
                'restored': restored, 'landed': landed, 'clean_restore': clean}
    finally:
        cur.close()
        try:
            conn.close()
        except Exception:
            pass


# ── 4. AUTO TOP-UP after each engine run ────────────────────────────────────────
# Every engine run can bring items a branch has never had coverage for (br130 gained
# 39 in one run, 2026-09-27), and rates keep moving, which leaves the stored max stale.
# The top-up brings each server in line with the latest successful run WITHOUT ever
# changing a coverage someone set on purpose:
#   • fill    — item has no coverage (0) → set the default coverage (+ its max);
#   • refresh — item already has a coverage but its stored max ≠ rate × that coverage
#               → refresh the max only, keeping that item's own coverage;
#   • missing — no stkbal row on that server → skipped (we never create stock rows).
# Gated by COVERAGE_WRITER_ENABLED + COVERAGE_AUTO_TOPUP_ENABLED; runs on the
# scheduler (apps/sync/tasks.py _run_coverage_topup) and by hand (topup_coverage cmd).
MAX_TOPUP_TRIES_PER_RUN = 3     # a run left 'partial' (e.g. a branch offline) is retried


def topup_settings() -> dict:
    return {
        'enabled': bool(getattr(settings, 'COVERAGE_AUTO_TOPUP_ENABLED', False)),
        'months': float(getattr(settings, 'COVERAGE_AUTO_TOPUP_MONTHS', 1.5)),
        'target': str(getattr(settings, 'COVERAGE_AUTO_TOPUP_TARGET', TARGET_NODE)).lower(),
    }


def _topup_groups(current, codes, write_maxqty):
    """Split one server's items. current = {itemcode: (months, rate, maxqty)}.
    Returns (fill, refresh, missing) — see the section comment above."""
    fill, refresh, missing = [], [], []
    for c in codes:
        row = current.get(c)
        if row is None:
            missing.append(c)
            continue
        months, rate, maxqty = row
        if months <= 0:
            fill.append(c)
        elif write_maxqty and abs(maxqty - _expected_maxqty(rate, months)) >= MAXQTY_TOL:
            refresh.append(c)
    return fill, refresh, missing


def _apply_maxqty_refresh(conn, branchcode, storecode, codes, usercode):
    """Refresh maxnowqty only (each item keeps its own coverage), then read back."""
    bc, st, uc = _lit(str(branchcode)), _lit(str(storecode)), _lit(str(usercode))
    codes = [str(c).strip() for c in codes]
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _UPDATE_CHUNK):
            cur.execute(_refresh_maxqty_sql(bc, st, uc, codes[i:i + _UPDATE_CHUNK]))
    finally:
        _safe_close(cur)
    return _verify_maxqty(conn, branchcode, storecode, codes)


def _verify_maxqty(conn, branchcode, storecode, codes) -> dict:
    """Read back: max == that row's own rate × its own coverage."""
    codes = [str(c).strip() for c in codes]
    landed = {c: False for c in codes}
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(f"SELECT itemcode, maxnowqtymonths, monthlyqty, maxnowqty FROM stkbal "
                        f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                        [str(branchcode), str(storecode), *chunk])
            for r in cur.fetchall():
                months = float(r[1]) if r[1] is not None else 0.0
                rate = float(r[2]) if r[2] is not None else 0.0
                maxqty = float(r[3]) if r[3] is not None else 0.0
                landed[str(r[0]).strip()] = (
                    months > 0 and abs(maxqty - _expected_maxqty(rate, months)) < MAXQTY_TOL)
    finally:
        _safe_close(cur)
    return landed


def topup_coverage(*, run=None, months=None, target=None, branch_filter=None, dry_run=True):
    """
    Bring every eligible branch (never branch 100) in line with the latest successful
    engine run: fill missing coverage with the default and refresh stale maxes. Writes
    only when dry_run=False AND COVERAGE_WRITER_ENABLED; otherwise just reports what it
    would do. Returns a summary with one entry per (branch, server).
    """
    cfg = topup_settings()
    months = _round(months if months is not None else cfg['months'], COVERAGE_DECIMALS)
    if months <= 0:
        raise ValueError('حدّد عدد أشهر تغطية موجب.')
    target = (target or cfg['target'] or TARGET_NODE).lower()
    if target not in _VALID_TARGETS:
        raise ValueError(f'وجهة كتابة غير معروفة: {target}')
    run = run or _latest_run()
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب (DemandCalculationRun).')

    write_maxqty = _write_maxqty_too()
    commit = (not dry_run) and coverage_writer_enabled()
    usercode = _service_usercode()
    branches = _eligible_branches(branch_filter)          # excludes branch 100
    want = _pivot_want(run, branches, None, stock_only=True)   # real stock only
    labels = [TARGET_NODE, TARGET_HQ] if target == TARGET_BOTH else [target]

    out = {'run_id': run.id, 'months': months, 'target': target, 'write_maxqty': write_maxqty,
           'mode': 'commit' if commit else 'dry_run', 'branches': []}
    for branch in branches:
        bc = branch.softech_branch_id
        store = resolve_store(branch)
        codes = list(want.get(bc, {}).keys())
        for label in labels:
            e = {'branchcode': bc, 'surface': label, 'items': len(codes), 'reachable': True,
                 'fill': 0, 'refresh': 0, 'missing': 0, 'verified': 0, 'not_confirmed': 0}
            conn = None
            try:
                conn = _read_conn_for_target(branch, label)
                current = _read_current(conn, bc, store, codes)
            except Exception as exc:
                e.update(reachable=False, error=str(exc)[:200])
                out['branches'].append(e)
                continue
            finally:
                if conn is not None:
                    _safe_close(conn)

            fill, refresh, missing = _topup_groups(current, codes, write_maxqty)
            e.update(fill=len(fill), refresh=len(refresh), missing=len(missing))
            if commit and (fill or refresh):
                ok, errors = 0, []
                if fill:
                    landed, errs = _write_surface_with_resume(
                        branch, label, fill,
                        write_fn=lambda cn, cs: _apply_coverage_updates(
                            cn, bc, store, cs, months, usercode, write_maxqty),
                        verify_fn=lambda cn, cs: _verify_coverage(
                            cn, bc, store, cs, months, write_maxqty))
                    ok += sum(1 for v in landed.values() if v)
                    errors += errs
                if refresh:
                    landed, errs = _write_surface_with_resume(
                        branch, label, refresh,
                        write_fn=lambda cn, cs: _apply_maxqty_refresh(cn, bc, store, cs, usercode),
                        verify_fn=lambda cn, cs: _verify_maxqty(cn, bc, store, cs))
                    ok += sum(1 for v in landed.values() if v)
                    errors += errs
                e['verified'] = ok
                e['not_confirmed'] = len(fill) + len(refresh) - ok
                if errors:
                    e['error'] = ' | '.join(errors)[:400]
            out['branches'].append(e)

    rows = out['branches']
    out['totals'] = {
        'fill': sum(r['fill'] for r in rows), 'refresh': sum(r['refresh'] for r in rows),
        'missing': sum(r['missing'] for r in rows), 'verified': sum(r['verified'] for r in rows),
        'not_confirmed': sum(r['not_confirmed'] for r in rows),
        'unreachable': sum(1 for r in rows if not r['reachable']),
    }
    t = out['totals']
    out['status'] = ('dry_run' if not commit else
                     'success' if (t['not_confirmed'] == 0 and t['unreachable'] == 0) else 'partial')
    logger.info('[coverage_writer] TOP-UP %s run=%s target=%s fill=%d refresh=%d verified=%d '
                'not_confirmed=%d unreachable=%d', out['status'], run.id, target, t['fill'],
                t['refresh'], t['verified'], t['not_confirmed'], t['unreachable'])
    return out


def persist_topup(result, *, trigger='manual', created_by=None):
    """Audit record of a committed top-up (who/when/what, per branch & server)."""
    from apps.purchasing.models import CoverageTopUp
    t = result['totals']
    return CoverageTopUp.objects.create(
        run_id=result['run_id'], status=result['status'], trigger=trigger,
        months=result['months'], target=result['target'], created_by=created_by,
        filled_count=t['fill'], refreshed_count=t['refresh'], verified_count=t['verified'],
        not_confirmed_count=t['not_confirmed'], unreachable_count=t['unreachable'],
        summary=result['branches'], finished_at=timezone.now())


def topup_due(run) -> bool:
    """Should the scheduler top up after this engine run? Yes until one committed
    top-up fully succeeded; a 'partial' one (e.g. a branch offline) is retried up to
    MAX_TOPUP_TRIES_PER_RUN times."""
    from apps.purchasing.models import CoverageTopUp
    qs = CoverageTopUp.objects.filter(run=run).exclude(status='dry_run')
    if qs.filter(status='success').exists():
        return False
    return qs.count() < MAX_TOPUP_TRIES_PER_RUN


# ── 5. RESET non-stock items (coupons / gifts / price ≤ 0 / non-stockable) ───────
# Coverage now skips these (_real_stock_filter), but pushes before 2026-10-02 gave
# 16 of them coverage + a max (50 rows over both servers). This puts them back to
# their original state (coverage 0, max 0) — ONLY on rows WE stamped (usercode_xq =
# our service usercode), so anything set natively in SOFTECH is never touched.
def _non_stock_codes(run, branches):
    """branchcode -> [itemcodes in the engine run that are NOT real stock]."""
    every = _pivot_want(run, branches, None)
    stock = _pivot_want(run, branches, None, stock_only=True)
    return {bc: [c for c in codes if c not in stock.get(bc, {})] for bc, codes in every.items()}


def _ours_with_ceiling(conn, branchcode, storecode, codes, usercode):
    """Of `codes`, those with coverage or max set AND last stamped by us."""
    codes = [str(c).strip() for c in codes]
    out = []
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(f"SELECT itemcode, maxnowqtymonths, maxnowqty, usercode_xq FROM stkbal "
                        f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                        [str(branchcode), str(storecode), *chunk])
            for r in cur.fetchall():
                months, maxqty = float(r[1] or 0), float(r[2] or 0)
                stamped = str(r[3]).strip() if r[3] is not None else ''
                if (months > 0 or maxqty > 0) and stamped == str(usercode):
                    out.append(str(r[0]).strip())
    finally:
        _safe_close(cur)
    return out


def _apply_reset(conn, branchcode, storecode, codes, usercode):
    bc, st, uc = _lit(str(branchcode)), _lit(str(storecode)), _lit(str(usercode))
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _UPDATE_CHUNK):
            inlist = ','.join(_lit(c) for c in codes[i:i + _UPDATE_CHUNK])
            cur.execute(f"UPDATE stkbal SET maxnowqtymonths=0, maxnowqty=0, usercode_xq={uc}, "
                        f"trans_time_xq=getdate() WHERE branchcode={bc} AND storecode={st} "
                        f"AND itemcode IN ({inlist})")
    finally:
        _safe_close(cur)
    return _verify_reset(conn, branchcode, storecode, codes)


def _verify_reset(conn, branchcode, storecode, codes) -> dict:
    landed = {c: False for c in codes}
    cur = conn.cursor()
    try:
        for i in range(0, len(codes), _READ_CHUNK):
            chunk = codes[i:i + _READ_CHUNK]
            ph = ','.join('?' for _ in chunk)
            cur.execute(f"SELECT itemcode, maxnowqtymonths, maxnowqty FROM stkbal "
                        f"WHERE branchcode=? AND storecode=? AND itemcode IN ({ph})",
                        [str(branchcode), str(storecode), *chunk])
            for r in cur.fetchall():
                landed[str(r[0]).strip()] = float(r[1] or 0) == 0 and float(r[2] or 0) == 0
    finally:
        _safe_close(cur)
    return landed


def reset_non_stock(*, branch_filter=None, target=TARGET_BOTH, dry_run=True, run=None):
    """Reset coverage + max to 0 on non-stock items we wrote earlier (see section note).
    Writes only when dry_run=False AND COVERAGE_WRITER_ENABLED. Returns one entry per
    (branch, server): candidates / verified / not_confirmed / reachable / error."""
    target = (target or TARGET_BOTH).lower()
    if target not in _VALID_TARGETS:
        raise ValueError(f'وجهة كتابة غير معروفة: {target}')
    run = run or _latest_run()
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب (DemandCalculationRun).')
    commit = (not dry_run) and coverage_writer_enabled()
    usercode = _service_usercode()
    branches = _eligible_branches(branch_filter)              # never branch 100
    excluded = _non_stock_codes(run, branches)
    labels = [TARGET_NODE, TARGET_HQ] if target == TARGET_BOTH else [target]

    out = {'run_id': run.id, 'target': target, 'mode': 'commit' if commit else 'dry_run',
           'branches': []}
    for branch in branches:
        bc, store = branch.softech_branch_id, resolve_store(branch)
        excl = excluded.get(bc, [])
        if not excl:
            continue
        for label in labels:
            e = {'branchcode': bc, 'surface': label, 'reachable': True,
                 'candidates': 0, 'verified': 0, 'not_confirmed': 0, 'codes': []}
            conn = None
            try:
                conn = _read_conn_for_target(branch, label)
                ours = _ours_with_ceiling(conn, bc, store, excl, usercode)
            except Exception as exc:
                e.update(reachable=False, error=str(exc)[:200])
                out['branches'].append(e)
                continue
            finally:
                if conn is not None:
                    _safe_close(conn)
            e.update(candidates=len(ours), codes=ours)
            if commit and ours:
                landed, errs = _write_surface_with_resume(
                    branch, label, ours,
                    write_fn=lambda cn, cs: _apply_reset(cn, bc, store, cs, usercode),
                    verify_fn=lambda cn, cs: _verify_reset(cn, bc, store, cs))
                e['verified'] = sum(1 for v in landed.values() if v)
                e['not_confirmed'] = len(ours) - e['verified']
                if errs:
                    e['error'] = ' | '.join(errs)[:300]
            out['branches'].append(e)
    logger.info('[coverage_writer] RESET non-stock %s target=%s candidates=%d verified=%d',
                out['mode'], target, sum(r['candidates'] for r in out['branches']),
                sum(r['verified'] for r in out['branches']))
    return out
