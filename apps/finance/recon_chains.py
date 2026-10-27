"""
apps/finance/recon_chains.py

Voucher CORRECTION CHAINS (doc 23 §17) — owner-confirmed logic (2026-09-26):

    a wrong مدفوعات (cheqtype 20) is cancelled by a SAME-AMOUNT مقبوضات (cheqtype 10)
    to the SAME supplier shortly after; a following same-amount مدفوعات — to the
    same supplier or to ANOTHER one (money posted to the wrong account) — is the
    corrected payment.

Evidence (SOFTECH mirror, 520 receipts): 293 follow their payment the SAME day,
217 sit within 3 serial numbers of it; 78 are re-issued to another supplier and
13 to the same supplier, mostly the same day on the next serial.

Roles written on Payment.chain_role:
  reversed  the cancelled payment — NEVER settles an invoice
  reversal  the receipt that cancels it — never settles anything either
  reissue   the corrected payment — a normal payment, tagged for traceability
  refund    a receipt with no payment before it (supplier refund, e.g. for a return)

Deterministic, idempotent (recomputed from scratch each run), PostgreSQL only.
"""
from __future__ import annotations

from collections import defaultdict

from .models import Payment, Allocation, ReconException

REVERSAL_WINDOW_DAYS = 14   # payment → its cancelling receipt
REISSUE_WINDOW_DAYS = 3     # receipt → the corrected payment


def _serial_gap(a: Payment, b: Payment) -> int:
    if a.branchcode != b.branchcode:
        return 10 ** 9
    return abs(int(a.cheqsno) - int(b.cheqsno))


def detect_chains(party_type: str = 'supplier') -> dict:
    pays = list(Payment.objects.filter(party_type=party_type)
                .only('id', 'party_id', 'branchcode', 'cheqsno', 'cheqtype', 'amount',
                      'voucher_date', 'chain_role', 'chain_key', 'chain_note'))
    receipts = sorted((p for p in pays if (p.cheqtype or '').strip() == '10' and p.voucher_date),
                      key=lambda p: (p.voucher_date, p.id))
    payments_by_party_amt = defaultdict(list)
    payments_by_amt = defaultdict(list)
    for p in pays:
        if (p.cheqtype or '').strip() == '20' and p.voucher_date:
            payments_by_party_amt[(p.party_id, p.amount)].append(p)
            payments_by_amt[p.amount].append(p)

    role, key, note = {}, {}, {}
    used = set()
    counts = defaultdict(int)
    for r in receipts:
        before = [p for p in payments_by_party_amt.get((r.party_id, r.amount), [])
                  if p.id not in used and 0 <= (r.voucher_date - p.voucher_date).days <= REVERSAL_WINDOW_DAYS]
        ck = f'CH{r.id}'
        if not before:
            role[r.id], key[r.id] = Payment.CHAIN_REFUND, ck
            note[r.id] = 'مقبوضات بلا سند صرف سابق بنفس المبلغ — استرداد من المورد'
            counts['refund'] += 1
            continue
        p1 = min(before, key=lambda p: ((r.voucher_date - p.voucher_date).days, _serial_gap(p, r)))
        used.add(p1.id)
        role[p1.id], key[p1.id] = Payment.CHAIN_REVERSED, ck
        role[r.id], key[r.id] = Payment.CHAIN_REVERSAL, ck
        note[p1.id] = f'أُلغي بسند مقبوضات {r.branchcode}/{r.cheqsno} بتاريخ {r.voucher_date}'
        note[r.id] = f'يلغي سند الصرف {p1.branchcode}/{p1.cheqsno} بتاريخ {p1.voucher_date}'
        counts['reversal'] += 1

        after = [p for p in payments_by_amt.get(r.amount, [])
                 if p.id not in used and p.id != p1.id
                 and 0 <= (p.voucher_date - r.voucher_date).days <= REISSUE_WINDOW_DAYS]
        if after:
            p2 = min(after, key=lambda p: ((p.voucher_date - r.voucher_date).days,
                                           _serial_gap(p, r), p.party_id != r.party_id))
            used.add(p2.id)
            same = p2.party_id == r.party_id
            role[p2.id], key[p2.id] = Payment.CHAIN_REISSUE, ck
            note[p2.id] = (f'سند صرف تصحيحي بعد إلغاء {p1.branchcode}/{p1.cheqsno}'
                           + ('' if same else ' — كان مسجلاً على مورد آخر'))
            note[r.id] += f' — ثم أُعيد الصرف بالسند {p2.branchcode}/{p2.cheqsno}' + ('' if same else ' لمورد آخر')
            counts['reissue_same_supplier' if same else 'reissue_other_supplier'] += 1

    changed = []
    for p in pays:
        new = (role.get(p.id, ''), key.get(p.id, ''), note.get(p.id, '')[:250])
        if (p.chain_role, p.chain_key, p.chain_note) != new:
            p.chain_role, p.chain_key, p.chain_note = new
            changed.append(p)
    Payment.objects.bulk_update(changed, ['chain_role', 'chain_key', 'chain_note'], batch_size=2000)
    counts['changed'] = len(changed)
    counts['exceptions'] = _emit_chain_exceptions(party_type)
    return dict(counts)


def _emit_chain_exceptions(party_type: str) -> int:
    """Revision items: SOFTECH-native links that use a cancelled payment, and every
    correction that moved money to another supplier (tracked, informational)."""
    from .recon_anomalies import _upsert_exc
    n = 0
    for a in (Allocation.objects.filter(origin=Allocation.ORIGIN_SOFTECH,
                                        payment__party_type=party_type,
                                        payment__chain_role=Payment.CHAIN_REVERSED)
              .select_related('payment', 'invoice', 'payment__party')):
        p = a.payment
        if _upsert_exc(p.party, ReconException.TYPE_CANCELLED, 'warning', payment=p, invoice=a.invoice,
                       detail=f'سند الصرف {p.branchcode}/{p.cheqsno} ({a.amount}) مربوط في SOFTECH بالفاتورة '
                              f'{a.invoice.docnumber} لكنه {p.chain_note} — الفاتورة قد تظهر مسددة بالخطأ'):
            n += 1
    for p in (Payment.objects.filter(party_type=party_type, chain_role=Payment.CHAIN_REISSUE,
                                     chain_note__contains='مورد آخر').select_related('party')):
        if _upsert_exc(p.party, ReconException.TYPE_SUPPLIER_MISMATCH, 'info', payment=p,
                       detail=f'سند الصرف {p.branchcode}/{p.cheqsno} ({p.amount}): {p.chain_note}'):
            n += 1
    return n


def excluded_payment_ids(party_type: str = 'supplier') -> set:
    """Payments that must never settle anything (cancelled payment + its reversal)."""
    return set(Payment.objects.filter(
        party_type=party_type,
        chain_role__in=[Payment.CHAIN_REVERSED, Payment.CHAIN_REVERSAL],
    ).values_list('id', flat=True))
