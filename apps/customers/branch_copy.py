"""
apps/customers/branch_copy.py — copy a customer's HQ account flags onto a branch node's own copy
(B7 step 3 / Option B). Owner approved 2026-10-08: "our system writes them, audited and read back,
starting with 05HD999 on branch 140 only".

Why: the branch till reads ONLY its node's localcustomers row. A change made in SOFTECH's customer
screen at HQ (points off, file closed, deceased, entity lock, special discount) never reaches the node
(trace of 05HD999: HQ picpoints=0 / picdiscounts=1, branch 140 still 1 / 0). So the till keeps awarding
points or serving a blocked customer.

What it writes (one UPDATE on the node, nothing else):
  phcodestatus, piclock, picdied, picpoints, picdiscounts  ← HQ's values
  usercode, trans_time                                     ← HQ's values (a repair re-delivers HQ's
                                                              edit; the original editor is preserved,
                                                              exactly like discount_approvals.replication)
  table_dumped is NOT touched (the row is not re-shipped). Nodes have no UPDATE trigger on the table.
Safety:
  * gate CUSTOMER_BRANCH_COPY_WRITE_ENABLED (default False) — otherwise dry run only;
  * at most CUSTOMER_BRANCH_COPY_MAX_PER_RUN codes per run (default 1 — the pilot);
  * optimistic: the UPDATE matches the node's values as just read, so a concurrent change is not
    overwritten (→ 'conflict');
  * idempotent: a copy already equal to HQ is 'no_change' and not written;
  * read back and compared field by field; every attempt is a BranchCopyWrite row + an AuditLog entry.
Points BALANCES are not touched here (separate, pending the reset method).
"""
import logging

from django.conf import settings

logger = logging.getLogger('elrezeiky.customers')

DB = 'SOFTECHDB9.dbo'
FLAGS = ('phcodestatus', 'piclock', 'picdied', 'picpoints', 'picdiscounts')
EDITOR = ('usercode', 'trans_time')
_TEXT = {'phcodestatus', 'usercode'}


def write_enabled():
    return bool(getattr(settings, 'CUSTOMER_BRANCH_COPY_WRITE_ENABLED', False))


def max_per_run():
    return int(getattr(settings, 'CUSTOMER_BRANCH_COPY_MAX_PER_RUN', 1))


def _norm(col, v):
    if col in _TEXT:
        return str(v).strip() if v is not None else ''
    if col == 'trans_time':
        return v
    return int(v or 0)


def read_row(conn, pic):
    cur = conn.cursor()
    cur.execute(f'SELECT {", ".join(FLAGS + EDITOR)} FROM {DB}.localcustomers WHERE phcode = ?', [pic])
    r = cur.fetchall()
    if not r:
        return None
    return {c: _norm(c, v) for c, v in zip(FLAGS + EDITOR, r[0])}


def _param(col, v):
    """jConnect rejects a Python datetime parameter → send trans_time as text (convert() in the SQL)."""
    if col == 'trans_time':
        return v.strftime('%Y-%m-%d %H:%M:%S.') + f'{v.microsecond // 1000:03d}' if v else None
    return v


def _json(row):
    return {k: (v.isoformat(sep=' ') if hasattr(v, 'isoformat') else v) for k, v in (row or {}).items()}


def diff(hq, node, fields=FLAGS):
    """Flags (of `fields`) whose node value differs from HQ."""
    return [c for c in fields if hq[c] != node[c]]


# Batch mode copies only flags that make the branch STRICTER (owner 2026-10-09: "build it and run it in
# batches"). Special discount is a pricing change → only with include_discount.
TIGHTEN_FIELDS = ('phcodestatus', 'piclock', 'picdied', 'picpoints')
_BLOCKED = {'0', '5'}


def loosening(hq, node, fields):
    """Fields where copying HQ would RELAX the branch copy (unblock, unlock, re-enroll in points)."""
    out = []
    for c in fields:
        h, n = hq[c], node[c]
        if h == n:
            continue
        if c == 'phcodestatus' and n in _BLOCKED and h not in _BLOCKED:
            out.append(c)
        elif c in ('piclock', 'picdied') and n and not h:
            out.append(c)
        elif c == 'picpoints' and not n and h:
            out.append(c)
    return out


def _branch(code):
    from apps.branches.models import Branch
    b = Branch.objects.filter(softech_branch_id=str(code)).first()
    if not b or not b.db_host:
        raise ValueError(f'branch {code}: no SOFTECH node configured')
    if str(code) == '100':
        raise ValueError('HQ is the source, not a branch copy')
    return b


def copy_one(pic, branch_code, *, user=None, commit=False, hq_conn=None, node_conn=None,
             fields=FLAGS, only_tighten=False, absent_ok=False):
    """Plan (and with commit=True + the gate on, write) one code on one branch. Returns the
    BranchCopyWrite row. `fields` limits which flags are copied; only_tighten skips the code when a
    copy would relax the branch (batch mode)."""
    from config.sybase import get_branch_connection, get_sybase_connection
    from .models import BranchCopyWrite as W

    pic = (pic or '').strip()
    rec = W(pic=pic, node_branch=str(branch_code), requested_by=user)
    own_hq, own_node = hq_conn is None, node_conn is None
    try:
        hq_conn = hq_conn or get_sybase_connection()
        hq = read_row(hq_conn, pic)
        if hq is None:
            raise ValueError(f'{pic} not found at HQ')
        if node_conn is None:
            b = _branch(branch_code)
            node_conn = get_branch_connection(b.db_host, b.db_port or 5000, 'SOFTECHDB9')
        node = read_row(node_conn, pic)
        if node is None and absent_ok:              # the branch never held this customer → nothing to fix
            rec.status, rec.error = W.STATUS_SKIPPED, 'not held on this branch'
            rec.target = _json(hq)
            rec.save()
            return rec
        if node is None:
            raise ValueError(f'{pic} has no copy on branch {branch_code}')
        rec.before, rec.target = _json(node), _json(hq)
        changed = diff(hq, node, fields)
        loose = loosening(hq, node, fields) if only_tighten else []
        if loose:
            rec.status = W.STATUS_SKIPPED
            rec.error = 'copy would relax the branch (' + ', '.join(loose) + ') — review, not batch'
        elif not changed:
            rec.status, rec.after = W.STATUS_NO_CHANGE, _json(node)
        elif not (commit and write_enabled()):
            rec.status = W.STATUS_DRY_RUN
            if commit:
                rec.error = 'CUSTOMER_BRANCH_COPY_WRITE_ENABLED is off — nothing written'
        else:
            sets = list(changed) + list(EDITOR)
            where = ' AND '.join(
                f"isnull({c}, '') = ?" if c in _TEXT else f'isnull({c}, 0) = ?' for c in FLAGS)
            set_sql = ', '.join('trans_time = convert(datetime, ?)' if c == 'trans_time' else f'{c} = ?' for c in sets)
            cur = node_conn.cursor()
            cur.execute(f'UPDATE {DB}.localcustomers SET {set_sql} WHERE phcode = ? AND {where}',
                        [_param(c, hq[c]) for c in sets] + [pic] + [node[c] for c in FLAGS])
            after = read_row(node_conn, pic)
            rec.after = _json(after)
            if after and not diff(hq, after, fields):
                rec.status = W.STATUS_VERIFIED
            elif after and not diff(node, after):
                rec.status = W.STATUS_CONFLICT
                rec.error = 'branch copy changed between read and write — not overwritten'
            else:
                rec.status = W.STATUS_FAILED
                rec.error = 'read-back does not match HQ: ' + ', '.join(diff(hq, after or node, fields))
    except Exception as exc:
        rec.status, rec.error = W.STATUS_FAILED, str(exc)[:500]
        logger.warning('[branch_copy] %s@%s failed: %s', pic, branch_code, exc)
    finally:
        if own_node and node_conn is not None:
            node_conn.close()
        if own_hq and hq_conn is not None:
            hq_conn.close()
    rec.save()
    if rec.status in (W.STATUS_VERIFIED, W.STATUS_CONFLICT, W.STATUS_FAILED) and commit:
        _audit(rec, user)
    if rec.status == W.STATUS_VERIFIED:
        _resolve_drift(rec, fields)
    return rec


def _audit(rec, user):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log('customer_branch_copy_written', user=user, obj=rec, old_data=rec.before, new_data=rec.after,
                     note=f'{rec.pic} → فرع {rec.node_branch}: {rec.get_status_display()}'[:255],
                     extra={'target': rec.target, 'error': rec.error})
    except Exception:
        logger.exception('[branch_copy] audit failed')


_DRIFT_COLUMNS = {'status': ('phcodestatus', 'picdied'), 'lock': ('piclock',), 'points': ('picpoints',)}


def _resolve_drift(rec, fields=FLAGS):
    """Close the open drift rows whose flags were copied (a partial copy leaves the others open)."""
    from django.utils import timezone
    from .models import CustomerStatusDrift
    done = [f for f, cols in _DRIFT_COLUMNS.items() if all(c in fields for c in cols)]
    CustomerStatusDrift.objects.filter(pic=rec.pic, node_branch=rec.node_branch, field__in=done,
                                       resolved_at__isnull=True).update(resolved_at=timezone.now())


def run(pics, branch_code, *, user=None, commit=False):
    pics = [p.strip() for p in pics if p and p.strip()]
    if commit and len(pics) > max_per_run():
        raise ValueError(f'{len(pics)} codes > CUSTOMER_BRANCH_COPY_MAX_PER_RUN ({max_per_run()})')
    return [copy_one(p, branch_code, user=user, commit=commit) for p in pics]


# ── batch mode (owner 2026-10-09) ───────────────────────────────────────────────────────────────
def batch_max():
    return int(getattr(settings, 'CUSTOMER_BRANCH_COPY_BATCH_MAX', 50))


def held_codes():
    """Codes never copied in batch (owner decision pending), e.g. 07HD11663."""
    raw = getattr(settings, 'CUSTOMER_BRANCH_COPY_HOLD', '07HD11663')
    return {c.strip() for c in str(raw).split(',') if c.strip()}


def batch_candidates(branch_code, limit):
    """Codes with an open HQ-stricter difference on this branch, and NO open branch-stricter / other
    difference there (copying those could relax the branch). Oldest difference first."""
    from .models import CustomerStatusDrift as D
    open_rows = D.objects.filter(node_branch=str(branch_code), resolved_at__isnull=True)
    risky = set(open_rows.exclude(direction=D.HQ_STRICTER).values_list('pic', flat=True)) | held_codes()
    pics, seen = [], set()
    for pic in open_rows.filter(direction=D.HQ_STRICTER).order_by('first_seen', 'pic').values_list('pic', flat=True):
        if pic in seen or pic in risky:
            continue
        seen.add(pic)
        pics.append(pic)
        if len(pics) >= limit:
            break
    return pics


def run_batch(branch_code, *, user=None, commit=False, limit=None, include_discount=False):
    """Copy the tightening flags for up to `limit` drift candidates on one branch, over one HQ and one
    branch connection. Stops at the first conflict / failure when writing."""
    from config.sybase import get_branch_connection, get_sybase_connection
    from .models import BranchCopyWrite as W
    limit = min(int(limit or batch_max()), batch_max())
    pics = batch_candidates(branch_code, limit)
    fields = TIGHTEN_FIELDS + (('picdiscounts',) if include_discount else ())
    recs = []
    if not pics:
        return recs
    b = _branch(branch_code)
    hq_conn = get_sybase_connection()
    node_conn = get_branch_connection(b.db_host, b.db_port or 5000, 'SOFTECHDB9')
    try:
        for pic in pics:
            r = copy_one(pic, branch_code, user=user, commit=commit, hq_conn=hq_conn, node_conn=node_conn,
                         fields=fields, only_tighten=True)
            recs.append(r)
            if commit and r.status in (W.STATUS_CONFLICT, W.STATUS_FAILED):
                break
    finally:
        node_conn.close()
        hq_conn.close()
    return recs


# ── removed customers → branch copies (owner 2026-10-10: removed customers get special discount) ────────
REMOVAL_FIELDS = ('picpoints', 'picdiscounts')


def removal_candidates(branch_code, limit):
    """Customers removed from points at HQ (PointsRemoval verified / no_change with discount 1) that have no
    settled copy on this branch since their latest removal."""
    from django.db.models import Max
    from .models import BranchCopyWrite as W, PointsRemoval as R
    latest = dict(R.objects.filter(status__in=(R.STATUS_VERIFIED, R.STATUS_NO_CHANGE), discount_after=1)
                  .values('pic').annotate(t=Max('created_at')).values_list('pic', 't'))
    settled = {}
    for pic, t in (W.objects.filter(node_branch=str(branch_code), pic__in=list(latest),
                                    status__in=(W.STATUS_VERIFIED, W.STATUS_NO_CHANGE, W.STATUS_SKIPPED))
                   .values_list('pic', 'created_at')):
        settled[pic] = max(settled.get(pic, t), t)
    out = [p for p in sorted(latest) if p not in held_codes() and not (p in settled and settled[p] >= latest[p])]
    return out[:limit]


def run_removals_batch(branch_code, *, user=None, commit=False, limit=None):
    """Copy points-off + special discount from HQ onto this branch's copy for removed customers. A code the
    branch does not hold is 'skipped' (not a failure); a code whose copy would re-enroll points is skipped
    for review; stops at the first conflict / failure."""
    from config.sybase import get_branch_connection, get_sybase_connection
    from .models import BranchCopyWrite as W
    limit = min(int(limit or batch_max()), batch_max())
    pics = removal_candidates(branch_code, limit)
    recs = []
    if not pics:
        return recs
    b = _branch(branch_code)
    hq_conn = get_sybase_connection()
    node_conn = get_branch_connection(b.db_host, b.db_port or 5000, 'SOFTECHDB9')
    try:
        for pic in pics:
            r = copy_one(pic, branch_code, user=user, commit=commit, hq_conn=hq_conn, node_conn=node_conn,
                         fields=REMOVAL_FIELDS, only_tighten=True, absent_ok=True)
            recs.append(r)
            if commit and r.status in (W.STATUS_CONFLICT, W.STATUS_FAILED):
                break
    finally:
        node_conn.close()
        hq_conn.close()
    return recs
