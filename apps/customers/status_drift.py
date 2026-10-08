"""
apps/customers/status_drift.py — daily HQ vs branch-node check of customers' SOFTECH account flags
(B7 step 2, owner 2026-10-08). READ-ONLY vs SOFTECH.

Why: SOFTECH does not reliably copy a status change between HQ and the branch nodes (probe
investigate_pic_replication, doc 27): a code HQ closed can still be active on a branch node, so
that branch's till can still serve it (100HD6038 — blocked at HQ, active at branch 140).

For every operational branch node, compare the codes it holds with HQ on three flags:
  status  phcodestatus  — blocked = '0' (file closed) or '5' / picdied (deceased)
  lock    piclock       — entity account
  points  picpoints     — enrolled in points
Rows land in CustomerStatusDrift (open until a later scan stops seeing them). The notification to
CUSTOMER_STATUS_DRIFT_ROLES (admin, supervisor) lists the open `hq_stricter` rows — the branch
till still serves a customer HQ restricted. Nothing is written to SOFTECH; fixing a node copy is
a separate, approved channel.
Settings: CUSTOMER_STATUS_DRIFT_CHECK_ENABLED (True — read-only) · CUSTOMER_STATUS_DRIFT_ROLES.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.customers')

DB = 'SOFTECHDB9.dbo'
LOCK_KEY = 7_301_003            # pg advisory lock (coupon_dashboard uses 7_301_001/2)
QUERY = (f'SELECT phcode, phcodestatus, piclock, picpoints, picdied FROM {DB}.localcustomers')


def _s(v):
    return str(v).strip() if v is not None else ''


def roles():
    return list(getattr(settings, 'CUSTOMER_STATUS_DRIFT_ROLES', ['admin', 'supervisor']))


def load(conn):
    """{phcode: (blocked_code, locked, enrolled)} — blocked_code: '0' closed · '5' deceased · '' not."""
    cur = conn.cursor()
    cur.execute(QUERY)
    out = {}
    for pic, status, lock, points, died in cur.fetchall():
        st = _s(status)
        blocked = '0' if st == '0' else ('5' if (st == '5' or died) else '')
        out[_s(pic)] = (blocked, bool(lock), bool(points))
    return out


def compare(hq, node):
    """Pure. [(pic, field, hq_value, node_value, direction)] for codes held by both."""
    from .models import CustomerStatusDrift as D
    rows = []
    for pic, (nb, nl, np_) in node.items():
        h = hq.get(pic)
        if h is None:
            continue
        hb, hl, hp = h
        if hb != nb:
            d = D.HQ_STRICTER if hb and not nb else (D.NODE_STRICTER if nb and not hb else D.OTHER)
            rows.append((pic, D.FIELD_STATUS, hb or '1', nb or '1', d))
        if hl != nl:
            rows.append((pic, D.FIELD_LOCK, str(int(hl)), str(int(nl)), D.HQ_STRICTER if hl else D.NODE_STRICTER))
        if hp != np_:
            rows.append((pic, D.FIELD_POINTS, str(int(hp)), str(int(np_)), D.NODE_STRICTER if hp else D.HQ_STRICTER))
    return rows


def record(node_branch, rows, now=None):
    """Upsert this node's differences; resolve the node's open rows not seen this time."""
    from .models import CustomerStatusDrift as D
    now = now or timezone.now()
    seen = set()
    with transaction.atomic():
        for pic, field, hv, nv, direction in rows:
            seen.add((pic, field))
            D.objects.update_or_create(
                pic=pic, node_branch=node_branch, field=field,
                defaults={'hq_value': hv, 'node_value': nv, 'direction': direction, 'last_seen': now,
                          'resolved_at': None})
        stale = [r.pk for r in D.objects.filter(node_branch=node_branch, resolved_at__isnull=True)
                 .only('pk', 'pic', 'field') if (r.pic, r.field) not in seen]
        D.objects.filter(pk__in=stale).update(resolved_at=now)
    return len(stale)


def _nodes(hosts=None):
    from apps.branches.models import Branch
    if hosts:
        return [(h, 5000, h) for h in hosts]
    return [(b.db_host, b.db_port or 5000, b.softech_branch_id)
            for b in Branch.objects.filter(is_operational=True).exclude(softech_branch_id='100')
            .exclude(db_host='').exclude(db_host__isnull=True).order_by('softech_branch_id')]


def scan(hosts=None):
    """Run the check on every node. Returns {'nodes': {code: {...}}, 'open_risk': n, 'open': n}."""
    from config.sybase import get_branch_connection, get_sybase_connection
    from .models import CustomerStatusDrift as D
    hq_conn = get_sybase_connection()
    try:
        hq = load(hq_conn)
    finally:
        hq_conn.close()
    out = {'hq_codes': len(hq), 'nodes': {}}
    for host, port, label in _nodes(hosts):
        info = {}
        try:
            conn = get_branch_connection(host, port, 'SOFTECHDB9')
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT branchcode FROM {DB}.lastdocnumbers WHERE ver_branch = '1'")
                r = cur.fetchall()
                code = _s(r[0][0]) if r else label
                node = load(conn)
            finally:
                conn.close()
            rows = compare(hq, node)
            info = {'branch': code, 'held': len(node), 'differences': len(rows),
                    'resolved': record(code, rows)}
        except Exception as exc:          # an offline node keeps its open rows untouched
            info = {'error': str(exc)[:200]}
            logger.warning('[status_drift] node %s skipped: %s', label, exc)
        out['nodes'][label] = info
    open_rows = D.objects.filter(resolved_at__isnull=True)
    out['open'] = open_rows.count()
    out['open_risk'] = open_rows.filter(direction=D.HQ_STRICTER).count()
    return out


def scan_locked(**kw):
    from apps.vouchers.coupon_dashboard import pg_lock
    with pg_lock(LOCK_KEY) as got:
        if not got:
            return None
        return scan(**kw)


FIELD_TEXT = {('status', '0'): 'ملف مغلق', ('status', '5'): 'متوفى', ('status', '1'): 'نشط',
              ('lock', '1'): 'مقفول (جهة)', ('lock', '0'): 'غير مقفول',
              ('points', '1'): 'في نظام النقاط', ('points', '0'): 'خارج نظام النقاط'}


def digest_text(limit=20):
    from .models import CustomerStatusDrift as D
    risk = list(D.objects.filter(resolved_at__isnull=True, direction=D.HQ_STRICTER)
                .order_by('node_branch', 'pic')[:limit])
    lines = [f'• {r.pic} — الرئيسي: {FIELD_TEXT.get((r.field, r.hq_value), r.hq_value)} / '
             f'فرع {r.node_branch}: {FIELD_TEXT.get((r.field, r.node_value), r.node_value)}' for r in risk]
    others = D.objects.filter(resolved_at__isnull=True).exclude(direction=D.HQ_STRICTER).count()
    if others:
        lines.append(f'+ {others} اختلاف آخر (الفرع أشد من الرئيسي) للمراجعة.')
    return '\n'.join(lines)


def notify(result):
    """One notification per admin/supervisor per day while HQ-stricter differences are open."""
    if not result or not result.get('open_risk'):
        return 0
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile
    day = timezone.localdate().isoformat()
    dedup = f'customer_status_drift_{day}'
    title = (f"⚠️ عملاء محظورون في الرئيسي وما زالوا نشطين في فرع — {result['open_risk']} "
             f'({day})')
    body = digest_text()
    sent = 0
    for p in StaffProfile.objects.filter(role__in=roles(), is_active=True):
        if Notification.objects.filter(recipient=p, dedup_key=dedup).exists():
            continue
        Notification.objects.create(recipient=p, notification_type='customer_status_drift',
                                    title=title, body=body, dedup_key=dedup)
        sent += 1
    return sent
