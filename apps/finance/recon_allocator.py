"""
apps/finance/recon_allocator.py

MAX-ALLOCATION pass (doc 23 §14) — runs per supplier AFTER the pairwise engine and
distributes the money still unallocated on vouchers over invoices still unpaid, the
way SOFTECH's own «سداد فواتير» modal does («سداد الفواتير بالأقدم» / «توزيع المبلغ
على الفواتير»), so the maximum amount can be settled — while every proposal carries
an honest, back-tested confidence.

Strategies, in order of certainty (each consumes capacity before the next runs):

  multi_ref       voucher names ≥2 open invoices (note/cheqno) and equals their sum
  exact_unique    voucher = one open invoice exactly, mutually unique in the window
  subset_oldest   voucher = Σ of the OLDEST open invoices (SOFTECH «بالأقدم»)
  subset_window   voucher = Σ of ONE unique run of consecutive invoices in the window
  installments    consecutive vouchers add up exactly to one invoice
  fifo_residual   whatever is left, oldest invoice first, partial allowed (LOW —
                  review queue; this is what maximises the settled amount)

Pure core: the find_* functions take plain OpenInvoice/OpenVoucher records so the
live engine and the historical back-test (backtest_ap_allocator) run identical
logic. Nothing here touches SOFTECH — proposals become MatchCandidate rows that a
human (or a proven-high bulk approve) turns into allocations, and only then the
gated writer records them.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal('0')
TOL = Decimal('0.01')

ALLOC_CFG = {
    'window_days': 200,        # SOFTECH lag p99 = 184 days
    'future_days': 7,          # voucher may precede its invoice slightly (1.5% of links)
    'max_oldest_n': 60,        # longest «بالأقدم» prefix considered
    'max_run_len': 40,         # longest consecutive-invoice run considered
    'max_installments': 6,
    # confidence per strategy — CALIBRATED from backtest_ap_allocator (doc 23 §14)
    # back-test 2026-09-26 (6,008 SOFTECH vouchers): exact_unique 99.51% (3,911),
    # subset_window 99.12% (3,972), subset_oldest 96.74%, installments 84.62%, fifo 5.6%
    # exact (36% by amount) ⇒ the three exact strategies are HIGH (≥85), installments
    # MEDIUM, fifo_residual LOW (review queue).
    'score': {
        'multi_ref':     Decimal('95'),
        'exact_unique':  Decimal('92'),
        'subset_window': Decimal('90'),
        'subset_oldest': Decimal('88'),
        'same_amount_nearest': Decimal('80'),   # 95.45% on 352 ambiguous cases → MEDIUM
        'net_returns':   Decimal('65'),   # 79% in real order (19/24) → always held for review
        'installments':  Decimal('70'),
        'fifo_residual': Decimal('40'),
    },
}


@dataclass
class OpenInvoice:
    id: int
    docdate: datetime.date | None
    residual: Decimal
    refs: tuple = ()           # its own number keys (docnumber / supplier docnumber2)
    obj: object = None


@dataclass
class OpenVoucher:
    id: int
    date: datetime.date | None
    residual: Decimal
    tokens: frozenset = frozenset()
    obj: object = None
    taken: list = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────

def _eligible(inv: OpenInvoice, v: OpenVoucher, cfg=ALLOC_CFG, *, oldest=False) -> bool:
    """Invoice can be settled by this voucher date-wise. «بالأقدم» has no lower bound
    (it walks back to the oldest open invoice); the other strategies use the window."""
    if inv.residual <= TOL:
        return False
    if inv.docdate is None or v.date is None:
        return True
    lag = (v.date - inv.docdate).days
    if lag < -cfg['future_days']:
        return False
    return oldest or lag <= cfg['window_days']


def _open_sorted(invoices: list[OpenInvoice]) -> list[OpenInvoice]:
    return sorted((i for i in invoices if i.residual > TOL),
                  key=lambda i: (i.docdate or datetime.date.min, i.id))


# ── strategies (pure) ─────────────────────────────────────────────────────────

def find_multi_ref(v: OpenVoucher, invoices: list[OpenInvoice]) -> list | None:
    hits = [i for i in invoices if i.residual > TOL and set(i.refs) & v.tokens]
    if len(hits) < 2:
        return None
    total = sum((i.residual for i in hits), ZERO)
    if abs(total - v.residual) <= TOL:
        return [(i, i.residual) for i in hits]
    return None


def _q(x: Decimal) -> Decimal:
    return x.quantize(TOL)


def find_exact_unique(v: OpenVoucher, inv_by_amt: dict, vch_by_amt: dict, cfg=ALLOC_CFG) -> list | None:
    """Voucher = exactly ONE eligible open invoice, and no OTHER open voucher of that
    amount could claim that invoice (mutual uniqueness). Indexes are keyed on the
    residual at strategy start and re-checked live."""
    key = _q(v.residual)
    same = [i for i in inv_by_amt.get(key, ()) if _eligible(i, v, cfg)
            and abs(i.residual - v.residual) <= TOL]
    if len(same) != 1:
        return None
    inv = same[0]
    rivals = [w for w in vch_by_amt.get(key, ()) if w.id != v.id and w.residual > TOL
              and abs(w.residual - inv.residual) <= TOL and _eligible(inv, w, cfg)]
    if rivals:
        return None
    return [(inv, inv.residual)]


def find_same_amount_nearest(v: OpenVoucher, sorted_open: list[OpenInvoice], cfg=ALLOC_CFG) -> list | None:
    """AMBIGUOUS exact amount (≥2 eligible open invoices with exactly the voucher's
    amount — the 'conflict' case): take the one CLOSEST IN DATE to the voucher.
    Back-test on 352 real ambiguous SOFTECH cases: nearest 95.45% vs oldest 12.16%.
    Returns None when 0/1 match (exact_unique handles 1) or on an exact date tie."""
    same = [i for i in sorted_open if _eligible(i, v, cfg) and abs(i.residual - v.residual) <= TOL]
    if len(same) < 2:
        return None
    # back-test: OLDEST is right only 12% here — cashiers pay the NEAREST delivery.
    if v.date is None:
        return None
    ranked = sorted(same, key=lambda i: abs((v.date - i.docdate).days) if i.docdate else 10 ** 6)
    best, second = ranked[0], ranked[1]
    gap = lambda i: abs((v.date - i.docdate).days) if i.docdate else 10 ** 6
    if gap(best) == gap(second):
        return None          # a true tie — leave it to a human
    return [(best, best.residual)]


def find_oldest_prefix(v: OpenVoucher, sorted_open: list[OpenInvoice], cfg=ALLOC_CFG) -> list | None:
    """SOFTECH «سداد الفواتير بالأقدم»: the oldest open invoices, in order, whose
    cumulative residual lands EXACTLY on the voucher amount."""
    acc, picked = ZERO, []
    for inv in sorted_open:
        if not _eligible(inv, v, cfg, oldest=True):
            if inv.docdate and v.date and inv.docdate > v.date:
                break                      # sorted by date → nothing later qualifies
            continue
        picked.append(inv)
        acc += inv.residual
        if abs(acc - v.residual) <= TOL:
            return [(i, i.residual) for i in picked]
        if acc > v.residual + TOL or len(picked) >= cfg['max_oldest_n']:
            return None
    return None


def find_window_run(v: OpenVoucher, sorted_open: list[OpenInvoice], cfg=ALLOC_CFG) -> list | None:
    """A UNIQUE run of consecutive (by date) eligible invoices summing exactly to the
    voucher. Two solutions ⇒ ambiguous ⇒ None (left for FIFO / human).
    `sorted_open` may be pre-sliced to the voucher's date window (bisect)."""
    elig = [i for i in sorted_open if _eligible(i, v, cfg)]
    found = None
    lo, acc = 0, ZERO
    for hi, inv in enumerate(elig):
        acc += inv.residual
        while (acc > v.residual + TOL or hi - lo + 1 > cfg['max_run_len']) and lo <= hi:
            acc -= elig[lo].residual
            lo += 1
        if lo <= hi and abs(acc - v.residual) <= TOL:
            if found is not None:
                return None                # ambiguous
            found = elig[lo:hi + 1]
    return [(i, i.residual) for i in found] if found else None


def find_installments(inv: OpenInvoice, sorted_vouchers: list[OpenVoucher], cfg=ALLOC_CFG) -> list | None:
    """Consecutive open vouchers dated from the invoice onward, 2..N of them, adding
    up EXACTLY to the invoice's residual; must be unique."""
    elig = [w for w in sorted_vouchers if w.residual > TOL and _eligible(inv, w, cfg)]
    found = None
    lo, acc = 0, ZERO
    for hi, w in enumerate(elig):
        acc += w.residual
        while (acc > inv.residual + TOL or hi - lo + 1 > cfg['max_installments']) and lo <= hi:
            acc -= elig[lo].residual
            lo += 1
        n = hi - lo + 1
        if lo <= hi and n >= 2 and abs(acc - inv.residual) <= TOL:
            if found is not None:
                return None
            found = elig[lo:hi + 1]
    return [(w, w.residual) for w in found] if found else None


def fifo_residual(v: OpenVoucher, sorted_open: list[OpenInvoice], cfg=ALLOC_CFG) -> list:
    """Whatever the voucher still holds → oldest eligible invoices first, partial OK."""
    out, left = [], v.residual
    for inv in sorted_open:
        if left <= TOL:
            break
        if not _eligible(inv, v, cfg, oldest=True):
            if inv.docdate and v.date and inv.docdate > v.date + datetime.timedelta(days=cfg['future_days']):
                break
            continue
        take = min(inv.residual, left)
        out.append((inv, take))
        left -= take
    return out


# ── orchestration over one party (pure over Open* records) ────────────────────

def _date_key(d):
    return d or datetime.date.min


def allocate(invoices: list[OpenInvoice], vouchers: list[OpenVoucher],
             cfg=ALLOC_CFG, strategies=None, returns: list | None = None) -> list[dict]:
    """
    Run the strategies in order, consuming residual capacity. Returns proposal dicts:
    {strategy, group, invoice, voucher, amount}. `strategies` restricts the set (the
    back-test measures each one in isolation).
    """
    import bisect
    order = strategies or ['multi_ref', 'exact_unique', 'same_amount_nearest', 'subset_oldest',
                           'subset_window', 'net_returns', 'installments', 'fifo_residual']
    rets = sorted([r for r in (returns or []) if r.residual > TOL],
                  key=lambda r: (_date_key(r.docdate), r.id))
    vouchers = sorted(vouchers, key=lambda w: (_date_key(w.date), w.id))
    invs = sorted(invoices, key=lambda i: (_date_key(i.docdate), i.id))   # sorted ONCE
    inv_dates = [_date_key(i.docdate) for i in invs]
    props: list[dict] = []
    win = datetime.timedelta(days=cfg['window_days'])
    fut = datetime.timedelta(days=cfg['future_days'])

    def live(seq):
        return [i for i in seq if i.residual > TOL]

    def take(strategy, group, pairs, *, voucher=None, invoice=None):
        for a, amt in pairs:
            inv = invoice or a
            vch = voucher or a
            amt = min(amt, inv.residual, vch.residual)
            if amt <= TOL:
                continue
            inv.residual -= amt
            vch.residual -= amt
            props.append({'strategy': strategy, 'group': group,
                          'invoice': inv, 'voucher': vch, 'amount': amt})

    for strat in order:
        if strat == 'installments':
            for inv in live(invs):
                hit = find_installments(inv, vouchers, cfg)
                if hit:
                    take(strat, f'inst:{inv.id}', hit, invoice=inv)
            continue
        inv_by_amt: dict = {}
        vch_by_amt: dict = {}
        if strat == 'exact_unique':
            for i in live(invs):
                inv_by_amt.setdefault(_q(i.residual), []).append(i)
            for w in vouchers:
                if w.residual > TOL:
                    vch_by_amt.setdefault(_q(w.residual), []).append(w)
        by_token: dict = {}
        if strat == 'multi_ref':
            for i in live(invs):
                for r in i.refs:
                    by_token.setdefault(r, []).append(i)
        first_open = 0
        for v in vouchers:
            if v.residual <= TOL:
                continue
            if strat == 'multi_ref':
                cands = {i.id: i for t in v.tokens for i in by_token.get(t, ())}
                hit = find_multi_ref(v, list(cands.values())) if len(cands) >= 2 else None
            elif strat == 'exact_unique':
                hit = find_exact_unique(v, inv_by_amt, vch_by_amt, cfg)
            elif strat in ('subset_oldest', 'fifo_residual'):
                while first_open < len(invs) and invs[first_open].residual <= TOL:
                    first_open += 1
                upto = (bisect.bisect_right(inv_dates, v.date + fut) if v.date else len(invs))
                pool = invs[first_open:upto]
                hit = (find_oldest_prefix(v, pool, cfg) if strat == 'subset_oldest'
                       else (fifo_residual(v, pool, cfg) or None))
            elif strat == 'same_amount_nearest':
                if v.date:
                    lo = bisect.bisect_left(inv_dates, v.date - win)
                    hi = bisect.bisect_right(inv_dates, v.date + fut)
                    pool = invs[lo:hi]
                else:
                    pool = invs
                hit = find_same_amount_nearest(v, pool, cfg)
            elif strat == 'net_returns':
                # SOFTECH netting: voucher = Σ purchases − Σ open returns. Take the
                # supplier's open returns in the window as credits, then look for an
                # exact purchase set for the enlarged amount.
                elig_r = [r for r in rets if r.residual > TOL and v.date and r.docdate
                          and v.date - win <= r.docdate <= v.date + fut]
                if not elig_r:
                    continue
                credit = sum((r.residual for r in elig_r), ZERO)
                probe = OpenVoucher(v.id, v.date, v.residual + credit, v.tokens)
                while first_open < len(invs) and invs[first_open].residual <= TOL:
                    first_open += 1
                upto = (bisect.bisect_right(inv_dates, v.date + fut) if v.date else len(invs))
                hit = find_oldest_prefix(probe, invs[first_open:upto], cfg)
                if not hit:
                    lo = bisect.bisect_left(inv_dates, v.date - win) if v.date else 0
                    hit = find_window_run(probe, invs[lo:upto], cfg)
                if hit:
                    group = f'net:{v.id}'
                    for r in elig_r:                       # credits first → room on the voucher
                        amt = r.residual
                        r.residual = ZERO
                        v.residual += amt
                        props.append({'strategy': strat, 'group': group, 'invoice': r,
                                      'voucher': v, 'amount': amt, 'is_credit': True})
                    take(strat, group, hit, voucher=v)
                continue
            elif strat == 'subset_window':
                if v.date:
                    lo = bisect.bisect_left(inv_dates, v.date - win)
                    hi = bisect.bisect_right(inv_dates, v.date + fut)
                    pool = invs[lo:hi]
                else:
                    pool = invs
                hit = find_window_run(v, pool, cfg)
            else:
                raise ValueError(strat)
            if hit:
                take(strat, f'{strat[:6]}:{v.id}', hit, voucher=v)
    return props


# ── persistence: turn proposals into MatchCandidate rows (PostgreSQL only) ────

_STRAT_TEXT = {
    'multi_ref':     'السند يذكر أرقام هذه الفواتير ومجموعها = مبلغ السند',
    'exact_unique':  'مبلغ السند = قيمة الفاتورة، ولا فاتورة/سند آخر بنفس المبلغ في الفترة',
    'subset_oldest': 'مجموع أقدم الفواتير المفتوحة = مبلغ السند (مثل «سداد الفواتير بالأقدم»)',
    'subset_window': 'مجموع فواتير متتالية (مجموعة وحيدة) = مبلغ السند',
    'same_amount_nearest': 'أكثر من فاتورة بنفس المبلغ — اختيرت الأقرب تاريخًا للسند (دقة تاريخية 95%)',
    'net_returns':   'مقاصة: مبلغ السند = فواتير شراء − مرتجعات مفتوحة (كما يفعل SOFTECH) — للمراجعة',
    'installments':  'عدة سندات متتالية مجموعها = قيمة الفاتورة (أقساط)',
    'fifo_residual': 'توزيع المتبقي من السند على أقدم الفواتير المفتوحة — يحتاج مراجعة',
}


def _inv_refs(inv) -> tuple:
    keys = [str(inv.docnumber).split('.')[0].lstrip('0')]
    if inv.docnumber2:
        keys.append(str(inv.docnumber2).strip().lstrip('0'))
    return tuple(k for k in keys if k)


def open_state(party, reserve_run=None):
    """Writable capacity per purchase invoice / outgoing voucher of one party:
    invoice = doc_value − SOFTECH-known paid − approved-not-yet-written − capacity
    reserved by this run's own high/medium pairwise proposals; voucher likewise."""
    from collections import defaultdict
    from .models import Allocation, MatchCandidate
    from .recon_engine import payment_ref_tokens
    soft_written = defaultdict(lambda: ZERO)
    approved = defaultdict(lambda: ZERO)
    pay_used = defaultdict(lambda: ZERO)
    for a in Allocation.objects.filter(payment__party=party).values(
            'invoice_id', 'payment_id', 'origin', 'amount', 'invoice__is_return', 'payment__cheqtype'):
        # signed voucher usage: a return netted in a مدفوعات is a credit
        receipt = (a['payment__cheqtype'] or '').strip() == '10'
        sign = 1 if receipt == bool(a['invoice__is_return']) else -1
        pay_used[a['payment_id']] += sign * a['amount']
        if a['origin'] == Allocation.ORIGIN_APPROVED:
            approved[a['invoice_id']] += a['amount']
        else:
            soft_written[a['invoice_id']] += a['amount']
    res_inv = defaultdict(lambda: ZERO)
    res_pay = defaultdict(lambda: ZERO)
    if reserve_run is not None:
        for c in MatchCandidate.objects.filter(
                run=reserve_run, party=party, status=MatchCandidate.STATUS_PROPOSED,
                confidence_class__in=(MatchCandidate.CONF_HIGH, MatchCandidate.CONF_MEDIUM)):
            res_inv[c.invoice_id] += c.proposed_amount
            res_pay[c.payment_id] += c.proposed_amount

    from .recon_returns import open_returned_by_purchase
    returned_open = open_returned_by_purchase(party=party)
    invoices = []
    for inv in party.invoices.filter(is_return=False):
        paid_known = max(inv.doc_value_pay or ZERO, soft_written[inv.id])
        # a purchase with an OPEN linked return is only payable for what was kept
        cap = ((inv.doc_value or ZERO) - paid_known - approved[inv.id] - res_inv[inv.id]
               - returned_open.get(inv.id, ZERO))
        if cap > TOL:
            invoices.append(OpenInvoice(inv.id, inv.docdate, cap, _inv_refs(inv), obj=inv))
    vouchers = []
    # REFERENCE LOCK (2026-09-29): a voucher whose serial/note names an OPEN invoice of
    # this supplier + branch that can absorb it belongs to THAT invoice — the pairwise
    # reference match settles it; the amount/date strategies here must not hand it to a
    # different invoice (5,529 links had done exactly that, e.g. 630 vouchers shifted one
    # invoice back at supplier 4471).
    open_by_no = {}
    for oi in invoices:
        open_by_no[(oi.obj.branchcode, str(oi.obj.docnumber).split('.')[0].lstrip('0'))] = oi
    # payment vouchers only — مقبوضات (cheqtype 10) never settle purchase invoices
    for p in (party.payments.filter(direction='out').exclude(cheqtype='10')
              .exclude(chain_role__in=['reversed', 'reversal'])):
        cap = (p.net_amount or ZERO) - pay_used[p.id] - res_pay[p.id]     # net of bound refunds
        if cap <= TOL:
            continue
        refs = frozenset(payment_ref_tokens(p))
        named = [open_by_no[(p.branchcode, t.lstrip('0'))] for t in refs
                 if (p.branchcode, t.lstrip('0')) in open_by_no]
        if any(n.residual + TOL >= cap for n in named):
            continue                     # locked to the invoice it names
        vouchers.append(OpenVoucher(p.id, p.voucher_date, cap, refs, obj=p))
    from .recon_returns import open_return_amounts
    ret_objs = list(party.invoices.filter(is_return=True).exclude(source_hash=''))
    credit = open_return_amounts(ret_objs)
    returns = [OpenInvoice(r.id, r.docdate, credit[r.id] - res_inv[r.id], _inv_refs(r), obj=r)
               for r in ret_objs if credit.get(r.id, ZERO) - res_inv[r.id] > TOL]
    return invoices, vouchers, returns


def propose_for_party(run, party, rules_version: str, cfg=ALLOC_CFG,
                      skip_pairs=frozenset(), notes=None) -> tuple[int, set]:
    """Run allocate() over the party's residual capacity and persist each proposal as a
    MatchCandidate (strategy + group_key + explainable evidence). Returns
    (n_created, matched_payment_ids). `skip_pairs` = (invoice_id, payment_id) a human
    REJECTED — never re-proposed; `notes` = manual review holds carried over a re-run."""
    notes = notes or {}
    from .models import MatchCandidate, MatchEvidence
    from .recon_engine import classify
    invoices, vouchers, returns = open_state(party, reserve_run=run)
    if not invoices or not vouchers:
        return 0, set()
    props = allocate(invoices, vouchers, cfg, returns=returns)
    if not props:
        return 0, set()

    group_sizes: dict = {}
    for pr in props:
        group_sizes[pr['group']] = group_sizes.get(pr['group'], 0) + 1
    existing = {(c.invoice_id, c.payment_id): c
                for c in MatchCandidate.objects.filter(run=run, party=party)}
    n, matched = 0, set()
    for pr in props:
        inv, v = pr['invoice'].obj, pr['voucher'].obj
        strat = pr['strategy']
        score = cfg['score'][strat]
        cls = classify(score)
        key = (inv.id, v.id)
        if key in skip_pairs:                     # a human rejected this exact pair
            continue
        if key in existing:                       # a weaker pairwise row for the same pair
            c = existing[key]
            if c.status != MatchCandidate.STATUS_PROPOSED or c.confidence_score >= score:
                continue
            c.proposed_amount, c.confidence_score, c.confidence_class = pr['amount'], score, cls
            c.strategy, c.group_key = strat, pr['group']
            c.save(update_fields=['proposed_amount', 'confidence_score', 'confidence_class',
                                  'strategy', 'group_key'])
            c.evidence.all().delete()
        else:
            c = MatchCandidate.objects.create(
                run=run, party=party, invoice=inv, payment=v, proposed_amount=pr['amount'],
                confidence_score=score, confidence_class=cls, status=MatchCandidate.STATUS_PROPOSED,
                rules_version=rules_version, strategy=strat, group_key=pr['group'],
                decision_note=notes.get(key, ''))
        lag = (v.voucher_date - inv.docdate).days if (v.voucher_date and inv.docdate) else None
        size = group_sizes[pr['group']]
        ev = [MatchEvidence(candidate=c, signal='amount',
                            outcome='approximate' if strat == 'fifo_residual' else 'exact',
                            weight=Decimal('45'), contribution=Decimal('45') if strat != 'fifo_residual' else ZERO,
                            detail=(_STRAT_TEXT[strat] + (f' — {size} بنود' if size > 1 else ''))[:300]),
              MatchEvidence(candidate=c, signal='sequence', outcome='exact',
                            weight=ZERO, contribution=ZERO,
                            detail=f'الاستراتيجية: {strat} · المجموعة {pr["group"]}'[:300])]
        if lag is not None:
            ev.append(MatchEvidence(candidate=c, signal='temporal',
                                    outcome='exact' if 0 <= lag <= 45 else 'approximate',
                                    weight=Decimal('15'), contribution=ZERO,
                                    detail=f'{lag} يوم بين الفاتورة والسند'))
        if set(pr['invoice'].refs) & pr['voucher'].tokens:
            ev.append(MatchEvidence(candidate=c, signal='reference', outcome='exact',
                                    weight=Decimal('35'), contribution=ZERO,
                                    detail='رقم الفاتورة مذكور في السند'))
        MatchEvidence.objects.bulk_create(ev)
        n += 1
        matched.add(v.id)
    return n, matched
