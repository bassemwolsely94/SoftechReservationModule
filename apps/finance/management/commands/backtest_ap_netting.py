"""
python manage.py backtest_ap_netting

Back-test the `net_returns` strategy (voucher = Σ purchases − Σ open returns)
against SOFTECH's own netting vouchers. Replays each supplier's history in voucher
order, tracking open purchases AND open returns; a prediction is CORRECT only if it
reproduces exactly the purchases and returns (and amounts) SOFTECH recorded.
Also reports how often it fires on vouchers that did NOT net a return (misfires).
Read-only.
"""
import datetime
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.finance import recon_allocator as RA

TOL = Decimal('0.01')


class Command(BaseCommand):
    help = 'Back-test net_returns against SOFTECH netting vouchers'

    def handle(self, *args, **o):
        from apps.finance.models import Allocation, APInvoice, ReconParty
        cfg = RA.ALLOC_CFG
        fut = datetime.timedelta(days=cfg['future_days'])
        res = {'netting': [0, 0, 0], 'plain': [0, 0, 0]}   # tried, made, correct
        for party in ReconParty.objects.filter(party_type='supplier').iterator():
            gt = list(Allocation.objects.filter(origin='softech', payment__party=party,
                                                payment__cheqtype='20')
                      .select_related('payment', 'invoice'))
            if not gt:
                continue
            truth = defaultdict(dict)
            vouchers = {}
            for a in gt:
                truth[a.payment_id][a.invoice_id] = truth[a.payment_id].get(a.invoice_id, 0) + a.amount
                vouchers[a.payment_id] = a.payment
            docs = sorted(APInvoice.objects.filter(party=party).exclude(source_hash=''),
                          key=lambda i: (i.docdate or datetime.date.min, i.id))
            is_ret = {d.id: d.is_return for d in docs}
            linked = {a.invoice_id for a in gt}
            state = {}
            for d in docs:
                if d.id in linked:
                    state[d.id] = d.doc_value
                elif d.doc_value - d.doc_value_pay > TOL:
                    state[d.id] = d.doc_value - d.doc_value_pay
            order = sorted(vouchers.values(), key=lambda p: (p.voucher_date or datetime.date.min, p.id))
            for p in order:
                t = p.voucher_date
                tr = truth[p.id]
                pur = sum((v for k, v in tr.items() if not is_ret.get(k)), Decimal(0))
                ret = sum((v for k, v in tr.items() if is_ret.get(k)), Decimal(0))
                clean = abs(p.amount - (pur - ret)) <= TOL
                kind = 'netting' if ret > 0 else 'plain'
                if clean and t:
                    purchases = [RA.OpenInvoice(d.id, d.docdate, state[d.id]) for d in docs
                                 if not d.is_return and d.id in state and state[d.id] > TOL
                                 and (not d.docdate or d.docdate <= t + fut)]
                    returns = [RA.OpenInvoice(d.id, d.docdate, state[d.id]) for d in docs
                               if d.is_return and d.id in state and state[d.id] > TOL
                               and (not d.docdate or d.docdate <= t + fut)]
                    v = RA.OpenVoucher(p.id, t, p.amount)
                    # realistic order: purchase-only exact strategies get the voucher first
                    props = RA.allocate(purchases, [v], cfg, returns=returns,
                                        strategies=['exact_unique', 'same_amount_nearest', 'subset_oldest',
                                                    'subset_window', 'net_returns'])
                    res[kind][0] += 1
                    if any(pr['strategy'] == 'net_returns' for pr in props):
                        res[kind][1] += 1
                        got = defaultdict(Decimal)
                        for pr in props:
                            got[pr['invoice'].id] += pr['amount']
                        if set(got) == set(tr) and all(abs(got[k] - tr[k]) <= TOL for k in tr):
                            res[kind][2] += 1
                for iid, amt in tr.items():
                    if iid in state:
                        state[iid] -= amt
        for kind, (tried, made, ok) in res.items():
            prec = ok / made * 100 if made else 0
            self.stdout.write(f'  {kind:8} vouchers tried {tried:6}  fired {made:5}  correct {ok:5}  PRECISION {prec:6.2f}%')
        tot_made = res['netting'][1] + res['plain'][1]
        tot_ok = res['netting'][2] + res['plain'][2]
        self.stdout.write(self.style.SUCCESS(
            f'  OVERALL precision {tot_ok / tot_made * 100 if tot_made else 0:.2f}% '
            f'({tot_ok}/{tot_made}); recall on netting vouchers '
            f'{res["netting"][2] / res["netting"][0] * 100 if res["netting"][0] else 0:.1f}%'))
