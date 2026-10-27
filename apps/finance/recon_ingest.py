"""
apps/finance/recon_ingest.py

Phase-C batch 2 — the pure, SOFTECH-free ingest core for A/P–A/R reconciliation.

The management command (`sync_ap_reconciliation`) fetches read-only rows from
SOFTECH (via apps/finance/queries/sybase_reconciliation.py) and hands them to
`ingest()` here. Keeping the transform/upsert logic pure lets us unit-test the
whole pipeline with fabricated rows — no Sybase, deterministic.

NOTHING here writes to SOFTECH. It only upserts the PostgreSQL mirror
(ReconParty / APInvoice / Payment / Allocation) and flags the historical problem
set (payments with no allocation).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import ReconParty, APInvoice, Payment, Allocation

SUPPLIER_PTCODE = '20'   # personsdata.ptcode for suppliers/distributors (verified)

# doccode → party_type / is_return / direction
_DOCCODE_META = {
    '10':  ('supplier', False),   # purchase (payable)
    '120': ('supplier', True),    # return to supplier
    '115': ('customer', False),   # sale (receivable)
    '30':  ('customer', True),    # customer return
}
_PARTY_DIRECTION = {'supplier': 'out', 'customer': 'in'}


# ── coercion helpers ──────────────────────────────────────────────────────────

def _dec(v) -> Decimal:
    if v in (None, '', 'NULL'):
        return Decimal('0')
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def _as_date(v):
    if v in (None, '', 'NULL'):
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # last resort: leading date token
    try:
        return datetime.datetime.strptime(s[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _as_datetime(v):
    if v in (None, '', 'NULL'):
        return None
    if isinstance(v, datetime.datetime):
        return timezone.make_aware(v) if timezone.is_naive(v) else v
    s = str(v).strip().replace('T', ' ')   # queries serialize datetimes as ISO (with 'T')
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return timezone.make_aware(dt)
        except ValueError:
            continue
    return None


def _s(v) -> str:
    if v in (None, 'NULL'):
        return ''
    return str(v).strip()


def _hash(fields: dict) -> str:
    """Stable sha256 of the SOFTECH-sourced fields — used to detect drift/tamper."""
    payload = json.dumps(fields, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _party_type_for_doccode(doccode: str):
    return _DOCCODE_META.get(_s(doccode), (None, False))


# ── upserts ───────────────────────────────────────────────────────────────────

def upsert_party(personcode, party_type, name='', ptclassif='') -> ReconParty:
    pc = _s(personcode)
    party, created = ReconParty.objects.get_or_create(
        softech_personcode=pc,
        defaults={'party_type': party_type, 'name': _s(name),
                  'ptclassifcode': _s(ptclassif), 'synced_at': timezone.now()},
    )
    if not created:
        changed = []
        if name and party.name != _s(name):
            party.name = _s(name); changed.append('name')
        if ptclassif and party.ptclassifcode != _s(ptclassif):
            party.ptclassifcode = _s(ptclassif); changed.append('ptclassifcode')
        # never silently flip party_type once set (data-integrity signal handled upstream)
        if changed:
            party.synced_at = timezone.now(); changed.append('synced_at')
            party.save(update_fields=changed)
    return party


def upsert_invoice(row: dict, party: ReconParty | None = None) -> APInvoice | None:
    """row = a SOFTECH stktransm dict (doccode 10/120/115/30)."""
    doccode = _s(row.get('doccode'))
    ptype, is_return = _party_type_for_doccode(doccode)
    if ptype is None:
        return None
    branchcode = _s(row.get('branchcode'))
    docnumber  = _s(row.get('docnumber')).split('.')[0]   # 12207.0 → "12207"
    docdate    = _as_date(row.get('docdate'))
    if not (branchcode and docnumber and docdate):
        return None

    personcode = _s(row.get('cust_branch_code')) or _s(row.get('personcode'))
    if party is None:
        party = upsert_party(personcode, ptype)

    src = {
        'doc_value': _s(row.get('docvalue')), 'doc_value_pay': _s(row.get('docvaluepay')),
        'fat': _s(row.get('fatcurrentstatus')), 'due': _s(row.get('docpaydue')),
        'dn2': _s(row.get('docnumber2')),
    }
    defaults = {
        'party': party, 'party_type': ptype, 'is_return': is_return,
        'docnumber2': _s(row.get('docnumber2')).split('.')[0],
        'doc_value': _dec(row.get('docvalue')),
        'doc_value_pay': _dec(row.get('docvaluepay')),
        'fat_status': _s(row.get('fatcurrentstatus')).split('.')[0],
        'due_date': _as_date(row.get('docpaydue')),
        'usercode': _s(row.get('usercode')).split('.')[0],
        'comments': _s(row.get('comments'))[:2000],
        'person_new_bal': _dec(row.get('personnewbal')),
        'trans_time': _as_datetime(row.get('trans_time')),
        'source_hash': _hash(src), 'synced_at': timezone.now(),
    }
    obj, _created = APInvoice.objects.update_or_create(
        branchcode=branchcode, doccode=doccode, docnumber=docnumber, docdate=docdate,
        defaults=defaults,
    )
    return obj


def upsert_payment(row: dict, party_type: str | None = None) -> Payment | None:
    """row = a SOFTECH cheques dict (payment/receipt voucher)."""
    branchcode = _s(row.get('branchcode'))
    cheqsno    = _s(row.get('cheqsno')).split('.')[0]
    if not (branchcode and cheqsno):
        return None
    cheqsno = int(cheqsno)

    # classify party_type: explicit arg wins, else from ptcode (join in the query)
    ptype = party_type
    if ptype is None:
        ptcode = _s(row.get('ptcode'))
        ptype = 'supplier' if ptcode == SUPPLIER_PTCODE else 'customer'
    direction = _PARTY_DIRECTION.get(ptype, 'out')

    personcode = _s(row.get('personcode'))
    # jConnect drops the SELECT alias, so the name arrives under `personname`;
    # some supplier rows have it NULL (real name lives in a branch-level table).
    party_name = _s(row.get('_party_name')) or _s(row.get('personname'))
    party = upsert_party(personcode, ptype, name=party_name)

    src = {
        'amount': _s(row.get('cheqvalue')), 'note': _s(row.get('chequenote')),
        'pnb': _s(row.get('personnewbal')), 'bnb': _s(row.get('banknewbal')),
        'fdc': _s(row.get('financialdoccode')), 'date': _s(row.get('cheqdate')),
    }
    ourcheqsno = _s(row.get('ourcheqsno')).split('.')[0]
    defaults = {
        'party': party, 'party_type': ptype, 'direction': direction,
        'cheqno': _s(row.get('cheqno')),
        'ourcheqsno': int(ourcheqsno) if ourcheqsno.isdigit() else None,
        'financial_doc_code': _s(row.get('financialdoccode')),
        'cheqtype': _s(row.get('cheqtype')),
        'voucher_date': _as_date(row.get('cheqdate')),
        'bankcode': _s(row.get('bankcode')),
        'amount': _dec(row.get('cheqvalue')),
        'note': _s(row.get('chequenote'))[:250],
        'person_new_bal': _dec(row.get('personnewbal')),
        'bank_new_bal': _dec(row.get('banknewbal')),
        'block_inv': _s(row.get('blockinv')) in ('1', 'True', 'true'),
        'usercode': _s(row.get('usercode')).split('.')[0],
        'trans_time': _as_datetime(row.get('trans_time')),
        'source_hash': _hash(src), 'synced_at': timezone.now(),
    }
    obj, _created = Payment.objects.update_or_create(
        branchcode=branchcode, cheqsno=cheqsno, defaults=defaults,
    )
    return obj


def upsert_allocation(row: dict) -> Allocation | None:
    """
    row = a SOFTECH chequestrans dict. Links an existing Payment (voucher) to an
    APInvoice; the invoice may fall outside the ingest window, so we create a stub
    (doc_value filled on a later invoice ingest) rather than dropping the link.
    """
    cheqsno        = _s(row.get('cheqsno')).split('.')[0]
    cheqbranchcode = _s(row.get('cheqbranchcode')) or _s(row.get('branchcode'))
    if not (cheqsno and cheqbranchcode):
        return None
    cheqsno = int(cheqsno)

    try:
        payment = Payment.objects.get(branchcode=cheqbranchcode, cheqsno=cheqsno)
    except Payment.DoesNotExist:
        return None   # voucher not ingested (out of scope) — skip its allocation

    inv_branch = _s(row.get('branchcode'))
    doccode    = _s(row.get('doccode'))
    docnumber  = _s(row.get('docnumber')).split('.')[0]
    docdate    = _as_date(row.get('docdate'))
    if not (inv_branch and doccode and docnumber and docdate):
        return None
    ptype, is_return = _party_type_for_doccode(doccode)

    invoice, _created = APInvoice.objects.get_or_create(
        branchcode=inv_branch, doccode=doccode, docnumber=docnumber, docdate=docdate,
        defaults={'party': payment.party, 'party_type': ptype or payment.party_type,
                  'is_return': is_return, 'synced_at': timezone.now()},
    )

    src = {'paid': _s(row.get('docvaluepaid')), 'paynow': _s(row.get('docvaluepaynow'))}
    # a link OUR writer put in SOFTECH stays 'written' when re-read (it was being
    # re-labelled 'softech', which hid it from reversal and review — 2026-09-28)
    ours = Allocation.objects.filter(payment=payment, invoice=invoice,
                                     origin=Allocation.ORIGIN_WRITTEN).exists()
    defaults = {
        'amount': _dec(row.get('docvaluepaynow')),
        'cumulative_paid': _dec(row.get('docvaluepaid')),
        'origin': Allocation.ORIGIN_WRITTEN if ours else Allocation.ORIGIN_SOFTECH,
        'source_hash': _hash(src), 'synced_at': timezone.now(),
    }
    obj, _created = Allocation.objects.update_or_create(
        payment=payment, invoice=invoice, defaults=defaults,
    )
    return obj


# ── orchestration ─────────────────────────────────────────────────────────────

def ingest(invoices=None, vouchers=None, allocations=None, party_type=None) -> dict:
    """
    Upsert a bounded batch of SOFTECH rows into the mirror and flag the problem set.
    All three lists are lists of dicts (SOFTECH column → value). Returns a stats dict.
    Ordering matters: invoices → vouchers → allocations (allocations reference both).
    """
    stats = {'invoices': 0, 'vouchers': 0, 'allocations': 0,
             'unallocated_flagged': 0, 'skipped': 0}

    for row in (invoices or []):
        if upsert_invoice(row):
            stats['invoices'] += 1
        else:
            stats['skipped'] += 1

    touched_payments: set[int] = set()
    for row in (vouchers or []):
        p = upsert_payment(row, party_type=party_type)
        if p:
            stats['vouchers'] += 1
            touched_payments.add(p.pk)
        else:
            stats['skipped'] += 1

    for row in (allocations or []):
        a = upsert_allocation(row)
        if a:
            stats['allocations'] += 1
            touched_payments.add(a.payment_id)
        else:
            stats['skipped'] += 1

    # Flag the historical problem: a voucher we ingested with no allocation link.
    for pk in touched_payments:
        try:
            p = Payment.objects.get(pk=pk)
        except Payment.DoesNotExist:
            continue
        unalloc = not p.allocations.exists()
        if p.is_unallocated != unalloc:
            p.is_unallocated = unalloc
            p.save(update_fields=['is_unallocated'])
        if unalloc:
            stats['unallocated_flagged'] += 1

    return stats
