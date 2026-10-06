"""
apps/finance/recon_anomalies.py

Phase-C batch H — deeper anomaly / risk scan over the reconstructed mirror. Extends
the basic detectors the matching engine already emits (orphan payment, duplicate
payment, old-unpaid invoice) with:

  • duplicate_invoice  — same supplier printed doc-no (docnumber2) + amount on ≥2
                         of our documents ⇒ probable double data-entry.
  • overpayment        — Σ allocations against an invoice exceed its doc_value.
  • anomaly (outlier)  — a payment far above the party's own norm (z-score > 3),
                         a statistical flag for review (never auto-action).
  • misallocation      — SOFTECH linked a payment to invoice B while the payment's
                         note names a different same-party invoice A whose value the
                         payment matches exactly ⇒ a swapped pair (the false-positive
                         pattern shadow-mode surfaced, §19). warning if B's value
                         differs, info if equal (reference swap, no balance effect).

All detectors are READ-ONLY over PostgreSQL, emit ReconException rows (idempotent —
no duplicate OPEN exception for the same (type, invoice/payment)), and NEVER touch
SOFTECH. Anomalies are *risk flags*, not proof of fraud (§13).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

from decimal import Decimal

from .models import ReconParty, ReconException, Allocation

_Z_THRESHOLD = Decimal('3')
_OUTLIER_FLOOR = Decimal('1000')     # ignore tiny-account noise
_OVERPAY_TOL = Decimal('0.01')


def _upsert_exc(party, etype, severity, *, invoice=None, payment=None,
                detail='', anomaly_score=Decimal('0')) -> bool:
    """Create an OPEN exception unless an identical open one already exists."""
    if ReconException.objects.filter(exception_type=etype, party=party, status='open',
                                     invoice=invoice, payment=payment).exists():
        return False
    ReconException.objects.create(
        party=party, invoice=invoice, payment=payment, exception_type=etype,
        severity=severity, detail=detail[:2000], anomaly_score=anomaly_score,
    )
    return True


_DUP_WINDOW_DAYS = 90   # same supplier doc-no + value years apart = number reuse, not a dup


def _duplicate_invoices(party) -> int:
    """
    Same supplier doc-no (docnumber2) + value on ≥2 distinct of our documents
    entered CLOSE IN TIME (≤ _DUP_WINDOW_DAYS) — the signature of a genuine double
    entry, not the year-over-year invoice-number reuse suppliers routinely do.
    """
    import datetime
    n = 0
    groups: dict[tuple, list] = {}
    for inv in party.invoices.all():
        dn2 = (inv.docnumber2 or '').strip()
        if not dn2 or inv.is_return or inv.docdate is None:
            continue
        groups.setdefault((dn2, inv.doc_value), []).append(inv)
    for (dn2, val), invs in groups.items():
        if len({i.docnumber for i in invs}) < 2:
            continue
        # deterministic order; flag any doc that has an EARLIER sibling (different
        # docnumber) within the window — the earliest stays as the "original".
        ordered = sorted(invs, key=lambda i: (i.docdate, str(i.docnumber)))
        for pos, dup in enumerate(ordered):
            earlier_near = [o for o in ordered[:pos]
                            if o.docnumber != dup.docnumber
                            and abs((dup.docdate - o.docdate).days) <= _DUP_WINDOW_DAYS]
            if not earlier_near:
                continue
            if _upsert_exc(party, ReconException.TYPE_DUPLICATE_INVOICE, 'warning',
                           invoice=dup,
                           detail=f'مستند المورد {dn2} بقيمة {val} مكرر خلال {_DUP_WINDOW_DAYS} '
                                  f'يومًا (أصل: فاتورة {earlier_near[0].docnumber})'):
                n += 1
    return n


def _overpayments(party) -> int:
    n = 0
    over_ids = set()
    for inv in party.invoices.all():
        if not inv.source_hash:
            continue    # an unfilled stub (value unknown) is not evidence of over-payment
        if inv.linked_amount > (inv.doc_value or Decimal('0')) + _OVERPAY_TOL:
            over_ids.add(inv.id)
            over = inv.linked_amount - inv.doc_value
            if _upsert_exc(party, ReconException.TYPE_OVERPAYMENT, 'critical', invoice=inv,
                           detail=f'الفاتورة {inv.docnumber} مخصص لها {inv.linked_amount} '
                                  f'من قيمتها {inv.doc_value} (زيادة {over})'):
                n += 1
    # a flag that is no longer true (e.g. a stub now filled with its real value) is closed
    ReconException.objects.filter(
        party=party, exception_type=ReconException.TYPE_OVERPAYMENT, status='open',
    ).exclude(invoice_id__in=over_ids).update(
        status='resolved', resolution_notes='أُغلق تلقائيًا: لم تعد الفاتورة مخصصًا لها أكثر من قيمتها')
    return n


def _payment_outliers(party) -> int:
    amounts = [Decimal(str(p.amount or 0)) for p in party.payments.all() if (p.amount or 0) > 0]
    if len(amounts) < 8:            # need a population to define a norm
        return 0
    mean = sum(amounts) / Decimal(len(amounts))
    var = sum((a - mean) ** 2 for a in amounts) / Decimal(len(amounts))
    std = var.sqrt() if var > 0 else Decimal('0')
    if std == 0:
        return 0
    n = 0
    for p in party.payments.all():
        amt = Decimal(str(p.amount or 0))
        if amt < _OUTLIER_FLOOR:
            continue
        z = (amt - mean) / std
        if z > _Z_THRESHOLD:
            if _upsert_exc(party, ReconException.TYPE_ANOMALY, 'warning', payment=p,
                           anomaly_score=min(z, Decimal('99.99')),
                           detail=f'سند {p.branchcode}/{p.cheqsno} بمبلغ {amt} '
                                  f'أعلى من معدل المورد {mean:.0f} بـ {z:.1f} انحراف'):
                n += 1
    return n


def _misallocations(party) -> int:
    """
    SWAPPED / MIS-ALLOCATED pairs — the false-positive pattern shadow-mode surfaced
    (§19): SOFTECH linked a payment to invoice B, but the payment's own note names a
    DIFFERENT same-party invoice A (and not B) whose value the payment matches EXACTLY.
    Severity: 'warning' when B's value ≠ the payment (money on the wrong invoice),
    'info' when equal (e.g. two 100.00 vouchers crossed — reference swap only).
    Read-only flag for review — never auto-repairs the SOFTECH link.
    """
    from .recon_engine import number_tokens, SCORING_V1
    tol = SCORING_V1['amount_exact_tol']
    minlen = SCORING_V1['min_ref_token_len']
    invoices = list(party.invoices.all())
    if len(invoices) < 2:
        return 0
    by_token: dict[str, list] = {}
    for inv in invoices:
        for key in (str(inv.docnumber or '').lstrip('0'),
                    (inv.docnumber2 or '').strip().lstrip('0')):
            if key:
                by_token.setdefault(key, []).append(inv)

    n = 0
    # NATIVE links only — a link our writer made (audited) is not SOFTECH's mis-allocation,
    # even when the nightly ingest had re-labelled it 'softech' (2026-09-28 relabel bug)
    from .models import ReconAuditEvent
    ours = set(ReconAuditEvent.objects.filter(action='allocation_written', allocation__payment__party=party)
               .values_list('allocation_id', flat=True))
    still = set()
    softech_allocs = (Allocation.objects
                      .filter(origin=Allocation.ORIGIN_SOFTECH, payment__party=party)
                      .exclude(id__in=ours)
                      .select_related('payment', 'invoice'))
    for a in softech_allocs:
        P, I_alloc = a.payment, a.invoice
        pay_amt = Decimal(str(P.amount or 0))
        toks = number_tokens(P.note, minlen)
        if not toks:
            continue
        # invoices the note explicitly references, by our doc-no or the supplier's
        referenced = {inv.id: inv for t in toks for inv in by_token.get(t, [])}
        if I_alloc.id in referenced:      # the note DOES name the settled invoice → fine
            continue
        # settled value ≠ payment ⇒ money sits on the wrong invoice (warning);
        # settled value = payment ⇒ a pure reference swap, balances unaffected (info)
        alloc_amount_matches = abs(pay_amt - (I_alloc.doc_value or Decimal('0'))) <= tol
        severity = 'info' if alloc_amount_matches else 'warning'
        effect = 'تبادل مراجع بلا أثر على الأرصدة' if alloc_amount_matches else 'المبلغ على فاتورة خاطئة'
        for inv in referenced.values():
            if abs(pay_amt - (inv.doc_value or Decimal('0'))) <= tol:
                still.add((P.id, inv.id))
                if _upsert_exc(party, ReconException.TYPE_MISALLOCATION, severity,
                               payment=P, invoice=inv,
                               detail=f'السند {P.branchcode}/{P.cheqsno} بمبلغ {pay_amt} يذكر '
                                      f'الفاتورة {inv.docnumber} (قيمة مطابقة) لكنه مربوط في SOFTECH '
                                      f'بالفاتورة {I_alloc.docnumber} — {effect}'):
                    n += 1
                break
    # a mis-link that is gone (reversed / corrected / re-paired) closes its own flag —
    # an open stale flag kept holding good matches (owner case 170/53662 → 13073)
    for e in ReconException.objects.filter(party=party, exception_type=ReconException.TYPE_MISALLOCATION,
                                           status='open'):
        if (e.payment_id, e.invoice_id) not in still:
            e.status, e.resolution_notes = 'resolved', 'أُغلق تلقائيًا: لم يعد السند مربوطًا بفاتورة خاطئة'
            e.save(update_fields=['status', 'resolution_notes'])
    return n


def scan(party_type: str | None = None, personcode: str | None = None) -> dict:
    """Run all H detectors over the scoped parties. Returns per-type counts."""
    parties = ReconParty.objects.all()
    if party_type:
        parties = parties.filter(party_type=party_type)
    if personcode:
        parties = parties.filter(softech_personcode=personcode)

    counts = {'duplicate_invoice': 0, 'overpayment': 0, 'anomaly': 0,
              'misallocation': 0, 'parties': 0}
    for party in parties:
        counts['duplicate_invoice'] += _duplicate_invoices(party)
        counts['overpayment']       += _overpayments(party)
        counts['anomaly']           += _payment_outliers(party)
        counts['misallocation']     += _misallocations(party)
        counts['parties'] += 1
    # returns: purchases paid although returned + returns the supplier still owes
    from .recon_returns import analyse as analyse_returns
    counts['returns'] = analyse_returns(party_type or 'supplier')
    from .recon_actions import flag_written_for_review
    counts['written_review'] = flag_written_for_review(party_type or 'supplier')
    return counts
