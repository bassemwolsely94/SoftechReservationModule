"""
apps/vouchers/coupon_lifecycle.py

Gift-coupon lifecycle tracking — READ-ONLY from SOFTECH.
Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md (doc types from `transdoc`).

Every movement of a coupon item carries the serial in stktrans.item_partno:
    10  شراء من مورد              stocked at HQ (both legs) — already in the archive
    170 صرف أصناف مصروفات          POINTS coupon (102230) issued to a customer; header phcode = PIC
    125 / 25 تبادل بين الفروع      SERVED coupon (118639) HQ → branch / received at the branch
    115 مبيعات لعميل               SERVED coupon redeemed on a sale at −50 EGP; header phcode = PIC
    30  (customer return)         redemption reversed
sync_events() mirrors those lines into CouponEvent (a date window is replaced, so re-runs
are idempotent); rebuild_summaries() recomputes each CouponSerial's lifecycle + anomaly
flags deterministically from its events. Nothing is ever written to SOFTECH.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction

from . import coupons

logger = logging.getLogger('elrezeiky.vouchers')

_DB = 'SOFTECHDB9.dbo'

# Confirmed on real coupon documents (2026-10-06 probe). Other doccodes are classified
# by their transdoc name (تبادل = inter-branch transfer), else 'other'.
_KIND_BY_DOCCODE = {
    '170': 'issue', '125': 'transfer_out', '25': 'transfer_in',
    '115': 'redeem', '30': 'redeem_return', '120': 'supplier_return',
}

ANOMALY_LABELS = {
    'redeemed_twice':            'استُخدم أكثر من مرة',
    'issued_twice':              'صُرف لعميل أكثر من مرة',
    'redeemed_not_issued':       'استُخدم دون صرفه لعميل مقابل نقاط',
    'redeemed_not_stocked':      'استُخدم ولم يُدخل في المخزن على صنف الاستحقاق',
    'redeemed_at_unsent_branch': 'استُخدم في فرع لم يُرسل إليه',
    'redeemed_by_other_customer': 'استخدمه عميل غير الذي صُرف له',
}


def since_default():
    return str(getattr(settings, 'COUPON_LIFECYCLE_SINCE', '2021-01-01'))


def classify(doccode, leg, doc_name=''):
    """(kind, direction) of a coupon movement line."""
    code = str(doccode).strip()
    kind = _KIND_BY_DOCCODE.get(code)
    if kind is None and 'تبادل' in (doc_name or ''):
        kind = 'transfer_in' if ('استلام' in doc_name or 'إستلام' in doc_name) else 'transfer_out'
    if kind == 'issue' and leg != 'points':
        kind = 'other'
    if kind in ('redeem', 'redeem_return') and leg != 'served':
        kind = 'other'
    try:
        direction = 'in' if int(code) < 99 else 'out'
    except ValueError:
        direction = 'out'
    return kind or 'other', direction


def _dec(v):
    try:
        return Decimal(str(v if v is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _s(v):
    return '' if v is None else str(v).strip()


# ── SOFTECH reads (SELECT only) ────────────────────────────────────────────────
def read_doc_names(conn):
    cur = conn.cursor()
    cur.execute(f'SELECT doccode, docdescr FROM {_DB}.transdoc')
    return {_s(r[0]): _s(r[1]) for r in cur.fetchall()}


def read_movements(conn, itemcode, start, end):
    """All non-purchase lines of one coupon item with start ≤ docdate < end, joined to
    their header (party + customer PIC)."""
    cur = conn.cursor()
    timeout = int(getattr(settings, 'SYBASE_SYNC_QUERY_TIMEOUT', 300))
    cur.execute(f"""
        SELECT t.branchcode, t.doccode, t.docnumber, t.docdate, t.storecode, t.dblitemflag,
               t.transqty, t.itemsaleprice, t.item_partno, t.usercode,
               m.cust_branch_code, m.phcode
        FROM {_DB}.stktrans t, {_DB}.stktransm m
        WHERE t.itemcode = ? AND t.doccode <> '10' AND t.docdate >= ? AND t.docdate < ?
          AND m.branchcode = t.branchcode AND m.doccode = t.doccode AND m.docnumber = t.docnumber
    """, [itemcode, start.isoformat(), end.isoformat()], timeout=timeout)
    keys = ('branchcode', 'doccode', 'docnumber', 'docdate', 'storecode', 'dblitemflag', 'transqty',
            'itemsaleprice', 'item_partno', 'usercode', 'cust_branch_code', 'phcode')
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def _windows(start, end, days=31):
    d = start
    while d < end:
        nxt = min(d + dt.timedelta(days=days), end)
        yield d, nxt
        d = nxt


# ── mirror + rebuild ───────────────────────────────────────────────────────────
@transaction.atomic
def store_events(rows, start, end, doc_names=None):
    """Replace every CouponEvent with start ≤ docdate < end by ``rows`` (dicts from
    read_movements, plus 'itemcode'). Returns counts. Idempotent for a given window."""
    from apps.customers.models import Customer
    from .models import CouponEvent, CouponSerial

    doc_names = doc_names or {}
    CouponEvent.objects.filter(docdate__gte=start, docdate__lt=end).delete()
    serial_ids = dict(CouponSerial.objects.values_list('serial', 'id'))
    pics = {_s(r.get('phcode')) for r in rows if _s(r.get('phcode'))}
    customers = dict(Customer.objects.filter(softech_pic__in=pics).values_list('softech_pic', 'id'))

    events, seen = [], set()
    stats = {'lines': 0, 'linked': 0, 'no_serial': 0, 'unknown_serial': 0}
    for r in rows:
        leg = coupons.leg_for_item(r.get('itemcode'))
        docdate = coupons.to_date(r.get('docdate'))
        docnumber = coupons.to_docnumber(r.get('docnumber'))
        if not leg or docdate is None or docnumber is None:
            continue
        key = (_s(r.get('branchcode')), _s(r.get('doccode')), docnumber, _s(r.get('itemcode')),
               int(_dec(r.get('dblitemflag'))))
        if key in seen:
            continue
        seen.add(key)
        stats['lines'] += 1
        raw = _s(r.get('item_partno'))
        parsed = coupons.parse_serial(raw)
        sid = serial_ids.get(parsed[2]) if parsed else None
        if sid:
            stats['linked'] += 1
        elif parsed:
            stats['unknown_serial'] += 1
        else:
            stats['no_serial'] += 1
        doccode = _s(r.get('doccode'))
        name = doc_names.get(doccode, '')
        kind, _ = classify(doccode, leg, name)
        pic = _s(r.get('phcode'))
        events.append(CouponEvent(
            serial_id=sid, raw_serial=raw[:40], leg=leg, itemcode=key[3], kind=kind,
            doccode=doccode, doc_name=name[:100], branchcode=key[0], storecode=_s(r.get('storecode')),
            docnumber=docnumber, docdate=docdate, line_no=key[4], qty=_dec(r.get('transqty')),
            price=_dec(r.get('itemsaleprice')), party_code=_s(r.get('cust_branch_code'))[:10],
            customer_pic=pic[:30], customer_id=customers.get(pic), usercode=_s(r.get('usercode'))[:10]))
    CouponEvent.objects.bulk_create(events, batch_size=2000)
    return stats


def summarise(serial, events):
    """Pure: the lifecycle fields + anomaly codes of one serial from its events
    (each an object with kind/leg/branchcode/docdate/docnumber/customer_pic/qty)."""
    hq = coupons.hq_branch()
    ev = sorted(events, key=lambda e: (e.docdate, e.docnumber))
    issues = [e for e in ev if e.kind == 'issue']
    redeems = [e for e in ev if e.kind == 'redeem']
    returns = [e for e in ev if e.kind == 'redeem_return']
    transfers_in = [e for e in ev if e.kind == 'transfer_in']
    transfers_out = [e for e in ev if e.kind == 'transfer_out']
    net_redeem = len(redeems) - len(returns)

    out = {
        'issue_count': len(issues), 'redeem_count': net_redeem,
        'issued_at': None, 'issued_doc': None, 'issued_branch': '', 'issued_pic': '',
        'sent_branch': '', 'sent_at': None,
        'redeemed_at': None, 'redeemed_doc': None, 'redeemed_branch': '', 'redeemed_pic': '',
    }
    if issues:
        e = issues[0]
        out.update(issued_at=e.docdate, issued_doc=e.docnumber, issued_branch=e.branchcode,
                   issued_pic=e.customer_pic)
    if transfers_in:
        e = transfers_in[-1]
        out.update(sent_branch=e.branchcode, sent_at=e.docdate)
    elif transfers_out:
        e = transfers_out[-1]
        out.update(sent_branch=e.party_code, sent_at=e.docdate)
    if redeems and net_redeem > 0:
        e = redeems[-1]
        out.update(redeemed_at=e.docdate, redeemed_doc=e.docnumber, redeemed_branch=e.branchcode,
                   redeemed_pic=e.customer_pic)

    if net_redeem > 0:
        stage = 'redeemed'
    elif out['sent_branch'] and out['sent_branch'] != hq:
        stage = 'at_branch'
    elif issues:
        stage = 'issued'
    elif serial.points_docnumber or serial.served_docnumber:
        stage = 'stocked'
    else:
        stage = ''
    out['stage'] = stage

    flags = []
    if net_redeem > 1:
        flags.append('redeemed_twice')
    if len(issues) > 1:
        flags.append('issued_twice')
    if net_redeem > 0:
        if not issues:
            flags.append('redeemed_not_issued')
        if not serial.served_docnumber:
            flags.append('redeemed_not_stocked')
        sent_to = {e.branchcode for e in transfers_in} | {e.party_code for e in transfers_out}
        if out['redeemed_branch'] not in sent_to | {hq}:
            flags.append('redeemed_at_unsent_branch')
        if out['issued_pic'] and out['redeemed_pic'] and out['issued_pic'] != out['redeemed_pic']:
            flags.append('redeemed_by_other_customer')
    out['anomalies'] = flags
    return out


@transaction.atomic
def rebuild_summaries():
    """Recompute every CouponSerial's lifecycle from its events. Deterministic."""
    from .models import CouponEvent, CouponSerial

    by_serial = defaultdict(list)
    for e in CouponEvent.objects.exclude(serial_id=None).only(
            'serial_id', 'kind', 'leg', 'branchcode', 'docdate', 'docnumber', 'customer_pic',
            'party_code', 'qty'):
        by_serial[e.serial_id].append(e)
    fields = ['stage', 'issued_at', 'issued_doc', 'issued_branch', 'issued_pic', 'sent_branch',
              'sent_at', 'redeemed_at', 'redeemed_doc', 'redeemed_branch', 'redeemed_pic',
              'issue_count', 'redeem_count', 'anomalies']
    rows = list(CouponSerial.objects.all())
    for c in rows:
        for k, v in summarise(c, by_serial.get(c.id, [])).items():
            setattr(c, k, v)
    CouponSerial.objects.bulk_update(rows, fields, batch_size=1000)
    return len(rows)


def sync(conn, *, since=None, until=None, full=False, progress=None):
    """Mirror coupon movements from SOFTECH (read-only) and rebuild summaries.
    Default window: from 7 days before the latest mirrored event (or since_default()
    when empty / full) to tomorrow."""
    from .models import CouponEvent

    until = until or (dt.date.today() + dt.timedelta(days=1))
    if since is None:
        last = None if full else CouponEvent.objects.order_by('-docdate').values_list('docdate', flat=True).first()
        since = (last - dt.timedelta(days=7)) if last else dt.date.fromisoformat(since_default())
    names = read_doc_names(conn)
    totals = defaultdict(int)
    for start, end in _windows(since, until):
        rows = []
        for item in (coupons.points_item(), coupons.served_item()):
            for r in read_movements(conn, item, start, end):
                r['itemcode'] = item
                rows.append(r)
        for k, v in store_events(rows, start, end, names).items():
            totals[k] += v
        if progress:
            progress(start, end, len(rows))
    totals['serials'] = rebuild_summaries()
    totals['since'], totals['until'] = since.isoformat(), until.isoformat()
    return dict(totals)


# ── reporting ──────────────────────────────────────────────────────────────────
def report():
    from django.db.models import Count, Sum
    from .models import CouponEvent, CouponSerial

    flags = defaultdict(int)
    for lst in CouponSerial.objects.exclude(anomalies=[]).values_list('anomalies', flat=True):
        for f in lst:
            flags[f] += 1
    no_serial = (CouponEvent.objects.filter(serial_id=None, kind='redeem')
                 .values('branchcode').annotate(n=Count('id'), qty=Sum('qty')).order_by('-n'))
    return {
        'stages': dict(CouponSerial.objects.values_list('stage').annotate(n=Count('id')).values_list('stage', 'n')),
        'anomalies': dict(flags),
        'redeemed_without_valid_serial_by_branch': [(r['branchcode'], r['n'], float(r['qty'] or 0)) for r in no_serial],
        'redeemed_by_branch': list(CouponSerial.objects.filter(stage='redeemed')
                                   .values('redeemed_branch').annotate(n=Count('id')).order_by('-n')
                                   .values_list('redeemed_branch', 'n')),
    }
