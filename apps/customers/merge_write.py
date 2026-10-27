"""
apps/customers/merge_write.py — merge an APPROVED duplicate code into its main code at HQ (B7 merge part 2).

Owner 2026-10-10 "Next batch (part 2)". Only pairs approved in the merge queue (maker-checker,
apps/customers/duplicates.py) are written. Per pair, at HQ, in this order:

  1. points (only when the old code holds a balance > 0):
       INSERT picpoints (old,  −balance, branch '100', doc '0', docnumber 0, vf1 'B7 merge <id>', vf2 operator)
       INSERT picpoints (main, +same,    branch '100', doc '0', docnumber 0, vf1 'B7 merge <id>', vf2 operator)
     tr_picpoints applies both rows to localcustomerspoints — the method of the HQ resets / Option B. The debit
     goes first (a failure in between strands points, never doubles them), and the credit amount is read back
     from the debit row itself. The vf1 tag makes it idempotent: a rerun finds the tagged rows and never moves
     the balance twice; a run that stopped after the debit only adds the missing credit.
  2. status: UPDATE localcustomers SET phcodestatus = '0', phcodestatususercode, phcodestatustime, usercode,
     trans_time WHERE phcode = old AND phcodestatus = <value read> (optimistic). The main code is untouched.
  3. read back: old closed, tagged debit and credit present and equal → verified, else conflict / failed.

Our side: MergeCandidate → merged; the old code's Customer mirror gets merged_into_pic (POS / reservations
show "use code <main>") and softech_status '0' at once. History stays under the old code in SOFTECH; pphcode
is never written. Branch copies follow through the daily status check → push_customer_branch_copy --from-drift.

Refused (failed, nothing written): pair not approved · a code missing · main closed / deceased / entity ·
old deceased / entity · main itself merged away (chain) · balance to move while either code is outside the
points system (owner: removed customers must not pass points on) · more than one tagged debit.
Gate CUSTOMER_MERGE_WRITE_ENABLED (default False → dry run); ≤ CUSTOMER_MERGE_BATCH_MAX per run; stops at
the first conflict / failure; one run at a time (pg lock); every attempt = CustomerMergeWrite + AuditLog.
"""
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.customers')

DB = 'SOFTECHDB9.dbo'
LOCK_KEY = 7_301_005


def write_enabled():
    return bool(getattr(settings, 'CUSTOMER_MERGE_WRITE_ENABLED', False))


def batch_max():
    return int(getattr(settings, 'CUSTOMER_MERGE_BATCH_MAX', 20))


def tag(cand):
    return f'B7 merge {cand.pk}'


def _q(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    return cur.fetchall()


def _s(v):
    return str(v).strip() if v is not None else ''


def read_code(conn, pic):
    """{status, locked, died, points, balance} at HQ, or None."""
    r = _q(conn, f'SELECT phcodestatus, piclock, picdied, picpoints FROM {DB}.localcustomers WHERE phcode = ?', [pic])
    if not r:
        return None
    b = _q(conn, f'SELECT sum(totpoints - conpoints) FROM {DB}.localcustomerspoints WHERE phcode = ?', [pic])
    st, lock, died, pts = r[0]
    return {'status': _s(st), 'locked': bool(int(lock or 0)), 'died': bool(int(died or 0)),
            'points': bool(int(pts or 0)), 'balance': int((b[0][0] if b else 0) or 0)}


def tagged(conn, pic, t):
    """(row count, points sum) of picpoints rows carrying our tag for this code."""
    r = _q(conn, f'SELECT count(*), sum(points) FROM {DB}.picpoints WHERE phcode = ? AND vf1 = ?', [pic, t])
    return (int(r[0][0] or 0), int(r[0][1] or 0)) if r else (0, 0)


def _refusal(cand, old, main):
    from .models import MergeCandidate as MC
    if old is None:
        return f'{cand.old_pic} not found at HQ'
    if main is None:
        return f'{cand.main_pic} not found at HQ'
    if main['status'] in ('0', '5') or main['died'] or main['locked']:
        return f"main {cand.main_pic} is not active (status {main['status']!r}, locked {main['locked']}, died {main['died']})"
    if old['status'] == '5' or old['died'] or old['locked']:
        return f'{cand.old_pic} is deceased / an entity — never merged'
    if MC.objects.filter(old_pic=cand.main_pic, status__in=(MC.APPROVED, MC.MERGED)).exists():
        return f'main {cand.main_pic} is itself merged away — re-review the group'
    return ''


def merge_one(cand, *, user=None, commit=False, conn=None):
    from .models import CustomerMergeWrite as W, MergeCandidate as MC
    rec = W(candidate=cand, old_pic=cand.old_pic, main_pic=cand.main_pic, requested_by=user)
    t = tag(cand)
    try:
        if cand.status not in (MC.APPROVED, MC.FAILED, MC.MERGED):
            raise ValueError(f'pair not approved (status {cand.status})')
        old, main = read_code(conn, cand.old_pic), read_code(conn, cand.main_pic)
        debit, credit = tagged(conn, cand.old_pic, t), tagged(conn, cand.main_pic, t)
        rec.before = {'old': old, 'main': main, 'debit': debit, 'credit': credit}
        why = _refusal(cand, old, main)
        if why:
            raise ValueError(why)
        if debit[0] > 1 or credit[0] > 1:
            raise ValueError(f'more than one tagged points row ({debit[0]}/{credit[0]}) — check by hand')
        move = old['balance'] if (debit[0] == 0 and old['balance'] > 0) else 0
        pending = -debit[1] if (debit[0] == 1 and credit[0] == 0) else 0
        if move and not (old['points'] and main['points']):
            raise ValueError(f"{old['balance']} points to move but the {'old' if not old['points'] else 'main'} "
                             'code is outside the points system — decide by hand')
        rec.points_moved = move or pending or (credit[1] if credit[0] else 0)
        if not move and not pending and old['status'] == '0':
            rec.status, rec.after = W.STATUS_NO_CHANGE, rec.before
        elif not (commit and write_enabled()):
            rec.status = W.STATUS_DRY_RUN
            if commit:
                rec.error = 'CUSTOMER_MERGE_WRITE_ENABLED is off — nothing written'
        else:
            op = _s(getattr(user, 'softech_user_id', ''))
            if not op:
                raise ValueError('the operator has no SOFTECH user id (StaffProfile.softech_user_id)')
            cur = conn.cursor()
            ins = (f'INSERT INTO {DB}.picpoints (phcode, transdate, points, branchcode, doccode, docnumber, docdate, '
                   "vf1, vf2) VALUES (?, getdate(), ?, '100', '0', 0, getdate(), ?, ?)")
            if move:
                bal = read_code(conn, cand.old_pic)['balance']        # re-read right before the debit
                if bal > 0:
                    cur.execute(ins, [cand.old_pic, -bal, t, op])
            debit = tagged(conn, cand.old_pic, t)
            if debit[0] == 1 and tagged(conn, cand.main_pic, t)[0] == 0:
                cur.execute(ins, [cand.main_pic, -debit[1], t, op])
            if old['status'] != '0':
                cur.execute(f"UPDATE {DB}.localcustomers SET phcodestatus = '0', phcodestatususercode = ?, "
                            'phcodestatustime = getdate(), usercode = ?, trans_time = getdate() '
                            "WHERE phcode = ? AND isnull(phcodestatus, '') = ?", [op, op, cand.old_pic, old['status']])
            o2, m2 = read_code(conn, cand.old_pic), read_code(conn, cand.main_pic)
            d2, c2 = tagged(conn, cand.old_pic, t), tagged(conn, cand.main_pic, t)
            rec.after = {'old': o2, 'main': m2, 'debit': d2, 'credit': c2}
            rec.points_moved = c2[1]
            points_ok = (d2 == (0, 0) and c2 == (0, 0)) or (d2[0] == 1 and c2[0] == 1 and c2[1] == -d2[1])
            if o2['status'] == '0' and points_ok:
                rec.status = W.STATUS_VERIFIED
                if o2['balance'] > 0:
                    rec.error = f"old code still shows {o2['balance']} points (earned during the run)"
            elif points_ok:
                rec.status = W.STATUS_CONFLICT
                rec.error = f"old code status changed during the run (now {o2['status']!r}) — rerun"
            else:
                rec.status = W.STATUS_FAILED
                rec.error = f'points rows debit {d2} / credit {c2} do not match — rerun adds the missing credit'
    except Exception as exc:
        rec.status, rec.error = W.STATUS_FAILED, str(exc)[:500]
        logger.warning('[merge_write] %s → %s failed: %s', cand.old_pic, cand.main_pic, exc)
    rec.save()
    _apply_ours(cand, rec, commit)
    if commit and rec.status != W.STATUS_DRY_RUN:
        _audit(rec, user)
    return rec


def _apply_ours(cand, rec, commit):
    from .models import Customer, CustomerMergeWrite as W, MergeCandidate as MC
    if not commit:
        return
    if rec.status in (W.STATUS_VERIFIED, W.STATUS_NO_CHANGE):
        cand.status, cand.error = MC.MERGED, rec.error
        cand.merged_at = cand.merged_at or timezone.now()
        cand.save(update_fields=['status', 'error', 'merged_at', 'updated_at'])
        Customer.objects.filter(softech_pic=cand.old_pic).update(merged_into_pic=cand.main_pic, softech_status='0')
    elif rec.status in (W.STATUS_CONFLICT, W.STATUS_FAILED):
        cand.status, cand.error = MC.FAILED, rec.error
        cand.save(update_fields=['status', 'error', 'updated_at'])


def _audit(rec, user):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log('customer_updated', user=user, obj=rec, old_data=rec.before, new_data=rec.after,
                     note=f'B7 merge {rec.old_pic} → {rec.main_pic}: {rec.points_moved} نقطة · '
                          f'{rec.get_status_display()}'[:255],
                     extra={'error': rec.error, 'candidate': rec.candidate_id})
    except Exception:
        logger.exception('[merge_write] audit failed')


def todo(pics=None, limit=None):
    """Approved pairs (or the given old codes, which may also retry a failed pair)."""
    from .models import MergeCandidate as MC
    limit = min(int(limit or batch_max()), batch_max())
    if pics:
        qs = MC.objects.filter(old_pic__in=[p.strip() for p in pics if p.strip()],
                               status__in=(MC.APPROVED, MC.FAILED, MC.MERGED))
    else:
        qs = MC.objects.filter(status=MC.APPROVED).order_by('approved_at', 'pk')
    return list(qs[:limit])


def run(*, pics=None, user=None, commit=False, limit=None, conn=None):
    from apps.vouchers.coupon_dashboard import pg_lock
    from config.sybase import get_sybase_connection
    from .models import CustomerMergeWrite as W
    with pg_lock(LOCK_KEY) as got:
        if not got:
            raise ValueError('another merge run is in progress')
        own = conn is None
        conn = conn or get_sybase_connection()
        recs = []
        try:
            for cand in todo(pics, limit):
                r = merge_one(cand, user=user, commit=commit, conn=conn)
                recs.append(r)
                if commit and r.status in (W.STATUS_CONFLICT, W.STATUS_FAILED):
                    break
        finally:
            if own:
                conn.close()
        return recs
