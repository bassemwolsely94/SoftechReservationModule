"""
apps/finance/recon_balances.py

Phase-C batch F — حصر (supplier historical reconciliation). Two pure pieces:

  apply_balances(rows)      — upsert SOFTECH balance snapshots onto ReconParty
                              (softech_balance = Σcredit−Σdebit, opening_balance),
                              also backfilling name/ptclassifcode (fixes blank names).

  build_ledger_timeline(party) — a chronological event stream over the mirror
                              (invoices + payments) with a running "owed" balance,
                              plus the reconciliation equation and the variance vs
                              SOFTECH's recorded balance.

Everything here is read-only w.r.t. SOFTECH and computed from the PG mirror + the
balance snapshot. Sign convention: OWED (positive = we owe the supplier), so
  Expected Closing = Opening + Purchases − Returns − Payments
is directly comparable to softech_balance (Σcredit − Σdebit).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import ReconParty
from . import recon_labels as L


def _dec(v) -> Decimal:
    if v in (None, '', 'NULL'):
        return Decimal('0')
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def apply_balances(rows: list[dict]) -> dict:
    """
    rows = output of queries.sybase_reconciliation.get_party_balances():
      {personcode, personname, ptcode, ptclassifcode, softech_balance, opening_balance}
    Updates the matching ReconParty. Returns {updated, missing}.
    """
    updated = missing = 0
    now = timezone.now()
    for r in rows:
        pc = str(r.get('personcode') or '').strip()
        if not pc:
            continue
        try:
            party = ReconParty.objects.get(softech_personcode=pc)
        except ReconParty.DoesNotExist:
            missing += 1
            continue
        party.softech_balance    = _dec(r.get('softech_balance'))
        party.softech_balance_at = now
        party.opening_balance    = _dec(r.get('opening_balance'))
        name = str(r.get('personname') or '').strip()
        if name and party.name != name:
            party.name = name
        ptc = str(r.get('ptclassifcode') or '').strip()
        if ptc:
            party.ptclassifcode = ptc
        party.save(update_fields=['softech_balance', 'softech_balance_at',
                                  'opening_balance', 'name', 'ptclassifcode'])
        updated += 1
    return {'updated': updated, 'missing': missing}


def _latest_snapshot_owed(party: ReconParty):
    """
    SOFTECH's own closing balance in OWED convention, from the per-document
    personnewbal snapshot of the party's most recent document (invoice or payment).
    personnewbal is signed (negative = we owe) ⇒ owed = −personnewbal. Returns None
    when no snapshot/date is available (older ingests before F2).
    """
    # Require trans_time — it is the F2 marker that a snapshot was captured
    # (person_new_bal defaults to 0, so it can't distinguish "unset" from a real 0).
    best = None  # (sort_key, personnewbal)
    for i in party.invoices.all():
        if i.trans_time is not None:
            k = (i.trans_time, 0)
            if best is None or k > best[0]:
                best = (k, i.person_new_bal)
    for p in party.payments.all():
        if p.trans_time is not None:
            k = (p.trans_time, 1)   # payment sorts after a same-instant invoice
            if best is None or k > best[0]:
                best = (k, p.person_new_bal)
    if best is None:
        return None
    return -(best[1] or Decimal('0'))


def reconciliation_equation(party: ReconParty) -> dict:
    """
    Two independent views of the closing balance (OWED convention):

    • MODEL     : Opening + Purchases − Returns − Payments   (our txn reconstruction)
    • SNAPSHOT  : −(latest document's personnewbal)          (SOFTECH's own running balance)
    • SOFTECH   : personsdata Σcredit − Σdebit               (the master balance)

    Splitting the variance tells us WHERE a gap lives:
      model_vs_snapshot   = SNAPSHOT − MODEL   → SOFTECH-posting difference: personnewbal moves
                                                  by more than net docvalue/cheqvalue. VERIFIED
                                                  for supplier 4471 it is NOT tax (origintaxp=0,
                                                  line tax ≈0, voucher deductions=0) nor line-gross
                                                  (≈docvalue) — the extra personcredit has a source
                                                  outside the purchase/payment docs (manual/other
                                                  postings), not deterministically recoverable from
                                                  available fields. The SNAPSHOT is authoritative.
      snapshot_vs_softech = SOFTECH − SNAPSHOT → should be ≈0 (validates the snapshot trail)
      unexplained_variance= SOFTECH − MODEL    → total (kept for back-compat)
    """
    invoices = party.invoices.all()
    payments = party.payments.all()
    purchases = sum((i.doc_value for i in invoices if not i.is_return), start=Decimal('0'))
    returns   = sum((i.doc_value for i in invoices if i.is_return), start=Decimal('0'))
    paid      = sum((p.amount for p in payments), start=Decimal('0'))
    opening   = party.opening_balance or Decimal('0')
    expected  = opening + purchases - returns - paid
    softech   = party.softech_balance or Decimal('0')
    snapshot  = _latest_snapshot_owed(party)

    eq = {
        'opening_balance': opening,
        'purchases': purchases,
        'returns': returns,
        'payments': paid,
        'expected_closing': expected,          # MODEL
        'snapshot_balance': snapshot,          # SOFTECH running-balance snapshot (may be None)
        'softech_balance': softech,            # personsdata master
        'unexplained_variance': softech - expected,
    }
    if snapshot is not None:
        eq['model_vs_snapshot']   = snapshot - expected
        eq['snapshot_vs_softech'] = softech - snapshot
    return eq


def build_ledger_timeline(party: ReconParty) -> dict:
    """
    Chronological حصر ledger: every invoice (+purchase / −return) and payment
    (−) as a signed event with a running owed balance from the opening.
    """
    events: list[dict] = []
    for inv in party.invoices.all():
        delta = -inv.doc_value if inv.is_return else inv.doc_value
        events.append({
            'kind': 'return' if inv.is_return else 'purchase',
            'date': inv.docdate,
            '_ts': inv.trans_time,
            '_seq': 0,   # invoice sorts before a same-instant payment
            'ref': f'{inv.doccode}/{inv.docnumber}',
            'branch': L.branch_label(inv.branchcode),
            'user': L.user_label(inv.usercode),
            'note': inv.comments or '',
            'docnumber': inv.docnumber,
            'docnumber2': inv.docnumber2,
            'delta': delta,
            'linked': inv.linked_amount,
            'unlinked': inv.unlinked_amount,
            # SOFTECH's own balance AFTER this doc (owed convention)
            'softech_balance_after': -(inv.person_new_bal or Decimal('0')),
            'invoice_id': inv.id,
        })
    for p in party.payments.all():
        events.append({
            'kind': 'payment',
            'date': p.voucher_date,
            '_ts': p.trans_time,
            '_seq': 1,
            'ref': f'سند {p.branchcode}/{p.cheqsno}',
            'branch': L.branch_label(p.branchcode),
            'user': L.user_label(p.usercode),
            'cheqsno': p.cheqsno,
            'note': p.note,
            'delta': -(p.amount or Decimal('0')),
            'allocated': p.allocated_amount,
            'unallocated': p.unallocated_amount,
            'is_unallocated': p.is_unallocated,
            'softech_balance_after': -(p.person_new_bal or Decimal('0')),
            'payment_id': p.id,
        })

    # chronological by precise trans_time when present, else date; then kind.
    _now = timezone.now()

    def _sortkey(e):
        ts = e['_ts']
        if ts is None and e['date'] is not None:
            ts = timezone.make_aware(
                datetime.datetime.combine(e['date'], datetime.time.min))
        return (ts is None, ts or _now, e['_seq'])

    events.sort(key=_sortkey)

    # MODEL running balance (opening + Σdelta) as a cross-check alongside the
    # SOFTECH snapshot trail carried on each event.
    running = party.opening_balance or Decimal('0')
    for e in events:
        running += e['delta']
        e['running_balance'] = running        # model cross-check
        e.pop('_ts', None); e.pop('_seq', None)

    return {
        'equation': reconciliation_equation(party),
        'events': events,
        'event_count': len(events),
    }
