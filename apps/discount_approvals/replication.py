"""
Replication audit & repair engine.

SOFTECH replicates HQ item-master changes to each branch by polling
items.itemlastupdate and copying the full row (incl. posdiscp). A branch
that is offline during a cycle silently misses that change until the item
is touched again — leaving stale prices/discounts at that branch.

This module:
  • check_item()      — live HQ↔branch status for ONE item (per-request badge)
  • scan_recent()     — audit EVERY item changed in the last N days across all
                        branches, regardless of whether the change came from our
                        Approval Module or a direct SOFTECH "Items Master" edit
  • force_replication — re-stamp HQ itemlastupdate (native re-pull next cycle)
                        and/or push the row directly to the stale branch NOW
  • resolve_source()  — who made the HQ change (usercode → name) and whether it
                        came through our module or directly in SOFTECH

All branch reads/writes use the same credentials and code paths the ERP uses;
no SOFTECH schema is modified.
"""
import logging
from decimal import Decimal
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('elrezeiky.discount_approvals')

# Price/discount columns we compare and (for direct push) write
PRICE_COLS = [
    'itemsaleprice', 'unitsaleprice', 'itemsaleprice_tax',
    'pharmacydiscp', 'additionaldiscp', 'specialdiscp', 'posdiscp',
]

# Tolerance (seconds) when comparing HQ vs branch itemlastupdate
LASTUPDATE_TOLERANCE_SEC = 2


# ── helpers ────────────────────────────────────────────────────────────────

def _operational_branches():
    from apps.branches.models import Branch
    return list(
        Branch.objects.filter(is_operational=True, db_host__isnull=False)
        .exclude(softech_branch_id='100').exclude(db_host='')
    )


def _usercode_name_map(usercodes):
    """Resolve SOFTECH usercode → operator name via users.userid."""
    from config.sybase import get_sybase_connection
    names = {}
    codes = [c for c in {str(u or '').strip() for u in usercodes} if c]
    if not codes:
        return names
    try:
        conn = get_sybase_connection()
        cur = conn.cursor()
        # chunked IN to avoid oversized statements
        for i in range(0, len(codes), 200):
            chunk = codes[i:i + 200]
            placeholders = ','.join('?' for _ in chunk)
            cur.execute(
                f"SELECT usercode, userid FROM SOFTECHDB9.dbo.users "
                f"WHERE usercode IN ({placeholders})",
                chunk,
            )
            for r in cur.fetchall():
                names[str(r[0]).strip()] = str(r[1] or '').strip()
        conn.close()
    except Exception as exc:
        logger.warning(f"[replication] usercode name lookup failed: {exc}")
    return names


def _module_usercodes():
    """Usercodes that represent OUR module (service code + every linked approver)."""
    from django.conf import settings
    from apps.users.models import StaffProfile
    codes = {str(getattr(settings, 'ERP_SERVICE_USERCODE', '') or '').strip()}
    for sid in StaffProfile.objects.exclude(softech_user_id='').values_list('softech_user_id', flat=True):
        codes.add(str(sid).strip())
    codes.discard('')
    return codes


def _ts_equal(a, b):
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= LASTUPDATE_TOLERANCE_SEC


# How close (seconds) the item's itemlastupdate must be to an executed module
# request's erp_executed_at to attribute the change to the module. Both writes
# happen in the same moment, so this only needs to absorb app↔DB clock skew.
MODULE_MATCH_WINDOW_SEC = 600


def resolve_source(usercode, softech_id=None, name_map=None, hq_lastupdate=None):
    """
    Determine whether the LATEST change to an item came through this module or
    was a direct SOFTECH (Items Master) edit, and by whom.

    Because module approvals now stamp the approver's OWN real usercode (same
    identity space as a manual SOFTECH edit), the usercode alone cannot tell the
    two apart. The reliable signal is our own audit table: the module stamps
    items.itemlastupdate = GETDATE() at execution time, so if an EXECUTED
    ItemPriceChangeRequest for this item has erp_executed_at within
    MODULE_MATCH_WINDOW_SEC of the item's current itemlastupdate, the latest
    change was ours.

    Returns (source_channel, source_label):
      source_channel: 'module' | 'direct'
      source_label:   e.g. 'وحدة الموافقات (BASSEM)' or 'MINA ADEL'
    """
    uc = str(usercode or '').strip()
    name_map = name_map if name_map is not None else _usercode_name_map([uc])
    name = name_map.get(uc, '') or uc

    if softech_id:
        from datetime import timedelta
        from .models import ItemPriceChangeRequest
        qs = ItemPriceChangeRequest.objects.filter(
            item__softech_id=softech_id,
            status=ItemPriceChangeRequest.STATUS_EXECUTED,
            erp_executed_at__isnull=False,
        )
        if hq_lastupdate is not None:
            lo = hq_lastupdate - timedelta(seconds=MODULE_MATCH_WINDOW_SEC)
            hi = hq_lastupdate + timedelta(seconds=MODULE_MATCH_WINDOW_SEC)
            qs = qs.filter(erp_executed_at__gte=lo, erp_executed_at__lte=hi)
        if qs.exists():
            return 'module', f'وحدة الموافقات ({name})'
    return 'direct', name


# ── single-item check (per-request replication badge) ───────────────────────

def check_item(softech_id):
    """
    Live HQ↔branch status for one item.
    Returns dict: { hq, source, branches: [ {code,name,status,branch_lastupdate,diffs} ] }
    status per branch: 'replicated' | 'stale' | 'unreachable'
    """
    from config.sybase import get_sybase_connection, get_branch_connection

    cols = 'itemname, itemlastupdate, usercode, ' + ', '.join(PRICE_COLS)

    conn = get_sybase_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT {cols} FROM SOFTECHDB9.dbo.items WHERE itemcode = ?",
        [softech_id],
    )
    hq = cur.fetchone()
    conn.close()
    if not hq:
        return {'error': 'item_not_found'}

    hq_name   = hq[0]
    hq_lastup = hq[1]
    hq_user   = str(hq[2] or '').strip()
    hq_prices = {PRICE_COLS[i]: hq[3 + i] for i in range(len(PRICE_COLS))}

    name_map = _usercode_name_map([hq_user])
    src_channel, src_label = resolve_source(hq_user, softech_id, name_map, hq_lastupdate=hq_lastup)

    branches = []
    for b in _operational_branches():
        entry = {'code': b.softech_branch_id, 'name': b.name}
        try:
            bc = get_branch_connection(b.db_host, b.db_port or 5000)
            cur = bc.cursor()
            cur.execute(
                f"SELECT itemlastupdate, {', '.join(PRICE_COLS)} FROM items WHERE itemcode = ?",
                [softech_id],
            )
            r = cur.fetchone()
            bc.close()
            if not r:
                entry.update(status='stale', branch_lastupdate=None,
                             diffs={'_missing': True})
            else:
                br_lastup = r[0]
                diffs = {}
                for i, col in enumerate(PRICE_COLS):
                    hv = float(hq_prices[col] or 0)
                    bv = float(r[1 + i] or 0)
                    if abs(hv - bv) > 0.01:
                        diffs[col] = {'hq': hv, 'branch': bv}
                replicated = _ts_equal(hq_lastup, br_lastup) and not diffs
                entry.update(
                    status='replicated' if replicated else 'stale',
                    branch_lastupdate=br_lastup,
                    diffs=diffs,
                )
        except Exception as exc:
            entry.update(status='unreachable', branch_lastupdate=None,
                         diffs={}, error=str(exc)[:80])
        branches.append(entry)

    return {
        'softech_id': softech_id,
        'hq': {
            'name': hq_name, 'itemlastupdate': hq_lastup,
            'usercode': hq_user, 'prices': {k: float(v or 0) for k, v in hq_prices.items()},
        },
        'source': {'channel': src_channel, 'label': src_label, 'usercode': hq_user},
        'branches': branches,
        'fully_replicated': all(b['status'] == 'replicated' for b in branches),
    }


# ── bulk scan over a time window (covers ALL edits incl. direct SOFTECH) ─────

def scan_recent(days=30, persist=True, triggered_by=None, is_scheduled=False):
    """
    Audit item replication HQ↔branches. Detects gaps from BOTH module changes
    and direct SOFTECH Items-Master edits.

    days=N    → only items changed on HQ in the last N days (fast, default).
    days=None → FULL-CATALOG deep audit of every active item (#6), to catch
                long-standing silent divergence. Heavier — run weekly.

    Returns the ReplicationScan (if persist) or a summary dict.
    """
    from config.sybase import get_sybase_connection, get_branch_connection
    from .models import ReplicationScan, ReplicationGap

    full_catalog = days is None

    scan = None
    if persist:
        scan = ReplicationScan.objects.create(
            days_window=(0 if full_catalog else days),
            triggered_by=triggered_by, is_scheduled=is_scheduled,
        )

    try:
        branches = _operational_branches()
        branch_names = {b.softech_branch_id: b.name for b in branches}

        # 1) HQ rows — full catalog or only those changed in the window
        conn = get_sybase_connection()
        cur = conn.cursor()
        cols = 'itemcode, itemname, itemlastupdate, usercode, ' + ', '.join(PRICE_COLS)
        if full_catalog:
            cur.execute(
                f"SELECT {cols} FROM SOFTECHDB9.dbo.items "
                f"WHERE itemnomoreuse != '1' AND itemarchive = 0"
            )
        else:
            cutoff = timezone.now() - timedelta(days=days)
            cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')  # jConnect can't bind datetime
            cur.execute(
                f"SELECT {cols} FROM SOFTECHDB9.dbo.items "
                f"WHERE itemlastupdate >= convert(datetime, '{cutoff_str}') "
                f"ORDER BY itemlastupdate DESC"
            )
        hq_rows = cur.fetchall()
        conn.close()

        hq = {}
        for r in hq_rows:
            code = str(r[0]).strip()
            hq[code] = {
                'name': r[1], 'lastup': r[2], 'usercode': str(r[3] or '').strip(),
                'prices': {PRICE_COLS[i]: float(r[4 + i] or 0) for i in range(len(PRICE_COLS))},
            }
        changed_codes = list(hq.keys())

        # Resolve source names once
        name_map = _usercode_name_map([v['usercode'] for v in hq.values()])

        # 2) For each branch, pull lastupdate+prices for the changed items (chunked)
        gaps = []
        branches_down = []
        for b in branches:
            bmap = {}
            reachable = True
            try:
                bc = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = bc.cursor()
                for i in range(0, len(changed_codes), 400):
                    chunk = changed_codes[i:i + 400]
                    ph = ','.join('?' for _ in chunk)
                    cur.execute(
                        f"SELECT itemcode, itemlastupdate, {', '.join(PRICE_COLS)} "
                        f"FROM items WHERE itemcode IN ({ph})",
                        chunk,
                    )
                    for r in cur.fetchall():
                        bmap[str(r[0]).strip()] = (
                            r[1], [float(r[2 + j] or 0) for j in range(len(PRICE_COLS))]
                        )
                bc.close()
            except Exception as exc:
                reachable = False
                branches_down.append(b.softech_branch_id)
                logger.warning(f"[replication] scan: BR{b.softech_branch_id} unreachable: {exc}")

            for code, h in hq.items():
                if not reachable:
                    gaps.append((code, h, b, 'unreachable', None, {}))
                    continue
                row = bmap.get(code)
                if row is None:
                    gaps.append((code, h, b, 'stale', None, {'_missing': True}))
                    continue
                br_lastup, br_prices = row
                diffs = {}
                for j, col in enumerate(PRICE_COLS):
                    if abs(h['prices'][col] - br_prices[j]) > 0.01:
                        diffs[col] = {'hq': h['prices'][col], 'branch': br_prices[j]}
                if not (_ts_equal(h['lastup'], br_lastup) and not diffs):
                    gaps.append((code, h, b, 'stale', br_lastup, diffs))

        # 3) Persist
        items_with_gaps = len({g[0] for g in gaps})
        if persist:
            bulk = []
            for code, h, b, status, br_lastup, diffs in gaps:
                channel, label = resolve_source(h['usercode'], code, name_map, hq_lastupdate=h['lastup'])
                bulk.append(ReplicationGap(
                    scan=scan,
                    item_softech_id=code, item_name=(h['name'] or '')[:120],
                    branch_code=b.softech_branch_id, branch_name=(branch_names.get(b.softech_branch_id, '') or '')[:120],
                    hq_itemlastupdate=h['lastup'], branch_itemlastupdate=br_lastup,
                    hq_usercode=h['usercode'], source_user=label[:120], source_channel=channel,
                    diff_summary=diffs, status=status,
                ))
            ReplicationGap.objects.bulk_create(bulk, batch_size=500)

            scan.finished_at     = timezone.now()
            scan.status          = ReplicationScan.STATUS_DONE
            scan.items_checked   = len(changed_codes)
            scan.items_ok        = len(changed_codes) - items_with_gaps
            scan.items_with_gaps = items_with_gaps
            scan.branches_down   = branches_down
            scan.save()
            return scan

        return {
            'items_checked': len(changed_codes),
            'items_with_gaps': items_with_gaps,
            'gaps': len(gaps),
            'branches_down': branches_down,
        }

    except Exception as exc:
        logger.error(f"[replication] scan failed: {exc}")
        if persist and scan:
            scan.status = ReplicationScan.STATUS_FAILED
            scan.error = str(exc)[:500]
            scan.finished_at = timezone.now()
            scan.save()
        raise


# ── force re-replication (catch a branch that was down) ──────────────────────

def force_replication(softech_id, erp_usercode=None, mode='restamp', target_branches=None):
    """
    Force a missed change to reach branches.

    A repair is NOT a new edit — it just re-delivers an existing change to a
    branch that missed it. So we PRESERVE the item's original editor
    (items.usercode is never overwritten); only itemlastupdate is bumped to
    re-trigger the native pull. This keeps source attribution correct (the
    real person who made the change stays the author) and means no fabricated
    service user is ever needed. `erp_usercode` is accepted for backward
    compatibility but ignored.

    mode:
      'restamp' — (DEFAULT, reliable) bump HQ items.itemlastupdate=GETDATE() so the
                  native SSB poller re-pulls the FULL row to ALL branches on its next
                  cycle (~30 min). Works even for branches whose local trigger reverts
                  direct writes, and catches a branch that was down once it's back.
      'push'    — best-effort: write the HQ price row directly to branches NOW,
                  preserving the original usercode. Some branches' local triggers
                  revert direct writes — readback reports 'reverted' honestly.
      'both'    — push immediately (fast path) AND restamp (guaranteed next cycle).

    target_branches: list of branchcodes to push to (None = all).
    Returns dict {restamped: bool, pushed: {branchcode: 'ok'|'reverted'|'error..'}}
    """
    from config.sybase import get_sybase_connection, get_branch_connection

    result = {'restamped': False, 'pushed': {}}

    # Read authoritative HQ row — including the ORIGINAL editor to preserve it
    conn = get_sybase_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT itemlastupdate, usercode, {', '.join(PRICE_COLS)} FROM SOFTECHDB9.dbo.items WHERE itemcode = ?",
        [softech_id],
    )
    hq = cur.fetchone()
    if not hq:
        conn.close()
        return {'error': 'item_not_found'}
    original_usercode = str(hq[1] or '').strip()
    hq_prices = {PRICE_COLS[i]: float(hq[2 + i] or 0) for i in range(len(PRICE_COLS))}

    # restamp — bump itemlastupdate ONLY; do not touch usercode (preserve author)
    if mode in ('restamp', 'both'):
        try:
            cur.execute(
                "UPDATE SOFTECHDB9.dbo.items SET itemlastupdate = GETDATE() WHERE itemcode = ?",
                [softech_id],
            )
            result['restamped'] = True
        except Exception as exc:
            result['restamp_error'] = str(exc)[:120]
    conn.close()

    # push directly to branches — preserve the original editor's usercode
    if mode in ('push', 'both'):
        branches = _operational_branches()
        if target_branches:
            tset = {str(x) for x in target_branches}
            branches = [b for b in branches if b.softech_branch_id in tset]

        set_clause = ', '.join(f"{c} = ?" for c in PRICE_COLS)
        params_base = [hq_prices[c] for c in PRICE_COLS] + [original_usercode]
        sql = f"UPDATE items SET {set_clause}, usercode = ? WHERE itemcode = ?"

        for b in branches:
            try:
                bc = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = bc.cursor()
                cur.execute(sql, params_base + [softech_id])
                # readback verify ALL pushed columns landed (a branch trigger may
                # revert direct writes — report that honestly so restamp is used)
                cur.execute(
                    f"SELECT {', '.join(PRICE_COLS)} FROM items WHERE itemcode = ?",
                    [softech_id],
                )
                rb = cur.fetchone()
                bc.close()
                if rb is None:
                    result['pushed'][b.softech_branch_id] = 'missing'
                else:
                    mism = [
                        PRICE_COLS[i] for i in range(len(PRICE_COLS))
                        if abs(float(rb[i] or 0) - hq_prices[PRICE_COLS[i]]) > 0.01
                    ]
                    result['pushed'][b.softech_branch_id] = 'ok' if not mism else f'reverted:{",".join(mism)}'
            except Exception as exc:
                result['pushed'][b.softech_branch_id] = f'error: {str(exc)[:60]}'

    return result
