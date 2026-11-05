"""
Round 2 / R2 — offers and incentives money correctness (docs/security/2026-11-05-full-project-test-plan.md §7 R2).

Offers — sources:
  * CLAUDE.md rule 4 "Pharmacy safety always beats sales — never let an upsell/promotion override a
    safety flag"; apps/catalog/safety.py: severity 'block' = "this item cannot be sold as-is … the flag
    only makes the reason visible so it can't be silently upsold"; recommendations/basket_intelligence.py
    already drops blocks_sale items ("SAFETY WINS").
  * apps/offers/engine.py: per offer a {line_index: amount} map; chosen offers combine per line, each
    line capped at its gross. apps/offers/order_attach.py: re-attaching rebuilds cust_discp from the
    line's LIST price and replaces the OfferApplication rows — it never stacks on itself.
Incentives — source: apps/incentives/engine.calculate docstring + views.calculate:
  * a run deletes the period's transactions and rebuilds them (same input → same rows);
  * a finalized period refuses recalculation (ValueError → HTTP 409) unless force=True;
  * force=True un-finalizes the period's settlements (is_finalized=False, finalized_at/by cleared).
SOFTECH reads (_fetch_rows / _fetch_cross_period_returns) are replaced by synthetic rows.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.catalog.safety import blocks_sale
from apps.incentives import engine as IE
from apps.incentives.models import IncentiveProgram, IncentiveRule, IncentiveSettlement, IncentiveTransaction
from apps.offers import order_attach
from apps.offers.engine import evaluate_offers
from apps.offers.models import Offer, OfferApplication
from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine

from .factories import make_branch, make_item, make_user
from .security.baseline import pending

D = Decimal


def _offer(**kw):
    d = dict(name='R2', offer_type='percent', status='active', value=D('10'), target_all=True,
             authorization_source='offer', require_stock=False, stackable=True)
    d.update(kw)
    return Offer.objects.create(**d)


def _line(item, qty, price):
    return {'softech_id': item.softech_id, 'item': item, 'qty': qty, 'unit_price': price}


# (label, field changes that make catalog.safety raise a 'block' flag)
BLOCKING = [
    ('sale stopped (itemtrans3=3)', {'customer_trans': '3'}),
    ('archived', {'item_archive': True}),
    ('inactive', {'is_active': False}),
]


class OfferSafetyTests(TestCase):
    def setUp(self):
        self.ok = make_item(name='OK', softech_id='R2OK')

    def _blocked(self, n, changes):
        it = make_item(name=f'BLK{n}', softech_id=f'R2BLK{n}')
        for k, v in changes.items():
            setattr(it, k, v)
        it.save()
        self.assertTrue(blocks_sale(it))
        return it

    def test_a_safe_item_in_the_same_basket_is_discounted(self):
        # Control for the pending test below: the offer itself works.
        plan = evaluate_offers([_line(self.ok, 1, 100)], offers=[_offer()])
        self.assertEqual(plan['total_discount'], D('10.00'))

    @pending('M-1')
    def test_an_item_with_a_blocking_safety_flag_never_receives_an_offer_discount(self):
        for n, (label, changes) in enumerate(BLOCKING):
            with self.subTest(label):
                bad = self._blocked(n, changes)
                plan = evaluate_offers([_line(self.ok, 1, 100), _line(bad, 1, 100)], offers=[_offer()])
                touched = {ln['index'] for ap in plan['applied'] for ln in ap['lines']}
                self.assertNotIn(1, touched)
                self.assertEqual(plan['total_discount'], D('10.00'))


class OfferAppliesOnceTests(TestCase):
    def setUp(self):
        self.a = make_item(name='A', softech_id='R2A')
        self.b = make_item(name='B', softech_id='R2B')

    def test_each_offer_appears_once_and_lines_never_exceed_gross(self):
        offers = [_offer(name='p10', value=D('10')), _offer(name='p60', value=D('60')),
                  _offer(name='fixed', offer_type='fixed', value=D('500'))]
        basket = [_line(self.a, 2, 100), _line(self.b, 1, D('33.33'))]
        plan = evaluate_offers(basket, offers=offers)
        ids = [ap['offer_id'] for ap in plan['applied']]
        self.assertEqual(len(ids), len(set(ids)))
        for ap in plan['applied']:
            idx = [ln['index'] for ln in ap['lines']]
            self.assertEqual(len(idx), len(set(idx)), ap['name'])
        # the engine's own total is capped per line at the line's gross (engine.evaluate_offers)
        self.assertEqual(plan['total_discount'], plan['basket_total'])
        self.assertEqual(plan['net_total'], D('0.00'))

    @pending('M-2')
    def test_stacked_offers_never_take_a_line_below_zero_when_attached(self):
        # attach.build_attach_plan turns the plan into the cust_discp written to the POS line. It sums the
        # per-offer line amounts WITHOUT the engine's per-line gross cap, so 10% + 60% + a fixed offer
        # covering the whole subtotal gives cust_discp 170% and a negative SOFTECH line total.
        from apps.offers.attach import build_attach_plan
        offers = [_offer(name='p10', value=D('10')), _offer(name='p60', value=D('60')),
                  _offer(name='fixed', offer_type='fixed', value=D('500'))]
        basket = [_line(self.a, 2, 100), _line(self.b, 1, D('33.33'))]
        self.assertEqual(Offer.objects.filter(status='active').count(), len(offers))   # what the plan reads
        out = build_attach_plan(basket)
        for ln in out['lines']:
            with self.subTest(index=ln['index']):
                self.assertLessEqual(ln['cust_discp'], D('100.00'))
                self.assertLessEqual(ln['engine_discount'], ln['gross'])
                self.assertGreaterEqual(ln['gross'] - ln['softech_discount'], D('0.00'))
        self.assertEqual(out['reconciliation']['engine_total'], out['plan']['total_discount'])

    def test_evaluation_is_deterministic(self):
        offers = [_offer(name='p10'), _offer(name='excl', value=D('15'), stackable=False)]
        basket = [_line(self.a, 3, D('19.99')), _line(self.b, 1, D('250'))]
        first = evaluate_offers(basket, offers=offers)
        for _ in range(3):
            again = evaluate_offers(basket, offers=offers)
            self.assertEqual((again['total_discount'], again['applied']),
                             (first['total_discount'], first['applied']))

    @override_settings(POS_OFFERS_EXECUTION_ENABLED=True, WRITER_INSTANCE=True)
    def test_attaching_twice_does_not_stack_the_offer(self):
        br = make_branch()
        o = SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id,
                                             store_code='1', seller_usercode='1', channel='cash')
        for it, qty, price in ((self.a, 2, '100'), (self.b, 1, '50')):
            SoftechSalesOrderLine.objects.create(order=o, item=it, softech_itemcode=it.softech_id,
                                                 qty=D(qty), item_sale_price=D(price))
        offer = _offer(value=D('10'), authorization_source='item_card')
        for it in (self.a, self.b):
            it.pos_discp = D('100')
            it.save(update_fields=['pos_discp'])

        def state():
            return [(l.cust_discp, l.trans_price_total) for l in o.lines.order_by('id')]

        order_attach.apply_offers_to_order(o)
        once = state()
        self.assertEqual(once, [(D('10.00'), D('180.00')), (D('10.00'), D('45.00'))])
        order_attach.apply_offers_to_order(o)
        self.assertEqual(state(), once)                                       # 10%, not 19%
        self.assertEqual(OfferApplication.objects.filter(pos_order=o, offer=offer).count(), 1)
        self.assertEqual(OfferApplication.objects.get(pos_order=o).discount_amount, D('25.00'))


# ── incentives ───────────────────────────────────────────────────────────────
P_START, P_END = date(2026, 10, 1), date(2026, 10, 31)


def _row(doc, user, item, qty, price, r_doc=None, day=5):
    # engine._COL_* order: docnumber, usercode, docdate, branchcode, r_docnumber, itemcode, itemname,
    # transqty, price, itemexpirydate
    return (doc, user, datetime(2026, 10, day, 11, 0), '130', r_doc, item, f'I{item}', qty, price, None)


SALES = [_row('S1', '501', 'X1', D('2'), D('100.00')), _row('S2', '501', 'X2', D('1'), D('33.33')),
         _row('S3', '502', 'X1', D('5'), D('100.00'))]
RETURNS = [_row('R1', '501', 'X1', D('1'), D('100.00'), r_doc='S1', day=9)]


def _fake_fetch(doc_code, start, end, person_codes=None, use_returns_template=False):
    return list(RETURNS if use_returns_template else SALES)


@mock.patch.object(IE, '_fetch_cross_period_returns', return_value=[])
@mock.patch.object(IE, '_fetch_rows', side_effect=_fake_fetch)
class IncentivePeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        _, self.u1, _ = make_user('r2_inc_1')
        _, self.u2, _ = make_user('r2_inc_2')
        for p, code in ((self.u1, '501'), (self.u2, '502')):
            p.softech_user_id = code
            p.save(update_fields=['softech_user_id'])
        _, self.admin, self.api = make_user('r2_inc_admin', role='admin', access_all=True)
        self.prog = IncentiveProgram.objects.create(name='R2', start_date=P_START, end_date=P_END)
        IncentiveRule.objects.create(program=self.prog, incentive_type='percent', incentive_value=D('10'))

    def rows(self):
        return sorted((t.user_id, t.doc_no, t.doc_type, t.item_code, t.quantity, t.unit_price,
                       t.incentive_amount, t.is_reversed)
                      for t in IncentiveTransaction.objects.filter(program=self.prog))

    def calc(self, **kw):
        return IE.calculate(self.prog.id, P_START, P_END, **kw)

    def finalize(self):
        for p in (self.u1, self.u2):
            IncentiveSettlement.objects.create(program=self.prog, user=p, period_start=P_START, period_end=P_END,
                                               is_finalized=True, finalized_by=self.admin)

    def test_same_period_twice_gives_identical_rows(self, *_):
        self.calc()
        first = self.rows()
        self.assertEqual(len(first), 4)                       # 3 sales + 1 return
        self.calc()
        self.assertEqual(self.rows(), first)
        # percent rule: qty × price × 10%; the return is the negative mirror
        amounts = {(r[1], r[2]): r[6] for r in first}
        self.assertEqual(amounts[('S1', 'sale')], D('20.0000'))
        self.assertEqual(amounts[('S2', 'sale')], D('3.3330'))
        self.assertEqual(amounts[('S3', 'sale')], D('50.0000'))
        self.assertEqual(amounts[('R1', 'return')], D('-10.0000'))

    def test_finalized_period_refuses_recalculation(self, *_):
        self.calc()
        before = self.rows()
        self.finalize()
        with self.assertRaises(ValueError):
            self.calc()
        self.assertEqual(self.rows(), before)
        self.assertEqual(IncentiveSettlement.objects.filter(program=self.prog, is_finalized=True).count(), 2)

    def test_finalized_period_answers_409_over_the_api(self, *_):
        self.calc()
        self.finalize()
        url = f'/api/incentives/programs/{self.prog.id}/calculate/'
        r = self.api.post(url, {'period_start': '2026-10-01', 'period_end': '2026-10-31'}, format='json')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertTrue(IncentiveSettlement.objects.filter(program=self.prog, is_finalized=True).exists())

    def test_forced_recalculation_unfinalizes_the_period(self, *_):
        self.calc()
        before = self.rows()
        self.finalize()
        self.calc(force=True)
        self.assertEqual(self.rows(), before)
        for s in IncentiveSettlement.objects.filter(program=self.prog):
            self.assertEqual((s.is_finalized, s.finalized_at, s.finalized_by_id), (False, None, None))

    def test_finalize_payout_is_transactions_plus_adjustments(self, *_):
        self.calc()
        r = self.api.post(f'/api/incentives/programs/{self.prog.id}/finalize/',
                          {'period_start': '2026-10-01', 'period_end': '2026-10-31'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        s1 = IncentiveSettlement.objects.get(program=self.prog, user=self.u1)
        self.assertEqual(s1.total_incentive, D('13.3330'))      # 20 + 3.333 − 10
        self.assertEqual(s1.final_payout, s1.total_incentive + s1.total_adjustments)
        self.assertTrue(s1.is_finalized)
