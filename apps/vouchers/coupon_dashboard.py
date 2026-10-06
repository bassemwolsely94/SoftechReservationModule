"""
apps/vouchers/coupon_dashboard.py

Read models for the gift-coupon screen (VouchersPage → «كوبونات الهدايا») and the daily
misuse digest. Everything here reads OUR PostgreSQL mirror (CouponSerial / CouponEvent /
CouponBatch, rebuilt by coupon_lifecycle.sync); nothing touches SOFTECH.
Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md §9.
"""
import datetime as dt
import logging
from collections import Counter, defaultdict

from django.conf import settings
from django.db.models import Count, Max, Q, Sum

from . import coupon_lifecycle, coupons

logger = logging.getLogger('elrezeiky.vouchers')


def _f(v):
    return float(v) if v is not None else 0.0


def _d(v):
    return v.isoformat() if v else None


# ── serialisers (plain dicts) ──────────────────────────────────────────────────
def event_dict(e):
    return {
        'id': e.pk, 'serial': e.raw_serial, 'linked': e.serial_id is not None, 'leg': e.leg,
        'itemcode': e.itemcode, 'kind': e.kind, 'kind_label': e.get_kind_display(),
        'doccode': e.doccode, 'doc_name': e.doc_name, 'branchcode': e.branchcode,
        'storecode': e.storecode, 'docnumber': e.docnumber, 'docdate': _d(e.docdate),
        'line_no': e.line_no, 'qty': _f(e.qty), 'price': _f(e.price), 'party_code': e.party_code,
        'customer_pic': e.customer_pic, 'usercode': e.usercode,
    }


def serial_dict(c, events=False):
    out = {
        'id': c.pk, 'serial': c.serial, 'number': c.number, 'code': c.code,
        'batch_id': c.batch_id, 'source': c.source, 'source_label': c.get_source_display(),
        'status': c.status, 'status_label': c.get_status_display(),
        'stage': c.stage, 'stage_label': c.get_stage_display(),
        'expiry': _d(c.points_expiry or c.served_expiry),
        'points_docnumber': c.points_docnumber, 'points_docdate': _d(c.points_docdate),
        'points_qty': _f(c.points_qty),
        'served_docnumber': c.served_docnumber, 'served_docdate': _d(c.served_docdate),
        'served_qty': _f(c.served_qty),
        'issued_at': _d(c.issued_at), 'issued_doc': c.issued_doc, 'issued_branch': c.issued_branch,
        'issued_pic': c.issued_pic, 'sent_branch': c.sent_branch, 'sent_at': _d(c.sent_at),
        'redeemed_at': _d(c.redeemed_at), 'redeemed_doc': c.redeemed_doc,
        'redeemed_branch': c.redeemed_branch, 'redeemed_pic': c.redeemed_pic,
        'issue_count': c.issue_count, 'redeem_count': c.redeem_count,
        'anomalies': [{'code': a, 'label': coupon_lifecycle.ANOMALY_LABELS.get(a, a)}
                      for a in (c.anomalies or [])],
        'conflict_note': c.conflict_note,
    }
    if events:
        out['events'] = [event_dict(e) for e in c.events.order_by('docdate', 'docnumber', 'line_no')]
    return out


def batch_dict(b):
    def leg(inv):
        if inv is None:
            return None
        return {'invoice_id': inv.pk, 'status': inv.status, 'docnumber': inv.softech_docnumber,
                'docdate': _d(getattr(inv, 'softech_docdate', None)),
                'error': (getattr(inv, 'erp_error', '') or '')[:300]}
    return {
        'id': b.pk, 'source': b.source, 'status': b.status, 'status_label': b.get_status_display(),
        'size': b.size, 'serial_from': b.serial_from, 'serial_to': b.serial_to,
        'expiry_from': _d(b.expiry_from), 'expiry_to': _d(b.expiry_to),
        'created_by': (b.created_by.full_name if b.created_by_id else ''),
        'created_at': b.created_at.isoformat(), 'notes': b.notes,
        'points': leg(b.points_invoice), 'served': leg(b.served_invoice),
    }


# ── screen read models ─────────────────────────────────────────────────────────
def overview():
    from .models import CouponBatch, CouponEvent, CouponSerial

    flags = Counter()
    for lst in CouponSerial.objects.exclude(anomalies=[]).values_list('anomalies', flat=True):
        flags.update(lst)
    since30 = dt.date.today() - dt.timedelta(days=30)
    no_serial = (CouponEvent.objects.filter(serial_id=None, kind='redeem', docdate__gte=since30)
                 .values('branchcode').annotate(lines=Count('id'), qty=Sum('qty')).order_by('-qty'))
    cust = coupon_lifecycle.customer_balances(limit=0)
    last = CouponEvent.objects.aggregate(synced=Max('created_at'), latest=Max('docdate'))
    hq_ready = CouponSerial.objects.filter(stage='stocked', source='generated').count()
    from apps.invoices import writer
    from .coupon_guard import guard_enabled
    return {
        'stages': {k or 'none': n for k, n in
                   CouponSerial.objects.values_list('stage').annotate(n=Count('id'))},
        'serials': CouponSerial.objects.count(),
        'generated_unstocked': CouponSerial.objects.filter(status='generated').count(),
        'hq_stocked_generated': hq_ready,
        'anomalies': [{'code': k, 'label': coupon_lifecycle.ANOMALY_LABELS.get(k, k), 'count': n}
                      for k, n in flags.most_common()],
        'no_serial_30d': [{'branch': r['branchcode'], 'lines': r['lines'], 'qty': _f(r['qty'])}
                          for r in no_serial],
        'customers': {k: cust[k] for k in ('customers_over', 'excess_total', 'active_over',
                                           'active_excess', 'redeemed_without_customer')},
        'customers_since': _d(cust['since']),
        'last_sync_at': last['synced'].isoformat() if last['synced'] else None,
        'latest_movement': _d(last['latest']),
        'batches_pending': CouponBatch.objects.filter(status='generated').count(),
        'writer_enabled': writer.writer_enabled(),
        'guard_enabled': guard_enabled(),
        'batch_size': coupons.batch_size(),
    }


def find_serials(q, limit=20):
    """Exact serial (27301-ABC123), a bare number (27301 → every serial with it) or a code."""
    from .models import CouponSerial
    q = (q or '').strip().upper()
    if not q:
        return []
    parsed = coupons.parse_serial(q)
    if parsed:
        qs = CouponSerial.objects.filter(serial=parsed[2])
    elif q.isdigit():
        qs = CouponSerial.objects.filter(number=int(q))
    else:
        qs = CouponSerial.objects.filter(code=q)
    return list(qs.order_by('number')[:limit])


def serial_lookup(q):
    """Matching serials (with full history) + movement lines whose raw serial equals q but
    are not linked to a known serial (junk / mistyped serials on sales)."""
    from .models import CouponEvent
    rows = find_serials(q)
    raw = (q or '').strip()
    stray = (CouponEvent.objects.filter(serial_id=None, raw_serial__iexact=raw)
             .order_by('-docdate')[:50]) if raw else []
    return {'serials': [serial_dict(c, events=True) for c in rows],
            'unlinked_events': [event_dict(e) for e in stray]}


def customers_over(limit=200, active_only=True):
    """Customers who redeemed more coupons than were issued to them (coupon_lifecycle rule)."""
    cust = coupon_lifecycle.customer_balances(limit=None)
    rows = cust['top'] if active_only else cust['all']
    names = _customer_names([r['pic'] for r in rows[:limit]])
    return {
        'since': _d(cust['since']), 'customers_over': cust['customers_over'],
        'active_over': cust['active_over'], 'active_excess': cust['active_excess'],
        'rows': [{**r, 'last': _d(r['last']), 'name': names.get(r['pic'], '')} for r in rows[:limit]],
    }


def _customer_names(pics):
    try:
        from apps.customers.models import Customer
        return dict(Customer.objects.filter(softech_pic__in=pics).values_list('softech_pic', 'name'))
    except Exception:
        return {}


def customer_history(pic):
    """Every issue / redemption line booked on one customer code (PIC)."""
    from .models import CouponEvent
    pic = (pic or '').strip()
    ev = list(CouponEvent.objects.filter(customer_pic=pic,
                                         kind__in=('issue', 'issue_return', 'redeem', 'redeem_return'))
              .order_by('-docdate', '-docnumber', 'line_no'))
    tot = defaultdict(float)
    for e in ev:
        tot[e.kind] += _f(e.qty)
    return {
        'pic': pic, 'name': _customer_names([pic]).get(pic, ''),
        'issued': tot['issue'] - tot['issue_return'],
        'redeemed': tot['redeem'] - tot['redeem_return'],
        'events': [event_dict(e) for e in ev],
    }


def no_serial_lines(branch='', days=30, limit=500):
    """Redemption lines without a valid coupon serial, newest first, + totals by branch / user."""
    from .models import CouponEvent
    qs = CouponEvent.objects.filter(serial_id=None, kind='redeem',
                                    docdate__gte=dt.date.today() - dt.timedelta(days=int(days)))
    if branch:
        qs = qs.filter(branchcode=str(branch))
    by_branch = qs.values('branchcode').annotate(lines=Count('id'), qty=Sum('qty')).order_by('-qty')
    by_user = (qs.values('branchcode', 'usercode').annotate(lines=Count('id'), qty=Sum('qty'))
               .order_by('-qty'))
    return {
        'days': int(days), 'branch': str(branch or ''),
        'by_branch': [{'branch': r['branchcode'], 'lines': r['lines'], 'qty': _f(r['qty'])} for r in by_branch],
        'by_user': [{'branch': r['branchcode'], 'usercode': r['usercode'], 'lines': r['lines'],
                     'qty': _f(r['qty'])} for r in by_user],
        'rows': [event_dict(e) for e in qs.order_by('-docdate', '-docnumber')[:limit]],
    }


# ── cross-process locks (web workers + scheduler) ──────────────────────────────
LOCK_SYNC = 7_301_001          # lifecycle mirror sync
LOCK_PUSH = 7_301_002          # SOFTECH stocking of a coupon batch (key + batch id)


class pg_lock:
    """PostgreSQL session advisory lock, non-blocking: ``with pg_lock(k) as got: ...``.
    ``got`` is False when another process holds it (the caller refuses instead of waiting)."""

    def __init__(self, key):
        self.key, self.got = int(key), False

    def __enter__(self):
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [self.key])
            self.got = bool(cur.fetchone()[0])
        return self.got

    def __exit__(self, *exc):
        if self.got:
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(%s)', [self.key])
        return False


def locked_sync(**kw):
    """coupon_lifecycle.sync under the sync lock. Returns the totals, or None when a sync
    is already running elsewhere."""
    from config.sybase import get_sybase_connection
    with pg_lock(LOCK_SYNC) as got:
        if not got:
            return None
        conn = get_sybase_connection()
        try:
            return coupon_lifecycle.sync(conn, **kw)
        finally:
            conn.close()


# ── daily misuse digest (scheduler) ────────────────────────────────────────────
def daily_digest(day=None):
    """What went wrong on ``day`` (default yesterday), from the mirror:
      * redemption lines without a valid serial (by branch / SOFTECH user);
      * redemptions of a serial already used up (redeemed more than stocked);
      * customers who redeemed that day and now hold more redemptions than issues.
    Lines booked later with an older date are not in the digest — the screen shows them."""
    from .models import CouponEvent

    day = day or (dt.date.today() - dt.timedelta(days=1))
    red = CouponEvent.objects.filter(kind='redeem', docdate=day)
    no_serial = list(red.filter(serial_id=None).order_by('branchcode', 'docnumber'))
    reused = list(red.filter(serial__isnull=False, serial__anomalies__contains=['redeemed_twice'])
                  .select_related('serial').order_by('branchcode', 'docnumber'))
    pics = set(red.exclude(customer_pic='').values_list('customer_pic', flat=True))
    over = [r for r in coupon_lifecycle.customer_balances(limit=None)['all'] if r['pic'] in pics]
    by_branch = defaultdict(float)
    by_user = defaultdict(float)
    for e in no_serial:
        by_branch[e.branchcode] += _f(e.qty)
        by_user[(e.branchcode, e.usercode)] += _f(e.qty)
    return {
        'day': day,
        'no_serial': no_serial, 'no_serial_qty': sum(_f(e.qty) for e in no_serial),
        'no_serial_by_branch': dict(by_branch), 'no_serial_by_user': dict(by_user),
        'reused': reused,
        'customers_over': over,
    }


def digest_is_empty(d):
    return not (d['no_serial'] or d['reused'] or d['customers_over'])


def digest_text(d, max_lines=10):
    """Arabic notification body for a daily_digest() result."""
    parts = []
    if d['no_serial']:
        users = '، '.join(f'{u or "؟"}@{b}={q:g}' for (b, u), q in
                         sorted(d['no_serial_by_user'].items(), key=lambda x: -x[1]))
        parts.append(f"• {len(d['no_serial'])} سطر استخدام كوبون بدون سريال صحيح "
                     f"({d['no_serial_qty']:g} كوبون) — حسب المستخدم/الفرع: {users}")
        for e in d['no_serial'][:max_lines]:
            parts.append(f"   {e.branchcode}/{e.doccode}/{e.docnumber} كمية {_f(e.qty):g} "
                         f"سريال «{e.raw_serial or '—'}» عميل {e.customer_pic or '—'} مستخدم {e.usercode}")
    if d['reused']:
        parts.append(f"• {len(d['reused'])} استخدام لسريال مستخدم من قبل:")
        for e in d['reused'][:max_lines]:
            parts.append(f"   {e.raw_serial} — {e.branchcode}/{e.doccode}/{e.docnumber} "
                         f"عميل {e.customer_pic or '—'} مستخدم {e.usercode}")
    if d['customers_over']:
        parts.append(f"• {len(d['customers_over'])} عميل استخدم كوبونات أكثر مما صُرف له:")
        for r in d['customers_over'][:max_lines]:
            parts.append(f"   {r['pic']}: صُرف {r['issued']:g} / استُخدم {r['redeemed']:g} "
                         f"(زيادة {r['excess']:g})")
    parts.append('التفاصيل: القسائم ← كوبونات الهدايا')
    return '\n'.join(parts)


def digest_roles():
    return tuple(getattr(settings, 'COUPON_DIGEST_ROLES', ('admin', 'supervisor')))


def notify_digest(d):
    """One in-app notification per recipient role member, deduped per day. Returns the
    number of notifications created (0 when there is nothing to report)."""
    if digest_is_empty(d):
        return 0
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile

    dedup = f"coupon_digest_{d['day'].isoformat()}"
    n_issues = len(d['no_serial']) + len(d['reused']) + len(d['customers_over'])
    title = f"🎟️ رقابة كوبونات الهدايا — {d['day'].isoformat()} ({n_issues} ملاحظة)"
    body = digest_text(d)
    sent = 0
    for p in StaffProfile.objects.filter(role__in=digest_roles(), is_active=True):
        if Notification.objects.filter(recipient=p, dedup_key=dedup).exists():
            continue
        try:
            Notification.objects.create(recipient=p, notification_type='coupon_digest',
                                        title=title, body=body, dedup_key=dedup)
            sent += 1
        except Exception:
            logger.exception('[coupons] digest notification failed for %s', p.pk)
    return sent
