"""
python manage.py backtest_ap_allocator [--max-per-party 400] [--seed 0]

HISTORICAL BACK-TEST of each max-allocation strategy (recon_allocator) against
SOFTECH's own recorded سداد (the `chequestrans` ground truth). Read-only.

Replay per supplier, vouchers in date order. At each voucher's date the OPEN
invoice set is rebuilt from history: an invoice is open if it was dated on/before
the voucher (+7d) and its residual — doc_value minus everything SOFTECH allocated to
it from EARLIER vouchers — is still > 0 (invoices never linked count as open only
if SOFTECH still shows them unpaid). The true allocation is hidden, each strategy
runs in isolation, and a prediction counts as CORRECT only if it reproduces the
exact invoice set and amounts SOFTECH recorded.

  precision = correct / predictions made      coverage = predictions / vouchers tried
  fifo_residual is scored amount-weighted (share of money landing on a true invoice).
"""
import datetime
import random
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.finance import recon_allocator as RA
from apps.finance.recon_engine import payment_ref_tokens

TOL = Decimal('0.01')
STRATS = ['multi_ref', 'exact_unique', 'same_amount_nearest', 'subset_oldest', 'subset_window', 'fifo_residual']


def _refs(inv):
    keys = [str(inv.docnumber).split('.')[0].lstrip('0')]
    if inv.docnumber2:
        keys.append(str(inv.docnumber2).strip().lstrip('0'))
    return tuple(k for k in keys if k)


class Command(BaseCommand):
    help = 'Back-test max-allocation strategies against SOFTECH ground-truth سداد'

    def add_arguments(self, parser):
        parser.add_argument('--max-per-party', type=int, default=400)
        parser.add_argument('--seed', type=int, default=0)
        parser.add_argument('--party', default='', help='one personcode only')

    def handle(self, *args, **o):
        from apps.finance.models import Allocation, APInvoice, ReconParty
        random.seed(o['seed'])
        cfg = RA.ALLOC_CFG
        fut = datetime.timedelta(days=cfg['future_days'])
        res = {s: {'tried': 0, 'made': 0, 'correct': 0} for s in STRATS}
        res['installments'] = {'tried': 0, 'made': 0, 'correct': 0}
        fifo_amt = {'total': Decimal(0), 'right': Decimal(0)}

        parties = ReconParty.objects.filter(party_type='supplier')
        if o['party']:
            parties = parties.filter(softech_personcode=o['party'])
        for party in parties.iterator():
            gt = list(Allocation.objects.filter(origin='softech', payment__party=party,
                                                invoice__is_return=False)
                      .select_related('payment', 'invoice'))
            if not gt:
                continue
            truth = defaultdict(dict)            # voucher id → {invoice id: amount}
            vouchers = {}
            for a in gt:
                truth[a.payment_id][a.invoice_id] = truth[a.payment_id].get(a.invoice_id, 0) + a.amount
                vouchers[a.payment_id] = a.payment
            invs = sorted(APInvoice.objects.filter(party=party, is_return=False),
                          key=lambda i: (i.docdate or datetime.date.min, i.id))
            linked = {a.invoice_id for a in gt}
            state = {}                           # residual as history unfolds
            for i in invs:
                if i.id in linked:
                    state[i.id] = i.doc_value
                elif i.doc_value - i.doc_value_pay > TOL:
                    state[i.id] = i.doc_value - i.doc_value_pay
            order = sorted(vouchers.values(), key=lambda p: (p.voucher_date or datetime.date.min, p.id))
            # evaluate only vouchers whose amount == Σ their purchase links (clean truth)
            clean = [p for p in order if abs(p.amount - sum(truth[p.id].values(), Decimal(0))) <= TOL]
            sample = set(p.id for p in (random.sample(clean, o['max_per_party'])
                                        if len(clean) > o['max_per_party'] else clean))

            for p in order:
                if p.id in sample:
                    t = p.voucher_date
                    pool = [RA.OpenInvoice(i.id, i.docdate, state[i.id], _refs(i))
                            for i in invs if i.id in state and state[i.id] > TOL
                            and (not t or not i.docdate or i.docdate <= t + fut)]
                    toks = frozenset(payment_ref_tokens(p))
                    exp = {k: v for k, v in truth[p.id].items()}
                    for s in STRATS:
                        v = RA.OpenVoucher(p.id, t, p.amount, toks)
                        fresh = [RA.OpenInvoice(x.id, x.docdate, x.residual, x.refs) for x in pool]
                        props = RA.allocate(fresh, [v], cfg, strategies=[s])
                        res[s]['tried'] += 1
                        if not props:
                            continue
                        got = defaultdict(Decimal)
                        for pr in props:
                            got[pr['invoice'].id] += pr['amount']
                        if s == 'fifo_residual':
                            for iid, amt in got.items():
                                fifo_amt['total'] += amt
                                if iid in exp:
                                    fifo_amt['right'] += min(amt, exp[iid])
                        res[s]['made'] += 1
                        if set(got) == set(exp) and all(abs(got[k] - exp[k]) <= TOL for k in exp):
                            res[s]['correct'] += 1
                # history moves on: apply the TRUE allocation of this voucher
                for iid, amt in truth[p.id].items():
                    if iid in state:
                        state[iid] -= amt

            # installments: invoices SOFTECH settled with ≥2 vouchers
            by_inv = defaultdict(dict)
            for a in gt:
                by_inv[a.invoice_id][a.payment_id] = a.amount
            multi = [iid for iid, d in by_inv.items() if len(d) >= 2]
            inv_map = {i.id: i for i in invs}
            for iid in multi[: o['max_per_party']]:
                inv = inv_map.get(iid)
                if not inv:
                    continue
                vs = [RA.OpenVoucher(pid, vouchers[pid].voucher_date, vouchers[pid].amount)
                      for pid in vouchers
                      if abs(vouchers[pid].amount - sum(truth[pid].values(), Decimal(0))) <= TOL
                      and len(truth[pid]) == 1]          # single-invoice vouchers only
                res['installments']['tried'] += 1
                oi = RA.OpenInvoice(inv.id, inv.docdate, inv.doc_value, _refs(inv))
                props = RA.allocate([oi], vs, cfg, strategies=['installments'])
                if not props:
                    continue
                res['installments']['made'] += 1
                if {pr['voucher'].id for pr in props} == set(by_inv[iid]):
                    res['installments']['correct'] += 1

        self.stdout.write('═══════ BACK-TEST vs SOFTECH ground truth ═══════')
        for s, r in res.items():
            prec = (r['correct'] / r['made'] * 100) if r['made'] else 0
            cov = (r['made'] / r['tried'] * 100) if r['tried'] else 0
            self.stdout.write(f"  {s:15} tried {r['tried']:6}  predicted {r['made']:6} ({cov:5.1f}%)  "
                              f"correct {r['correct']:6}  PRECISION {prec:6.2f}%")
        if fifo_amt['total']:
            self.stdout.write(f"  fifo_residual amount-weighted precision: "
                              f"{fifo_amt['right'] / fifo_amt['total'] * 100:.2f}% of "
                              f"{fifo_amt['total']:.2f} EGP lands on a truly linked invoice")
