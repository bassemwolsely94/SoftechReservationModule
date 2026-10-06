"""
apps/finance/recon_bindings.py — bind each مقبوضات to what it belongs to (owner 2026-09-29).

  1. REFUND → PAYMENT: a receipt whose note or inner serial names a مدفوعات of the same
     supplier and branch, dated on/before it (≤ 60 days) and larger than it → the
     receipt refunded PART of that payment («رد فرق النقدى ادخال رقم 31504»). The
     receipt's bound_payment is set and the payment's refunded_amount = Σ such receipts;
     every matcher then uses the payment NET (Payment.net_amount).
  2. RECEIPT → PURCHASE INVOICE: a receipt (not bound above, not a chain reversal) whose
     note or inner serial names a purchase invoice of the same supplier and branch, dated
     within 120 days before it → bound_invoice + a ReconException receipt_on_invoice for
     the owner to decide (money back → owed again, or a credit → owed less). Numbers are
     NOT changed until decided.
  3. CHAIN PARTNERS: every member of a مدفوعات → مقبوضات → مدفوعات correction chain gets
     a readable line naming the others, so the pairing is visible wherever a voucher is.

Mirror only — nothing here writes to SOFTECH. Deterministic and idempotent: bindings
are recomputed from scratch each run (a binding that no longer holds is cleared).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .models import APInvoice, Payment, ReconException
from .recon_engine import payment_ref_tokens

ZERO = Decimal('0')
REFUND_WINDOW_DAYS = 60
INVOICE_WINDOW_DAYS = 120
ROLE_LBL = {'reversed': 'صرف مُلغى', 'reversal': 'مقبوضات إلغاء', 'reissue': 'صرف تصحيحي', 'refund': 'مقبوضات'}


def _label(p) -> str:
    return f'{ROLE_LBL.get(p.chain_role, "سند")} {p.branchcode}/{p.cheqsno} ({p.voucher_date}, {p.amount})'


def bind_all(party_type: str = 'supplier') -> dict:
    from .recon_anomalies import _upsert_exc
    pays = list(Payment.objects.filter(party_type=party_type).select_related('party'))
    by_key = {(p.party_id, p.branchcode, p.cheqsno): p for p in pays}
    pay_by_id = {p.id: p for p in pays}
    stats = defaultdict(int)

    # ── 1. refund → payment ────────────────────────────────────────────────
    bound_pay, bind_note, refunded = {}, {}, defaultdict(lambda: ZERO)
    receipts = [p for p in pays if p.is_receipt and p.chain_role not in ('reversal', 'reversed')]
    for r in sorted(receipts, key=lambda p: (p.voucher_date or p.trans_time, p.id)):
        cands = []
        for t in payment_ref_tokens(r):
            if not t.isdigit():
                continue
            q = by_key.get((r.party_id, r.branchcode, int(t)))
            if (q and not q.is_receipt and q.chain_role not in ('reversed',)
                    and q.voucher_date and r.voucher_date
                    and 0 <= (r.voucher_date - q.voucher_date).days <= REFUND_WINDOW_DAYS
                    and (q.amount or ZERO) > (r.amount or ZERO) + refunded.get(q.id, ZERO)):
                cands.append(q)
        if not cands:
            continue
        q = min(cands, key=lambda x: (r.voucher_date - x.voucher_date).days)
        bound_pay[r.id] = q.id
        refunded[q.id] += r.amount or ZERO
        bind_note[r.id] = (f'↩ يسترد جزءًا من سند الصرف {q.branchcode}/{q.cheqsno} ({q.voucher_date}, {q.amount}) '
                           f'— صافي السند بعد الاسترداد {q.amount - refunded[q.id]}')
        stats['refund_to_payment'] += 1
    refunded = {k: v for k, v in refunded.items() if v > ZERO}
    for pid, total in refunded.items():
        refs = [p for p in receipts if bound_pay.get(p.id) == pid]
        bind_note[pid] = ('↩ مسترد منه بمقبوضات: ' + ' · '.join(f'{r.branchcode}/{r.cheqsno} ({r.voucher_date}, {r.amount})'
                                                             for r in refs)
                          + f' — الصافي المطابَق {pay_by_id[pid].amount - total}')

    # ── 2. receipt → purchase invoice (owner decides the meaning) ────────────
    invs = defaultdict(list)
    for i in APInvoice.objects.filter(party__party_type=party_type, is_return=False).only(
            'id', 'party_id', 'branchcode', 'docnumber', 'docdate', 'doc_value', 'doc_value_pay'):
        invs[(i.party_id, i.branchcode, str(i.docnumber).split('.')[0].lstrip('0'))].append(i)
    bound_inv, flagged = {}, set()
    for r in receipts:
        if r.id in bound_pay:
            continue
        hits = [i for t in payment_ref_tokens(r) for i in invs.get((r.party_id, r.branchcode, t.lstrip('0')), [])
                if i.docdate and r.voucher_date and 0 <= (r.voucher_date - i.docdate).days <= INVOICE_WINDOW_DAYS]
        if not hits:
            continue
        inv = min(hits, key=lambda i: (r.voucher_date - i.docdate).days)
        bound_inv[r.id] = inv.id
        bind_note[r.id] = (f'🔗 يشير لفاتورة الشراء {inv.branchcode}/{inv.docnumber} ({inv.docdate}, {inv.doc_value}) '
                           f'— استرداد أم خصم؟ يحتاج تحديد')
        stats['receipt_to_invoice'] += 1
        flagged.add((r.id, inv.id))
        if _upsert_exc(r.party, ReconException.TYPE_RECEIPT_ON_INVOICE, 'warning', invoice=inv, payment=r,
                       detail=(f'مقبوضات {r.branchcode}/{r.cheqsno} ({r.voucher_date}) بقيمة {r.amount} تشير للفاتورة '
                               f'{inv.branchcode}/{inv.docnumber} ({inv.docdate}) قيمتها {inv.doc_value} والمسدد منها '
                               f'{inv.doc_value_pay}. حدد: استرداد (الفاتورة مستحقة مجددًا بهذا المبلغ) أم خصم '
                               f'(يقلل المستحق على الفاتورة). لم تتغير الأرقام حتى القرار.')):
            stats['new_flags'] += 1

    # ── 3. chain partners (readable) ─────────────────────────────────────────
    chains = defaultdict(list)
    for p in pays:
        if p.chain_key:
            chains[p.chain_key].append(p)
    partners = {}
    for members in chains.values():
        for p in members:
            others = [_label(o) for o in sorted(members, key=lambda o: (o.voucher_date, o.cheqsno)) if o.id != p.id]
            partners[p.id] = ('⛓ ' + ' · '.join(others))[:300] if others else ''

    # ── persist (only what changed) ──────────────────────────────────────────
    changed = []
    for p in pays:
        new = (bound_pay.get(p.id), bound_inv.get(p.id), refunded.get(p.id, ZERO),
               bind_note.get(p.id, '')[:300], partners.get(p.id, ''))
        old = (p.bound_payment_id, p.bound_invoice_id, p.refunded_amount or ZERO, p.bind_note, p.chain_partners)
        if new != old:
            (p.bound_payment_id, p.bound_invoice_id, p.refunded_amount, p.bind_note, p.chain_partners) = new
            changed.append(p)
    Payment.objects.bulk_update(changed, ['bound_payment', 'bound_invoice', 'refunded_amount',
                                          'bind_note', 'chain_partners'], batch_size=1000)
    # a receipt→invoice flag whose binding no longer holds closes itself
    for e in ReconException.objects.filter(exception_type=ReconException.TYPE_RECEIPT_ON_INVOICE,
                                           status='open', party__party_type=party_type):
        if (e.payment_id, e.invoice_id) not in flagged:
            e.status, e.resolution_notes = 'resolved', 'أُغلق تلقائيًا: لم يعد الربط قائمًا'
            e.save(update_fields=['status', 'resolution_notes'])
    stats['updated'] = len(changed)
    stats['payments_with_refunds'] = len(refunded)
    return dict(stats)
