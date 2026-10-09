"""
apps/customers/points_removal.py — remove customers from the points system AT HQ (B7 Option B).

Owner 2026-10-08: the customers reset in 2022–2024 (mostly by user 19, Bassem Halim) "don't deserve to get
vouchers/coupons and they should be eliminated from the point system"; Option B approved, and "clear the
re-earned balance → yes". Probe findings (doc 27): 2,600 of 3,146 are still enrolled at HQ, 2,110 have
earned 1.71 M points again, and coupons are still issued against that HQ balance.

Per customer, at HQ only (two statements, then read back):
  1. points flag off + special discount on (owner 2026-10-10: "removed customers should get special
     discount", as done by hand on 05HD999):
                       UPDATE localcustomers SET picpoints = 0, picdiscounts = 1, usercode = <operator's SOFTECH
                       user>, trans_time = getdate()  WHERE phcode = ? AND (picpoints = 1 OR picdiscounts = 0)
     — what SOFTECH's customer screen writes (trace of 05HD999: picpoints, picdiscounts, usercode, trans_time).
  2. balance cleared:  INSERT picpoints (phcode, transdate, points = −balance, branchcode '100', doccode '0',
                       docnumber 0, docdate, vf1 reason, vf2 operator)
     — the reset method found in the 05HD999 trace (2022: −14,452, doc '0', branch 100); tr_picpoints applies
       it to localcustomerspoints. The same INSERT pattern as apps/loyalty/pic_bridge.adjust_softech_points.
  The branch copies (points flag + special discount) follow with push_customer_branch_copy --from-removals.
Safety: gate POINTS_REMOVAL_WRITE_ENABLED (default False → dry run); ≤ POINTS_REMOVAL_BATCH_MAX (50) per run;
the balance is re-read just before the INSERT and the INSERT is skipped when it is ≤ 0; read back after
(points 0, balance 0, special discount 1 → verified, else conflict / failed); stops at the first problem;
every attempt is a PointsRemoval row + AuditLog entry. Customers removed before the discount decision are
picked up again (discount 0) and only get the discount. Branch copies: push_customer_branch_copy
--from-removals (points flag + special discount).
"""
import logging

from django.conf import settings

logger = logging.getLogger('elrezeiky.customers')

DB = 'SOFTECHDB9.dbo'
REASON = 'B7 removed from points'   # ASCII: the jConnect link writes Arabic into vf1 as '?'


def write_enabled():
    return bool(getattr(settings, 'POINTS_REMOVAL_WRITE_ENABLED', False))


def batch_max():
    return int(getattr(settings, 'POINTS_REMOVAL_BATCH_MAX', 50))


def _q(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    return cur.fetchall()


def reset_customers(conn, users=('19',)):
    """PICs fully reset at HQ (lcpointstrans edit that set consumed = earned) by the given SOFTECH users."""
    marks = ','.join('?' * len(users))
    rows = _q(conn, f'SELECT DISTINCT phcode FROM {DB}.lcpointstrans WHERE conpoints = totpoints '
                    f'AND conpointsold < conpoints AND totpoints > 0 AND usercode IN ({marks})', list(users))
    return sorted({str(r[0]).strip() for r in rows if r[0]})


def read_state(conn, pic):
    """(points flag, balance, special-discount flag) at HQ, or None when the code does not exist."""
    r = _q(conn, f'SELECT picpoints, picdiscounts FROM {DB}.localcustomers WHERE phcode = ?', [pic])
    if not r:
        return None
    b = _q(conn, f'SELECT totpoints, conpoints FROM {DB}.localcustomerspoints WHERE phcode = ?', [pic])
    bal = int((b[0][0] or 0) - (b[0][1] or 0)) if b else 0
    return int(r[0][0] or 0), bal, int(r[0][1] or 0)


def _done(st):
    """Removed = points off, nothing left to spend, special discount on (owner 2026-10-10)."""
    flag, bal, disc = st
    return flag == 0 and bal <= 0 and disc == 1


def candidates(conn, users=('19',), limit=None):
    """Reset customers not yet fully removed (still enrolled, holding points, or without special discount).
    Bulk reads in chunks — one query per 150 codes instead of two per code."""
    pics = reset_customers(conn, users)
    out = []
    for i in range(0, len(pics), 150):
        chunk = pics[i:i + 150]
        marks = ','.join('?' * len(chunk))
        flags = {str(a).strip(): (int(f or 0), int(d or 0)) for a, f, d in _q(
            conn, f'SELECT phcode, picpoints, picdiscounts FROM {DB}.localcustomers WHERE phcode IN ({marks})', chunk)}
        bals = {str(a).strip(): int((t or 0) - (c or 0)) for a, t, c in _q(
            conn, f'SELECT phcode, totpoints, conpoints FROM {DB}.localcustomerspoints WHERE phcode IN ({marks})', chunk)}
        for pic in chunk:
            if pic not in flags:
                continue
            if not _done((flags[pic][0], bals.get(pic, 0), flags[pic][1])):
                out.append(pic)
                if limit and len(out) >= limit:
                    return out
    return out


def remove_one(pic, *, user=None, commit=False, conn=None):
    from .models import PointsRemoval as R
    rec = R(pic=pic, requested_by=user)
    try:
        st = read_state(conn, pic)
        if st is None:
            raise ValueError(f'{pic} not found at HQ')
        rec.flag_before, rec.balance_before, rec.discount_before = st
        if _done(st):
            rec.status = R.STATUS_NO_CHANGE
            rec.flag_after, rec.balance_after, rec.discount_after = st
        elif not (commit and write_enabled()):
            rec.status = R.STATUS_DRY_RUN
            rec.points_cleared = max(st[1], 0)
            if commit:
                rec.error = 'POINTS_REMOVAL_WRITE_ENABLED is off — nothing written'
        else:
            op = (getattr(user, 'softech_user_id', '') or '').strip()
            if not op:
                raise ValueError('the operator has no SOFTECH user id (StaffProfile.softech_user_id)')
            cur = conn.cursor()
            if st[0] == 1 or st[2] == 0:
                cur.execute(f'UPDATE {DB}.localcustomers SET picpoints = 0, picdiscounts = 1, usercode = ?, '
                            'trans_time = getdate() WHERE phcode = ? AND (picpoints = 1 OR isnull(picdiscounts, 0) = 0)',
                            [op, pic])
            flag, bal, disc = read_state(conn, pic)          # re-read right before touching the balance
            if bal > 0:
                cur.execute(f'INSERT INTO {DB}.picpoints (phcode, transdate, points, branchcode, doccode, docnumber, '
                            "docdate, vf1, vf2) VALUES (?, getdate(), ?, '100', '0', 0, getdate(), ?, ?)",
                            [pic, -bal, REASON, op])
                rec.points_cleared = bal
            after = read_state(conn, pic)
            rec.flag_after, rec.balance_after, rec.discount_after = after
            if _done(after):
                rec.status = R.STATUS_VERIFIED
            elif after[0] == 0 and after[2] == 1:
                rec.status = R.STATUS_CONFLICT
                rec.error = f'balance moved during the run (now {after[1]}) — rerun the code'
            else:
                rec.status = R.STATUS_FAILED
                rec.error = f'read back points={after[0]} discount={after[2]} (expected 0 / 1)'
    except Exception as exc:
        rec.status, rec.error = R.STATUS_FAILED, str(exc)[:500]
        logger.warning('[points_removal] %s failed: %s', pic, exc)
    rec.save()
    if commit and rec.status in (R.STATUS_VERIFIED, R.STATUS_CONFLICT, R.STATUS_FAILED):
        _audit(rec, user)
    return rec


def _audit(rec, user):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log('customer_points_removed', user=user, obj=rec,
                     old_data={'picpoints': rec.flag_before, 'balance': rec.balance_before,
                               'picdiscounts': rec.discount_before},
                     new_data={'picpoints': rec.flag_after, 'balance': rec.balance_after,
                               'picdiscounts': rec.discount_after},
                     note=f'{rec.pic}: −{rec.points_cleared} نقطة · {rec.get_status_display()}'[:255],
                     extra={'error': rec.error})
    except Exception:
        logger.exception('[points_removal] audit failed')


def run(*, pics=None, user=None, commit=False, limit=None, users=('19',), conn=None):
    from config.sybase import get_sybase_connection
    from .models import PointsRemoval as R
    limit = min(int(limit or batch_max()), batch_max())
    own = conn is None
    conn = conn or get_sybase_connection()
    recs = []
    try:
        todo = [p.strip() for p in pics if p.strip()][:limit] if pics else candidates(conn, users, limit)
        for pic in todo:
            r = remove_one(pic, user=user, commit=commit, conn=conn)
            recs.append(r)
            if commit and r.status in (R.STATUS_CONFLICT, R.STATUS_FAILED):
                break
    finally:
        if own:
            conn.close()
    return recs
