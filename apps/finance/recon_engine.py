"""
apps/finance/recon_engine.py

Phase-C batch 3 — the reconciliation MATCHING ENGINE (read-only proposals only).

Over the ingested mirror (recon_ingest / C2) it reconstructs the missing
invoice↔payment links: for each party it generates scored MatchCandidates with
explainable MatchEvidence, resolves them globally (capacity-aware, not naive
greedy), marks conflicts, and emits ReconExceptions (orphan payment, duplicate
payment, old-unpaid invoice).

NOTHING here writes to SOFTECH and it does NOT create Allocations — it only
proposes. Human approval (C-E) turns a proposal into an allocation; write-back is
Phase G (gated). Weights/thresholds live in a VERSIONED config (SCORING_V1 /
RULES_VERSION) — auditable, not buried magic numbers (§9 of the brief).

Core relationships handled (§10):
  • 1 payment → 1 invoice (exact / partial)
  • 1 payment → N invoices     (capacity split across invoices)
  • N payments → 1 invoice     (capacity accumulates on the invoice)
Matching target per invoice = its UNLINKED amount (doc_value − Σ allocations),
so an invoice already marked paid in SOFTECH but with no chequestrans link is
still matchable (the historical problem).

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

from .models import (
    ReconParty, APInvoice, Payment, MatchCandidate, MatchEvidence,
    ReconException, ReconciliationRun, ReconAuditEvent,
)

RULES_VERSION = 'v1'
# a person's «send to further review» on a proposal (recon_actions.HOLD_PREFIX + tag);
# survives the nightly re-run and is never auto-approved
MANUAL_HOLD_PREFIX = 'يحتاج مراجعة: مراجعة يدوية'

# All weights sum to 100 when every signal is exact → confidence is a real %.
SCORING_V1 = {
    'weights': {
        'amount':    Decimal('45'),
        'reference': Decimal('35'),
        'temporal':  Decimal('15'),
        'branch':    Decimal('5'),
    },
    'amount_exact_tol':      Decimal('0.01'),   # ≤ this diff ⇒ exact
    'amount_partial_factor': Decimal('0.60'),   # payment covers part of the invoice
    'amount_over_factor':    Decimal('0.50'),   # payment exceeds the unlinked amount
    'temporal_window_days':  120,
    'temporal_ideal_days':   45,                # ≤ this ⇒ full temporal score
    'min_ref_token_len':     3,                 # ignore 1–2 digit "numbers"
    'high_threshold':        Decimal('85'),
    'medium_threshold':      Decimal('60'),
    'conflict_delta':        Decimal('8'),      # top-2 within this ⇒ conflict
    'unpaid_old_days':       90,
    'duplicate_days':        3,
}

_NUM_RE = re.compile(r'\d+')


# ── small helpers ─────────────────────────────────────────────────────────────

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def number_tokens(text: str, min_len: int = 3) -> set[str]:
    """Digit runs of ≥min_len, with leading zeros preserved AND stripped variants.
    Arabic-Indic / Persian digits (cashiers type «رقم ١٢٣٤١») are folded to ASCII."""
    out: set[str] = set()
    for tok in _NUM_RE.findall((text or '').translate(_DIGITS)):
        tok = tok.translate(_DIGITS)
        if len(tok) >= min_len:
            out.add(tok)
            stripped = tok.lstrip('0')
            if stripped and len(stripped) >= min_len:
                out.add(stripped)
    return out


def cheqno_token(payment: Payment, min_len: int = 3) -> str:
    """The voucher's inner مسلسل (`cheqno`) when it is a plain number. Cashiers often
    type the settled invoice number there (SOFTECH ground truth: equals the allocated
    invoice 8,801× vs another invoice of the same supplier 443× ⇒ 95.2% alone)."""
    q = (payment.cheqno or '').strip().translate(_DIGITS).split('.')[0].lstrip('0')
    return q if q.isdigit() and len(q) >= min_len else ''


def is_receipt_voucher(payment: Payment) -> bool:
    """cheques.cheqtype '10' = مقبوضات — money RECEIVED from the supplier (refund,
    return settlement, «دخول خطأ» reversal). SOFTECH allocates these to RETURNS
    (47 of 51 native links); they must never pay a purchase invoice."""
    return (payment.cheqtype or '').strip() == '10'


def payment_ref_tokens(payment: Payment, min_len: int = 3) -> set[str]:
    """Every invoice-number-like token a voucher carries: note digits + cheqno."""
    toks = number_tokens(payment.note, min_len)
    q = cheqno_token(payment, min_len)
    if q:
        toks.add(q)
    return toks


def _linked(invoice: APInvoice) -> Decimal:
    return sum((a.amount for a in invoice.allocations.all()), start=Decimal('0'))


def _unlinked(invoice: APInvoice) -> Decimal:
    return (invoice.doc_value or Decimal('0')) - _linked(invoice)


def _unallocated(payment: Payment) -> Decimal:
    # signed: a return netted inside a payment voucher is a credit (see Payment.allocation_effect)
    used = sum((payment.allocation_effect(a.amount, a.invoice.is_return)
                for a in payment.allocations.select_related('invoice')), start=Decimal('0'))
    # NET of refunds bound to it (a مقبوضات that returned part of this payment)
    return (payment.net_amount or Decimal('0')) - used


# ── scoring ───────────────────────────────────────────────────────────────────

def score_candidate(invoice: APInvoice, payment: Payment,
                    inv_unlinked: Decimal, pay_unalloc: Decimal,
                    cfg: dict = SCORING_V1) -> tuple[Decimal, list[dict]]:
    """Return (score 0–100, evidence[]) for one (invoice, payment) pair."""
    w = cfg['weights']
    ev: list[dict] = []

    # ── amount ────────────────────────────────────────────────────────────────
    diff = abs(pay_unalloc - inv_unlinked)
    if diff <= cfg['amount_exact_tol']:
        ev.append(_e('amount', 'exact', w['amount'], w['amount'],
                     f'{pay_unalloc} = {inv_unlinked}'))
    elif pay_unalloc < inv_unlinked:
        contrib = (w['amount'] * cfg['amount_partial_factor']).quantize(Decimal('0.001'))
        ev.append(_e('amount', 'approximate', w['amount'], contrib,
                     f'دفع جزئي {pay_unalloc} من {inv_unlinked} (متبقٍّ {inv_unlinked - pay_unalloc})'))
    else:  # payment exceeds this invoice's unlinked amount → may cover more
        contrib = (w['amount'] * cfg['amount_over_factor']).quantize(Decimal('0.001'))
        ev.append(_e('amount', 'approximate', w['amount'], contrib,
                     f'المبلغ {pay_unalloc} يفوق المتبقي {inv_unlinked} (فائض {pay_unalloc - inv_unlinked})'))

    # ── reference (invoice serial found in the voucher note) ───────────────────
    tokens = number_tokens(payment.note, cfg['min_ref_token_len'])
    q = cheqno_token(payment, cfg['min_ref_token_len'])
    inv_no  = str(invoice.docnumber).split('.')[0].lstrip('0')
    inv_no2 = str(invoice.docnumber2).lstrip('0') if invoice.docnumber2 else ''
    if inv_no and inv_no in tokens:
        ev.append(_e('reference', 'exact', w['reference'], w['reference'],
                     f'رقم الفاتورة {invoice.docnumber} موجود في الملاحظات "{payment.note}"'))
    elif inv_no and q == inv_no:
        ev.append(_e('reference', 'exact', w['reference'], w['reference'],
                     f'رقم الفاتورة {invoice.docnumber} في مسلسل السند الداخلي (cheqno)'))
    elif inv_no2 and inv_no2 in tokens:
        ev.append(_e('reference', 'exact', w['reference'], w['reference'],
                     f'رقم مستند المورد {invoice.docnumber2} في الملاحظات'))
    else:
        ev.append(_e('reference', 'mismatch', w['reference'], Decimal('0'),
                     'لا يوجد رقم فاتورة مطابق في الملاحظات'))

    # ── temporal ───────────────────────────────────────────────────────────────
    if payment.voucher_date and invoice.docdate:
        delta = (payment.voucher_date - invoice.docdate).days
        window, ideal = cfg['temporal_window_days'], cfg['temporal_ideal_days']
        if 0 <= delta <= ideal:
            ev.append(_e('temporal', 'exact', w['temporal'], w['temporal'], f'{delta} يوم بعد الفاتورة'))
        elif ideal < delta <= window:
            frac = Decimal(window - delta) / Decimal(window - ideal)
            contrib = (w['temporal'] * frac).quantize(Decimal('0.001'))
            ev.append(_e('temporal', 'approximate', w['temporal'], contrib, f'{delta} يوم بعد الفاتورة'))
        elif -7 <= delta < 0:
            contrib = (w['temporal'] * Decimal('0.3')).quantize(Decimal('0.001'))
            ev.append(_e('temporal', 'approximate', w['temporal'], contrib,
                        f'الدفع قبل الفاتورة بـ{-delta} يوم'))
        else:
            ev.append(_e('temporal', 'mismatch', w['temporal'], Decimal('0'),
                        f'فارق {delta} يوم خارج النافذة'))

    # ── branch ─────────────────────────────────────────────────────────────────
    if payment.branchcode and payment.branchcode == invoice.branchcode:
        ev.append(_e('branch', 'exact', w['branch'], w['branch'], f'نفس الفرع {invoice.branchcode}'))
    else:
        ev.append(_e('branch', 'mismatch', w['branch'], Decimal('0'),
                     f'فرع مختلف ({payment.branchcode} ≠ {invoice.branchcode})'))

    score = sum((e['contribution'] for e in ev), start=Decimal('0'))
    return min(score, Decimal('100')).quantize(Decimal('0.01')), ev


def _e(signal, outcome, weight, contribution, detail):
    return {'signal': signal, 'outcome': outcome, 'weight': Decimal(weight),
            'contribution': Decimal(contribution).quantize(Decimal('0.001')), 'detail': detail}


def classify(score: Decimal, cfg: dict = SCORING_V1) -> str:
    if score >= cfg['high_threshold']:
        return MatchCandidate.CONF_HIGH
    if score >= cfg['medium_threshold']:
        return MatchCandidate.CONF_MEDIUM
    return MatchCandidate.CONF_LOW


# ── candidate generation (blocked, avoids O(N²)) ──────────────────────────────

def generate_for_party(party: ReconParty, cfg: dict = SCORING_V1) -> list[dict]:
    """
    Produce scored candidate dicts for one party. Blocking: for each invoice with
    an unlinked balance, only consider payments whose note references it OR whose
    unallocated amount is compatible — never the full cross product.
    """
    invoices = [i for i in party.invoices.all() if _unlinked(i) > 0]
    # cancelled payments and the receipts that cancel them never settle anything
    # …and a receipt already bound to a payment it refunds / an invoice it names is explained
    payments = [p for p in party.payments.all()
                if _unallocated(p) > 0 and p.chain_role not in ('reversed', 'reversal')
                and not (is_receipt_voucher(p) and (p.bound_payment_id or p.bound_invoice_id))]
    if not invoices or not payments:
        return []

    # index payments by reference token and by rounded amount for cheap lookup
    by_token: dict[str, list[Payment]] = {}
    by_amount: dict[Decimal, list[Payment]] = {}
    pay_unalloc = {p.pk: _unallocated(p) for p in payments}
    for p in payments:
        for t in payment_ref_tokens(p, cfg['min_ref_token_len']):
            by_token.setdefault(t, []).append(p)
        by_amount.setdefault(pay_unalloc[p.pk], []).append(p)

    # REFERENCE LOCK: a payment that names an OPEN invoice of the same branch able to absorb
    # it is proposed only for invoices it names (never for a same-amount stranger)
    open_no = {(i.branchcode, str(i.docnumber).split('.')[0].lstrip('0')): i for i in invoices}
    locked: dict[int, set] = {}
    for p in payments:
        named = {open_no[(p.branchcode, t.lstrip('0'))].pk
                 for t in payment_ref_tokens(p, cfg['min_ref_token_len'])
                 if (p.branchcode, t.lstrip('0')) in open_no
                 and _unlinked(open_no[(p.branchcode, t.lstrip('0'))]) + cfg['amount_exact_tol'] >= pay_unalloc[p.pk]}
        if named:
            locked[p.pk] = named

    cands: list[dict] = []
    for inv in invoices:
        inv_unlinked = _unlinked(inv)
        seen: set[int] = set()
        block: list[Payment] = []
        # reference block
        for key in (str(inv.docnumber).split('.')[0].lstrip('0'),
                    str(inv.docnumber2).lstrip('0') if inv.docnumber2 else ''):
            if key:
                block += by_token.get(key, [])
        # amount block (exact + amounts that could partially cover)
        block += by_amount.get(inv_unlinked, [])
        for amt, plist in by_amount.items():
            if abs(amt - inv_unlinked) <= cfg['amount_exact_tol']:
                block += plist
        for p in block:
            if p.pk in seen:
                continue
            seen.add(p.pk)
            if is_receipt_voucher(p) and not inv.is_return:
                continue    # مقبوضات never settle a purchase invoice (returns only)
            if p.pk in locked and inv.pk not in locked[p.pk]:
                continue    # locked to the open invoice it names

            score, ev = score_candidate(inv, p, inv_unlinked, pay_unalloc[p.pk], cfg)
            amount_exact = any(e['signal'] == 'amount' and e['outcome'] == 'exact' for e in ev)
            cands.append({'invoice': inv, 'payment': p, 'score': score,
                          'evidence': ev, 'inv_unlinked': inv_unlinked,
                          'pay_unalloc': pay_unalloc[p.pk], 'amount_exact': amount_exact})
    return cands


# ── conflict marking + capacity-aware resolution ──────────────────────────────

def resolve(cands: list[dict], cfg: dict = SCORING_V1) -> list[dict]:
    """
    Assign status + proposed_amount. Conflicts first (two strong rivals for the
    same invoice or payment), then a capacity-aware pass by score (a stable
    max-weight matching for these sparse per-party graphs — not naive first-come).
    """
    # ── conflict detection ──────────────────────────────────────────────────
    # A conflict is TWO+ payments that each *fully* claim the SAME invoice (only
    # one can be the settling payment). One payment covering many invoices, or
    # partial payments that add up, is legitimate splitting — NOT a conflict, so
    # we group by invoice only and require ≥2 amount-exact rivals.
    buckets: dict[int, list[dict]] = {}
    for c in cands:
        buckets.setdefault(c['invoice'].pk, []).append(c)
    for rivals in buckets.values():
        exact_rivals = [c for c in rivals if c.get('amount_exact')]
        if len(exact_rivals) < 2:
            continue
        exact_rivals.sort(key=lambda c: c['score'], reverse=True)
        top = exact_rivals[0]
        # a conflict needs ≥2 CONTENDERS: each ≥ medium and within conflict_delta of the
        # top. (Until 2026-09-28 the top counted as its own rival, so a 100-score match
        # with a 50-score same-amount voucher was wrongly held as «تعارض»; the shadow
        # validation already used this rule.)
        contenders = [c for c in exact_rivals
                      if c['score'] >= cfg['medium_threshold']
                      and (top['score'] - c['score']) <= cfg['conflict_delta']]
        if len(contenders) >= 2:
            for c in contenders:
                c['conflict'] = True

    # ── capacity-aware assignment ────────────────────────────────────────────
    inv_remaining: dict[int, Decimal] = {}
    pay_remaining: dict[int, Decimal] = {}
    for c in cands:
        inv_remaining.setdefault(c['invoice'].pk, c['inv_unlinked'])
        pay_remaining.setdefault(c['payment'].pk, c['pay_unalloc'])

    for c in sorted(cands, key=lambda c: c['score'], reverse=True):
        ir = inv_remaining[c['invoice'].pk]
        pr = pay_remaining[c['payment'].pk]
        if c.get('conflict'):
            c['status'] = MatchCandidate.STATUS_PROPOSED  # surfaced for human choice
            c['confidence_class'] = MatchCandidate.CONF_CONFLICT
            c['proposed_amount'] = min(ir, pr) if ir > 0 and pr > 0 else Decimal('0')
            continue
        if ir > 0 and pr > 0:
            take = min(ir, pr)
            c['proposed_amount'] = take
            c['status'] = MatchCandidate.STATUS_PROPOSED
            c['confidence_class'] = classify(c['score'], cfg)
            inv_remaining[c['invoice'].pk] = ir - take
            pay_remaining[c['payment'].pk] = pr - take
        else:
            c['proposed_amount'] = Decimal('0')
            c['status'] = MatchCandidate.STATUS_SUPERSEDED
            c['confidence_class'] = classify(c['score'], cfg)
    return cands


# ── orchestration (persists proposals + exceptions) ───────────────────────────

def run_matching(party_type: str | None = None, personcode: str | None = None,
                 cfg: dict = SCORING_V1, triggered_by: str = 'run_ap_matching') -> ReconciliationRun:
    """
    Run the engine over a scope and persist a ReconciliationRun + candidates + exceptions.

    Commits PER-SUPPLIER (each party in its own transaction) so an estate-wide run is
    stable, re-runnable, and never holds one giant lock that blocks concurrent
    workbench writes. A single party's failure is logged and skipped, not fatal.
    """
    # correction chains first: which payments were cancelled by a مقبوضات
    from .recon_chains import detect_chains
    detect_chains(party_type or 'supplier')
    # bind refunds to the payment they return part of (→ payment matched NET), receipts
    # to the purchase invoice they name, and write readable chain partners
    from .recon_bindings import bind_all
    bind_all(party_type or 'supplier')
    run = ReconciliationRun.objects.create(
        mode=ReconciliationRun.MODE_SUGGEST, status='running',
        party_type=party_type or '', rules_version=RULES_VERSION,
        triggered_by=triggered_by,
    )
    parties = ReconParty.objects.all()
    if party_type:
        parties = parties.filter(party_type=party_type)
    if personcode:
        parties = parties.filter(softech_personcode=personcode)

    n_cand = n_exc = n_err = 0
    for party in parties.iterator():
        try:
            with transaction.atomic():
                c_, e_ = _match_one_party(run, party, cfg)
            n_cand += c_
            n_exc += e_
        except Exception as exc:   # one bad supplier must not sink the whole run
            n_err += 1
            logger.error('[run_matching] party %s failed: %s', party.softech_personcode, exc)

    run.status = 'success' if not n_err else 'partial'
    run.counts = {'candidates': n_cand, 'exceptions': n_exc,
                  'parties': parties.count(), 'errors': n_err}
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'counts', 'finished_at'])
    ReconAuditEvent.objects.create(
        action='matching_run', run=run, rules_version=RULES_VERSION,
        after_state=run.counts, detail=f'party_type={party_type or "all"} person={personcode or "all"}',
    )
    return run


def _match_one_party(run, party, cfg) -> tuple[int, int]:
    """Generate + persist candidates/exceptions for ONE party. Caller wraps in a
    per-party transaction so each supplier commits independently."""
    # human decisions outlive the re-run: a REJECTED pair is never proposed again, and
    # a manual «send to review» hold is carried onto the re-created proposal (so the
    # auto-write policy can't approve it overnight).
    rejected = set(MatchCandidate.objects.filter(
        party=party, status=MatchCandidate.STATUS_REJECTED).values_list('invoice_id', 'payment_id'))
    manual = {(i, p): n for i, p, n in MatchCandidate.objects.filter(
        party=party, status=MatchCandidate.STATUS_PROPOSED,
        decision_note__startswith=MANUAL_HOLD_PREFIX).values_list('invoice_id', 'payment_id', 'decision_note')}
    # fresh proposals each run: drop only prior *proposed* candidates (keep
    # approved/rejected/written) so re-runs are idempotent.
    MatchCandidate.objects.filter(
        party=party, status=MatchCandidate.STATUS_PROPOSED,
    ).delete()

    cands = [c for c in generate_for_party(party, cfg)
             if (c['invoice'].pk, c['payment'].pk) not in rejected]
    resolve(cands, cfg)

    n_cand = 0
    matched_payment_ids: set[int] = set()
    for c in cands:
        if c['status'] == MatchCandidate.STATUS_SUPERSEDED and c['score'] < cfg['medium_threshold']:
            continue  # don't persist weak losers — keep the workbench clean
        mc = MatchCandidate.objects.create(
            run=run, party=party, invoice=c['invoice'], payment=c['payment'],
            proposed_amount=c['proposed_amount'], confidence_score=c['score'],
            confidence_class=c['confidence_class'], status=c['status'],
            rules_version=RULES_VERSION,
            decision_note=manual.get((c['invoice'].pk, c['payment'].pk), ''),
        )
        MatchEvidence.objects.bulk_create([
            MatchEvidence(candidate=mc, signal=e['signal'], outcome=e['outcome'],
                          weight=e['weight'], contribution=e['contribution'],
                          detail=e['detail'][:300])
            for e in c['evidence']
        ])
        n_cand += 1
        if c['status'] == MatchCandidate.STATUS_PROPOSED:
            matched_payment_ids.add(c['payment'].pk)

    # max-allocation pass over what the pairwise scoring left (doc 23 §14)
    from .recon_allocator import propose_for_party
    n_alloc, alloc_paid = propose_for_party(run, party, RULES_VERSION,
                                            skip_pairs=rejected, notes=manual)
    n_cand += n_alloc
    matched_payment_ids |= alloc_paid

    n_exc = _emit_exceptions(run, party, matched_payment_ids, cfg)
    return n_cand, n_exc


def _emit_exceptions(run, party, matched_payment_ids, cfg) -> int:
    """Orphan payments, duplicate payments, and old-unpaid invoices."""
    n = 0
    today = timezone.now().date()

    # orphan: an unallocated payment the engine could not match at all
    for p in party.payments.filter(is_unallocated=True):
        if _unallocated(p) <= 0 or p.pk in matched_payment_ids:
            continue
        _upsert_exc(run, party, ReconException.TYPE_ORPHAN_PAYMENT, 'warning', payment=p,
                    detail=f'سند {p.branchcode}/{p.cheqsno} بمبلغ {p.amount} بلا فاتورة مطابقة')
        n += 1

    # duplicate payments: same party + amount + date (probable double entry) — UNLESS the
    # two vouchers name DIFFERENT invoices (2026-09-29: a contract supplier is paid several
    # 630s a day, each voucher naming its own invoice → they were all flagged and held)
    seen: dict[tuple, list] = {}
    flagged: set[int] = set()
    for p in party.payments.all():
        key = (p.amount, p.voucher_date)
        refs = {t.lstrip('0') for t in payment_ref_tokens(p)}
        twin = next((o for o, orefs in seen.get(key, [])
                     if not (refs and orefs and not (refs & orefs))), None)
        if twin is not None:
            flagged.add(p.pk)
            _upsert_exc(run, party, ReconException.TYPE_DUPLICATE_PAYMENT, 'critical', payment=p,
                        detail=f'سند {p.branchcode}/{p.cheqsno} يطابق {twin.branchcode}/{twin.cheqsno} '
                               f'(نفس المبلغ {p.amount} ونفس التاريخ {p.voucher_date})')
            n += 1
        seen.setdefault(key, []).append((p, refs))
    # a flag the refined rule no longer raises closes itself
    ReconException.objects.filter(party=party, exception_type=ReconException.TYPE_DUPLICATE_PAYMENT,
                                  status='open').exclude(payment_id__in=flagged) \
        .update(status='resolved', resolution_notes='أُغلق تلقائيًا: السندان يسميان فاتورتين مختلفتين')

    # old unpaid invoices with nothing linked
    cutoff_days = cfg['unpaid_old_days']
    for inv in party.invoices.all():
        if _unlinked(inv) <= 0 or not inv.docdate:
            continue
        if (today - inv.docdate).days >= cutoff_days:
            _upsert_exc(run, party, ReconException.TYPE_UNPAID_OLD, 'info', invoice=inv,
                        detail=f'فاتورة {inv.docnumber} بتاريخ {inv.docdate} متبقٍّ {_unlinked(inv)}')
            n += 1
    return n


def _upsert_exc(run, party, etype, severity, invoice=None, payment=None, detail=''):
    """Avoid duplicate open exceptions for the same (type, invoice/payment)."""
    qs = ReconException.objects.filter(exception_type=etype, party=party, status='open',
                                       invoice=invoice, payment=payment)
    if qs.exists():
        return
    ReconException.objects.create(
        run=run, party=party, invoice=invoice, payment=payment,
        exception_type=etype, severity=severity, detail=detail,
    )
