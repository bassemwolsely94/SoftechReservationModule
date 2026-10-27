"""
apps/finance/recon_returns.py

RETURNS logic (doc 23 §17). A supplier return (doccode 120) is a credit: SOFTECH
settles it either by NETTING it inside a later مدفوعات (voucher = Σ purchases −
Σ returns, the common case) or by a مقبوضات refund. ReturnLink says which purchase
a return returns (~1 in 4–5 return lines carry it).

  returned_amounts()  purchase id → Σ returned (linked) — capacity & reports deduct it
  open_return_amounts() return id → credit still open (not netted/refunded)
  analyse()           revision items:
     paid_returned  a purchase was paid although it was returned:
                      • PAYMENT AFTER RETURN  → the payment should not have happened
                        (or should have netted the return) — revision
                      • RETURN AFTER PAYMENT  → normal, but the return must now be
                        netted/refunded; if it is still open the supplier owes us
     open_return    a return whose credit is still open — money to recover or to
                    net into the next payment
PostgreSQL only; deterministic; idempotent (stale flags are closed).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from .models import APInvoice, Allocation, ReturnLink, ReconException

ZERO = Decimal('0')
TOL = Decimal('1.00')


def returned_amounts(invoice_qs=None) -> dict:
    qs = ReturnLink.objects.filter(purchase_invoice__isnull=False)
    if invoice_qs is not None:
        qs = qs.filter(purchase_invoice__in=invoice_qs)
    return {r['purchase_invoice_id']: r['s'] or ZERO
            for r in qs.values('purchase_invoice_id').annotate(s=Sum('amount'))}


def open_return_amounts(return_qs) -> dict:
    """Credit still open on each return = value − max(SOFTECH paid, native+written
    links) − approved links (awaiting write)."""
    alloc = defaultdict(lambda: defaultdict(lambda: ZERO))
    for r in (Allocation.objects.filter(invoice__in=[x.id for x in return_qs])
              .values('invoice_id', 'origin').annotate(s=Sum('amount'))):
        alloc[r['invoice_id']][r['origin']] += r['s'] or ZERO
    out = {}
    for ret in return_qs:
        a = alloc[ret.id]
        settled = max(ret.doc_value_pay or ZERO, a['softech'] + a['written']) + a['approved']
        left = (ret.doc_value or ZERO) - settled
        if left >= TOL:
            out[ret.id] = left
    return out


def open_returned_by_purchase(party=None, party_type: str = 'supplier') -> dict:
    """purchase id → Σ credit still OPEN on the returns linked to it. Such a purchase
    is only payable for what was kept, until the return is netted or refunded."""
    links = ReturnLink.objects.filter(purchase_invoice__isnull=False)
    links = links.filter(purchase_invoice__party=party) if party is not None else         links.filter(purchase_invoice__party__party_type=party_type)
    links = list(links.select_related('return_invoice'))
    rets = {l.return_invoice_id: l.return_invoice for l in links}
    open_credit = open_return_amounts(list(rets.values()))
    out = defaultdict(lambda: ZERO)
    for l in links:
        c = min(l.amount, open_credit.get(l.return_invoice_id, ZERO))
        if c > ZERO:
            out[l.purchase_invoice_id] += c
    return dict(out)


def analyse(party_type: str = 'supplier') -> dict:
    from .recon_anomalies import _upsert_exc
    counts = defaultdict(int)
    flagged_paid, flagged_open = set(), set()

    # ── payments on returned purchases ──
    links = (ReturnLink.objects.filter(purchase_invoice__isnull=False,
                                       purchase_invoice__party__party_type=party_type)
             .select_related('purchase_invoice', 'return_invoice', 'purchase_invoice__party'))
    by_purchase = defaultdict(list)
    for l in links:
        by_purchase[l.purchase_invoice_id].append(l)
    pays = defaultdict(list)
    for a in (Allocation.objects.filter(invoice_id__in=list(by_purchase))
              .exclude(origin__in=['proposed', 'reversed']).select_related('payment')):
        pays[a.invoice_id].append(a)
    all_returns = {l.return_invoice_id: l.return_invoice for ls in by_purchase.values() for l in ls}
    open_credit = open_return_amounts(list(all_returns.values()))
    for pid, ls in by_purchase.items():
        if not pays.get(pid):
            continue
        inv = ls[0].purchase_invoice
        returned = sum((l.amount for l in ls), ZERO)
        paid = sum((a.amount for a in pays[pid]), ZERO)
        if paid + returned <= (inv.doc_value or ZERO) + TOL:
            continue       # paid only the part that was kept — consistent
        # paid in full AND returned: correct when the return's credit was taken
        # (netted in a voucher — SOFTECH's normal way — or refunded). It is only a
        # problem while the linked return's credit is still OPEN.
        if not any(open_credit.get(l.return_invoice_id, ZERO) >= TOL for l in ls):
            continue
        first_return = min(l.return_invoice.docdate for l in ls)
        after_return = [a for a in pays[pid] if a.payment.voucher_date and a.payment.voucher_date >= first_return]
        if after_return:
            kind = 'دُفعت بعد إرجاعها — السداد لم يكن يجب أن يتم (أو كان يجب خصم المرتجع)'
            counts['paid_after_return'] += 1
        else:
            kind = 'أُرجعت بعد سدادها — يجب أن يُخصم المرتجع من سداد لاحق أو يُسترد'
            counts['returned_after_payment'] += 1
        rets = ', '.join(f'{l.return_invoice.branchcode}/{l.return_invoice.docnumber} ({l.amount})' for l in ls)
        if _upsert_exc(inv.party, ReconException.TYPE_PAID_RETURNED, 'warning', invoice=inv,
                       detail=f'الفاتورة {inv.branchcode}/{inv.docnumber} ({inv.doc_value}) مسدد منها {paid} '
                              f'ومُرتجع منها {returned} [{rets}] — {kind}'):
            counts['new_flags'] += 1
        flagged_paid.add(inv.id)

    # ── open returns (credit the supplier still owes) ──
    rets = {r.id: r for r in APInvoice.objects.filter(party__party_type=party_type, is_return=True,
                                                      source_hash__gt='').select_related('party')}
    for ret_id, left in open_return_amounts(list(rets.values())).items():
        ret = rets[ret_id]
        counts['open_returns'] += 1
        counts['open_returns_value'] += left
        if _upsert_exc(ret.party, ReconException.TYPE_OPEN_RETURN, 'info', invoice=ret,
                       detail=f'مرتجع {ret.branchcode}/{ret.docnumber} بتاريخ {ret.docdate} قيمته {ret.doc_value} '
                              f'متبقٍّ منه {left} لم يُخصم من سداد ولم يُسترد — مستحق على المورد'):
            counts['new_flags'] += 1
        flagged_open.add(ret.id)

    # stale flags close themselves
    ReconException.objects.filter(exception_type=ReconException.TYPE_PAID_RETURNED, status='open',
                                  party__party_type=party_type).exclude(invoice_id__in=flagged_paid) \
        .update(status='resolved', resolution_notes='أُغلق تلقائيًا')
    ReconException.objects.filter(exception_type=ReconException.TYPE_OPEN_RETURN, status='open',
                                  party__party_type=party_type).exclude(invoice_id__in=flagged_open) \
        .update(status='resolved', resolution_notes='أُغلق تلقائيًا: خُصم المرتجع أو استُرد')
    counts['open_returns_value'] = str(counts['open_returns_value'])
    return dict(counts)
