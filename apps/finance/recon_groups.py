"""
apps/finance/recon_groups.py — the GROUPED review view (owner request 2026-09-28).

Every candidate in scope is gathered under its invoice (by='invoice': all vouchers
proposed for one invoice, one under the other) or under its voucher (by='payment':
every invoice one voucher could pay — where equal-score conflicts sit side by side).
Each group carries the object's capacity so a reviewer sees at once when the
proposed vouchers together EXCEED what the invoice still owes (or a voucher is
proposed for more than it holds), the links already on it (SOFTECH / written /
approved), and duplicate-voucher flags. Read-only; the decisions go through
recon_actions.selection_action.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Max, Sum

from .models import Allocation, APInvoice, MatchCandidate, Payment, ReconException
from .recon_reports import _local

TOL = Decimal('0.01')
ZERO = Decimal('0')
GROUP_ORDERINGS = ('-excess', '-n', '-pending', 'date', '-date', 'value', '-value')


def _invoice_remaining(objs: dict) -> dict:
    """«المتبقي (محسوب)» per invoice — same definition as APInvoice.remaining_calc."""
    links, approved = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for inv_id, origin, s in (Allocation.objects.filter(invoice_id__in=list(objs))
                              .values_list('invoice_id', 'origin').annotate(s=Sum('amount'))):
        if origin == Allocation.ORIGIN_APPROVED:
            approved[inv_id] += s or ZERO
        elif origin in (Allocation.ORIGIN_SOFTECH, Allocation.ORIGIN_WRITTEN):
            links[inv_id] += s or ZERO
    return {i: APInvoice.remaining_from(o.doc_value, o.doc_value_pay, links[i], approved[i])
            for i, o in objs.items()}


def _payment_capacity(payments: dict) -> dict:
    used = defaultdict(lambda: ZERO)
    for pay_id, amt, is_ret in (Allocation.objects.filter(payment_id__in=list(payments))
                                .values_list('payment_id', 'amount', 'invoice__is_return')):
        used[pay_id] += payments[pay_id].allocation_effect(amt or ZERO, bool(is_ret))
    return used


def build_groups(qs, by='invoice', only='multi', order='-excess', page=1, page_size=20) -> dict:
    by = 'payment' if by == 'payment' else 'invoice'
    key = f'{by}_id'
    agg = list(qs.values(key).annotate(n=Count('id'), top=Max('confidence_score')))
    pend = dict(qs.filter(status=MatchCandidate.STATUS_PROPOSED)
                .values_list(key).annotate(s=Sum('proposed_amount')))
    ids = [a[key] for a in agg]
    if by == 'invoice':
        objs = APInvoice.objects.in_bulk(ids)
        cap = _invoice_remaining(objs)
        date_of = {i: o.docdate for i, o in objs.items()}
        value_of = {i: o.doc_value or ZERO for i, o in objs.items()}
    else:
        objs = Payment.objects.in_bulk(ids)
        used = _payment_capacity(objs)
        cap = {i: (o.net_amount or ZERO) - used[i] for i, o in objs.items()}     # net of bound refunds
        date_of = {i: o.voucher_date for i, o in objs.items()}
        value_of = {i: o.amount or ZERO for i, o in objs.items()}

    rows = []
    for a in agg:
        gid = a[key]
        pending = pend.get(gid) or ZERO
        remaining = cap.get(gid, ZERO)
        excess = pending - max(remaining, ZERO)
        rows.append({'id': gid, 'n': a['n'], 'pending': pending, 'remaining': remaining,
                     'excess': excess if excess > TOL else ZERO,
                     'date': date_of.get(gid), 'value': value_of.get(gid, ZERO)})
    if only == 'multi':
        rows = [r for r in rows if r['n'] > 1]
    elif only == 'over':
        rows = [r for r in rows if r['excess'] > 0]
    stats = {'groups': len(rows), 'over': sum(1 for r in rows if r['excess'] > 0),
             'excess_total': sum((r['excess'] for r in rows), ZERO),
             'candidates': sum(r['n'] for r in rows)}

    order = order if order in GROUP_ORDERINGS else '-excess'
    field, rev = order.lstrip('-'), order.startswith('-')
    import datetime
    blank = datetime.date.min if field == 'date' else ZERO
    rows.sort(key=lambda r: (r[field] if r[field] is not None else blank, r['n'], r['id']), reverse=rev)
    start = (max(1, page) - 1) * page_size
    return {'by': by, 'stats': stats, 'count': len(rows), 'rows': rows[start:start + page_size],
            'objects': objs}


def group_payload(built: dict, qs, serialize_candidate, serialize_invoice, serialize_payment) -> dict:
    """Expand one page of groups: every candidate in it + the links already on the
    object + duplicate-voucher flags for every voucher shown."""
    by, rows, objs = built['by'], built['rows'], built['objects']
    key = f'{by}_id'
    page_ids = [r['id'] for r in rows]
    cands = defaultdict(list)
    for c in qs.filter(**{f'{key}__in': page_ids}).order_by('-confidence_score', 'payment__voucher_date', 'id'):
        cands[getattr(c, key)].append(c)
    links = defaultdict(list)
    for a in (Allocation.objects.filter(**{f'{key}__in': page_ids})
              .select_related('payment', 'invoice').order_by('payment__voucher_date', 'id')):
        links[getattr(a, key)].append({
            'origin': a.origin, 'amount': str(a.amount),
            'payment': f'{a.payment.branchcode}/{a.payment.cheqsno}', 'voucher_date': a.payment.voucher_date,
            'voucher_time': _local(a.payment.trans_time),
            'invoice': f'{a.invoice.branchcode}/{a.invoice.docnumber}', 'docdate': a.invoice.docdate,
            'invoice_time': _local(a.invoice.trans_time),
        })
    pay_ids = {c.payment_id for cs in cands.values() for c in cs}
    flags = defaultdict(list)
    for e in ReconException.objects.filter(
            status='open', payment_id__in=pay_ids,
            exception_type__in=[ReconException.TYPE_DUPLICATE_PAYMENT, ReconException.TYPE_MISALLOCATION,
                            ReconException.TYPE_SUSPECT_AMOUNT]):
        flags[e.payment_id].append({'type': e.exception_type, 'label': e.get_exception_type_display(),
                                    'detail': e.detail})
    # a duplicate voucher's twin: same supplier, same amount, same day
    twins = defaultdict(list)
    shown = Payment.objects.filter(id__in=pay_ids)
    by_sig = defaultdict(list)
    for p in Payment.objects.filter(party_id__in={p.party_id for p in shown},
                                    amount__in={p.amount for p in shown},
                                    voucher_date__in={p.voucher_date for p in shown}):
        by_sig[(p.party_id, p.amount, p.voucher_date)].append(p)
    for p in shown:
        sib = [q for q in by_sig[(p.party_id, p.amount, p.voucher_date)] if q.id != p.id]
        if sib:
            twins[p.id] = [f'{q.branchcode}/{q.cheqsno}' for q in sib]
    out = []
    for r in rows:
        obj = objs[r['id']]
        out.append({
            'id': r['id'], 'n': r['n'],
            'pending': str(r['pending']), 'remaining': str(r['remaining']), 'excess': str(r['excess']),
            'object': serialize_invoice(obj) if by == 'invoice' else serialize_payment(obj),
            'links': links[r['id']],
            'candidates': [dict(serialize_candidate(c),
                                payment_flags=flags.get(c.payment_id, []),
                                duplicate_of=twins.get(c.payment_id, []))
                           for c in cands[r['id']]],
        })
    return {'by': by, 'stats': {k: str(v) if isinstance(v, Decimal) else v
                                for k, v in built['stats'].items()},
            'count': built['count'], 'results': out}
