"""
apps/finance/recon_rivals.py — «what else touches this match» for the review grid (owner
2026-09-29): a row must show, on the same line, every OTHER voucher claiming the same
invoice (proposed or already linked) and, when the voucher's serial/note names a DIFFERENT
invoice, that invoice and who holds it — so a duplicate payment or a shifted link is visible
without opening anything. Read-only; one batch of queries per page.
"""
from __future__ import annotations

from collections import defaultdict

from .models import Allocation, APInvoice, MatchCandidate, Payment
from .recon_engine import payment_ref_tokens

ORIGIN = {'softech': 'SOFTECH', 'written': 'مكتوب', 'approved': 'معتمد', 'proposed': 'مقترح'}


def _vlabel(p) -> str:
    return f'{p.branchcode}/{p.cheqsno} ({p.voucher_date}, {p.amount})'


def annotate(rows: list) -> None:
    """Add row['rivals'] (other vouchers on the same invoice) and row['names_other'] (the
    invoice this voucher's reference names, when it is not the proposed one)."""
    if not rows:
        return
    inv_ids = {r['invoice'] for r in rows}
    pay_ids = {r['payment'] for r in rows}
    on_inv = defaultdict(list)                       # invoice → [(payment_id, label, state)]
    for c in (MatchCandidate.objects.filter(invoice_id__in=inv_ids, status='proposed')
              .select_related('payment')):
        on_inv[c.invoice_id].append((c.payment_id, _vlabel(c.payment), 'مقترح' + (f' {c.get_confidence_class_display()}')))
    for a in (Allocation.objects.filter(invoice_id__in=inv_ids, origin__in=['softech', 'written', 'approved'])
              .select_related('payment')):
        on_inv[a.invoice_id].append((a.payment_id, _vlabel(a.payment), f'مربوط {ORIGIN[a.origin]} {a.amount}'))

    pays = {p.id: p for p in Payment.objects.filter(id__in=pay_ids)}
    want = defaultdict(set)                          # (party, branch) → invoice numbers named
    for p in pays.values():
        for t in payment_ref_tokens(p):
            want[(p.party_id, p.branchcode)].add(t.lstrip('0'))
    named = {}
    for (party, branch), nos in want.items():
        for i in APInvoice.objects.filter(party_id=party, branchcode=branch, is_return=False,
                                          docnumber__in=list(nos)):
            named[(party, branch, str(i.docnumber).split('.')[0].lstrip('0'))] = i
    holders = defaultdict(list)
    for a in (Allocation.objects.filter(invoice_id__in=[i.id for i in named.values()],
                                        origin__in=['softech', 'written', 'approved']).select_related('payment')):
        holders[a.invoice_id].append(f'{a.payment.branchcode}/{a.payment.cheqsno} ({ORIGIN[a.origin]})')

    for r in rows:
        r['rivals'] = [{'voucher': lbl, 'state': st} for pid, lbl, st in on_inv.get(r['invoice'], [])
                       if pid != r['payment']]
        p = pays.get(r['payment'])
        r['names_other'] = None
        if p is None:
            continue
        inv_no = str((r.get('invoice_detail') or {}).get('docnumber', '')).split('.')[0].lstrip('0')
        for t in payment_ref_tokens(p):
            i = named.get((p.party_id, p.branchcode, t.lstrip('0')))
            if i is not None and t.lstrip('0') != inv_no:
                h = holders.get(i.id)
                r['names_other'] = {
                    'invoice': f'{i.branchcode}/{str(i.docnumber).split(".")[0]}',
                    'docdate': i.docdate, 'value': i.doc_value,
                    'state': ('مربوطة بـ ' + '، '.join(h)) if h else 'مفتوحة — لم تُسدد',
                }
                break
