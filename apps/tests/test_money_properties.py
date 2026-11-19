"""
Full audit Wave 4 — property-based tests (Hypothesis) on the deterministic money code.

docs/full-project-audit/10_TEST_STRATEGY_AND_RESULTS.md ("Property-based") and 13_IMPLEMENTATION_ROADMAP.md
Wave 4. The example tests (test_money_pos, test_offers_engine) pin the golden values; these check the RULES
for any input Hypothesis can build:

  * strip / pack quantity  — apps/pos_orders/writer.strips_to_qty: Q = round(K / packqty, 5) half-up,
                              and loose_units_from_qty inverts it;
  * VAT (inclusive)        — apps/pos_orders/pricing.compute_line / compute_header;
  * tender split           — pricing.split_payment and writer._contract_copay_tenders;
  * offers cap             — apps/offers/engine: _percent (max_discount_amount), _fixed, _cap_to_posdiscp,
                              and evaluate_offers end to end.

Properties: totals reconcile to the piaster, no negative line, rounding is idempotent, a cap is never
exceeded. SimpleTestCase only (no database); every run uses the same examples (derandomize) so CI never
flakes, and max_examples stays modest for CI time.
"""
import math
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from apps.offers import engine as E
from apps.pos_orders import pricing, writer

D = Decimal
C1 = D('0.01')

PROPS = settings(max_examples=80, deadline=None, derandomize=True, database=None,
                 suppress_health_check=[HealthCheck.too_slow])


def money(lo='0.00', hi='5000.00'):
    """2-dp EGP amounts, as SOFTECH stores prices."""
    return st.decimals(min_value=D(lo), max_value=D(hi), places=2, allow_nan=False, allow_infinity=False)


def pct(hi='100.00'):
    return st.decimals(min_value=D('0.00'), max_value=D(hi), places=2, allow_nan=False, allow_infinity=False)


def places(v):
    return -v.as_tuple().exponent if v.as_tuple().exponent < 0 else 0


# ── strip / pack quantity ──────────────────────────────────────────────────────

def _half_up_5(k, n):
    """Exact oracle: round(k/n, 5) half-up with integers only (k, n ≥ 0)."""
    scaled = Fraction(k * 100000, n)
    whole = math.floor(scaled + Fraction(1, 2))
    return D(whole) / D(100000)


class StripQuantityProperties(SimpleTestCase):

    @PROPS
    @given(k=st.integers(min_value=0, max_value=20000), n=st.integers(min_value=2, max_value=1000))
    @example(k=2, n=3)          # production goldens: 0.66667 / 0.71429 / 2.85714
    @example(k=5, n=7)
    @example(k=20, n=7)
    def test_q_is_k_over_packqty_half_up_at_5_places(self, k, n):
        q = writer.strips_to_qty(k, n)
        self.assertEqual(q, _half_up_5(k, n))
        self.assertLessEqual(places(q), 5)
        self.assertGreaterEqual(q, 0)
        self.assertLessEqual(abs(q * n - k), D('0.000005') * n)       # never more than half a step off

    @PROPS
    @given(k=st.integers(min_value=0, max_value=20000), n=st.integers(min_value=1, max_value=1000))
    def test_rounding_is_idempotent(self, k, n):
        q = writer.strips_to_qty(k, n)
        self.assertEqual(q.quantize(D('0.00001'), rounding=ROUND_HALF_UP), q)
        self.assertEqual(writer.strips_to_qty(k, n), q)                       # same input → same Q

    @PROPS
    @given(k=st.integers(min_value=0, max_value=20000), n=st.integers(min_value=1, max_value=1000))
    def test_loose_units_round_trip(self, k, n):
        """SOFTECH's Pkg+Unit split of Q gives back the strips: whole packs + round(frac(Q)×n) = K."""
        q = writer.strips_to_qty(k, n)
        packs, loose = math.floor(q), writer.loose_units_from_qty(q, n)
        self.assertEqual(packs * n + loose, k)
        self.assertTrue(0 <= loose < n or (n == 1 and loose == 0))

    @PROPS
    @given(n=st.integers(min_value=-5, max_value=1))
    def test_packqty_of_one_or_less_is_whole_units(self, n):
        self.assertEqual(writer.strips_to_qty(7, n), D(7))

    @PROPS
    @given(k=st.decimals(min_value=D('-50'), max_value=D('5000'), places=2), n=st.integers(2, 100))
    def test_no_negative_quantity_and_fractional_strips_round_half_up(self, k, n):
        q = writer.strips_to_qty(k, n)
        self.assertGreaterEqual(q, 0)
        whole = max(0, int(k.to_integral_value(rounding=ROUND_HALF_UP)))
        self.assertEqual(q, writer.strips_to_qty(whole, n))


# ── VAT (inclusive) on the POS line + header ──────────────────────────────────

line_inputs = st.fixed_dictionaries({
    'item_sale_price': money('0.00', '9999.99'),
    'sale_tax_pct': st.sampled_from([D('0'), D('5'), D('10'), D('14'), D('14.00'), D('22.5')]),
    'qty': st.one_of(st.integers(1, 50).map(D),
                     st.builds(writer.strips_to_qty, st.integers(1, 200), st.integers(2, 30))),
    'cust_discp': pct(),
    'new_cost_price': st.decimals(min_value=D('0'), max_value=D('9999.9999'), places=4),
})


class VatProperties(SimpleTestCase):

    @PROPS
    @given(line=line_inputs)
    def test_line_follows_the_6d_formulas_to_the_piaster(self, line):
        out = pricing.compute_line(**line)
        isp, disc, qty, taxp = (line['item_sale_price'], line['cust_discp'], line['qty'], line['sale_tax_pct'])
        tp = (isp * (1 - disc / 100)).quantize(C1, rounding=ROUND_HALF_UP)
        self.assertEqual(out['trans_price'], tp)
        self.assertEqual(out['trans_price_total'], (tp * qty).quantize(C1, rounding=ROUND_HALF_UP))
        for key, dp in (('trans_price', 2), ('trans_price_total', 2), ('item_sale_tax', 4),
                        ('item_sale_price_tax', 4), ('line_cogs', 2), ('line_gross', 2)):
            self.assertLessEqual(places(out[key]), dp, key)
            self.assertEqual(out[key], out[key].quantize(D(1).scaleb(-dp), rounding=ROUND_HALF_UP), key)

    @PROPS
    @given(line=line_inputs)
    def test_vat_is_inside_the_net_and_never_negative(self, line):
        out = pricing.compute_line(**line)
        total, tax, taxp = out['trans_price_total'], out['item_sale_tax'], line['sale_tax_pct']
        self.assertGreaterEqual(out['trans_price'], 0)                  # no negative line
        self.assertGreaterEqual(total, 0)
        self.assertGreaterEqual(tax, 0)
        self.assertLessEqual(tax, total)
        if taxp == 0:
            self.assertEqual(tax, 0)
        else:
            exact = total - total / (1 + taxp / 100)
            self.assertLessEqual(abs(tax - exact), D('0.00005'))       # 4-dp rounding only
            ex_vat = total - tax
            self.assertLessEqual(abs(ex_vat * (1 + taxp / 100) - total), D('0.0001') * (1 + taxp / 100))

    @PROPS
    @given(line=line_inputs)
    def test_discount_never_raises_the_price(self, line):
        out = pricing.compute_line(**line)
        list_total = (line['item_sale_price'] * line['qty']).quantize(C1, rounding=ROUND_HALF_UP)
        self.assertEqual(out['line_gross'], list_total)
        self.assertLessEqual(out['trans_price'], line['item_sale_price'])
        self.assertLessEqual(out['trans_price_total'], list_total)

    @PROPS
    @given(lines=st.lists(line_inputs, min_size=1, max_size=12))
    def test_header_reconciles_with_its_lines(self, lines):
        outs = [pricing.compute_line(**l) for l in lines]
        h = pricing.compute_header(outs)
        self.assertEqual(h['doc_value'], sum((o['trans_price_total'] for o in outs), D('0')))   # exact
        self.assertEqual(h['doc_value_gross'], sum((o['line_gross'] for o in outs), D('0')))
        self.assertEqual(h['doc_value_cogs'], sum((o['line_cogs'] for o in outs), D('0')))
        vat = sum((o['item_sale_tax'] for o in outs), D('0'))
        self.assertEqual(h['doc_value_tax'], vat.quantize(C1, rounding=ROUND_HALF_UP))
        self.assertLessEqual(h['doc_value_tax'], h['doc_value'])
        self.assertEqual(pricing.compute_header(outs), h)                   # deterministic

    @PROPS
    @given(lines=st.lists(line_inputs, min_size=1, max_size=8), seed=st.randoms(use_true_random=False))
    def test_header_does_not_depend_on_line_order(self, lines, seed):
        outs = [pricing.compute_line(**l) for l in lines]
        shuffled = list(outs)
        seed.shuffle(shuffled)
        self.assertEqual(pricing.compute_header(shuffled), pricing.compute_header(outs))


# ── tender split ──────────────────────────────────────────────────────────────

CHANNELS = ['cash', 'delivery', 'contract', 'employee', 'permanent', 'talabat']


class TenderSplitProperties(SimpleTestCase):

    @PROPS
    @given(channel=st.sampled_from(CHANNELS), doc_value=money('0.00', '99999.99'))
    def test_default_tender_covers_the_whole_invoice(self, channel, doc_value):
        pay, patient, tenders = pricing.split_payment(channel, doc_value)
        self.assertEqual(sum((t['amount'] for t in tenders), D('0')), doc_value)
        self.assertEqual(len(tenders), 1)
        credit = channel in ('contract', 'employee')
        self.assertEqual(tenders[0]['pay_type'], 'credit' if credit else 'cash')
        self.assertEqual(pay, D('0.00') if credit else doc_value)
        self.assertEqual(patient, D('0.00') if channel in ('cash', 'delivery') else pay)

    @PROPS
    @given(channel=st.sampled_from(CHANNELS),
           parts=st.lists(st.tuples(st.sampled_from(['cash', 'card', 'credit', 'wallet']), money('0.00', '3000')),
                          min_size=1, max_size=5))
    def test_collected_now_is_the_non_credit_part(self, channel, parts):
        tenders = [{'pay_type': p, 'amount': str(a)} for p, a in parts]
        total = sum((a for _, a in parts), D('0'))
        pay, patient, norm = pricing.split_payment(channel, total, tenders)
        self.assertEqual(sum((t['amount'] for t in norm), D('0')), total)          # nothing lost
        self.assertEqual(pay, sum((a for p, a in parts if p != 'credit'), D('0')))
        self.assertGreaterEqual(pay, 0)
        self.assertLessEqual(pay, total)
        self.assertEqual([t['pay_type'] for t in norm], [p for p, _ in parts])

    @PROPS
    @given(net=money('0.01', '50000'), extra=money('0.00', '5000'), pct_=pct('100.00'),
           paytype=st.sampled_from(['1', '2', '', None]))
    def test_contract_copay_reconciles_to_the_piaster(self, net, extra, pct_, paytype):
        gross = net + extra                                     # gross ≥ net (discounts only lower it)
        with mock.patch.object(writer, 'read_contract_copay',
                               return_value={'patient_paypercent': pct_, 'patient_paytype': paytype}):
            t = writer._contract_copay_tenders(None, net, gross)
        base = gross if paytype == '1' else net
        patient = (pct_ / 100 * base).quantize(C1, rounding=ROUND_HALF_UP)
        if pct_ <= 0 or patient <= 0 or patient >= net:
            self.assertIsNone(t)                                # default 100% آجل posture
            return
        self.assertEqual([x['pay_type'] for x in t], ['cash', 'credit'])
        cash, credit = D(t[0]['amount']), D(t[1]['amount'])
        self.assertEqual(cash, patient)
        self.assertEqual(cash + credit, net)                    # exact, to the piaster
        self.assertGreater(cash, 0)
        self.assertGreater(credit, 0)


# ── offers cap ────────────────────────────────────────────────────────────────

def _lines(rows):
    out = []
    for i, (qty, price, posdiscp) in enumerate(rows):
        item = SimpleNamespace(pos_discp=posdiscp, cost_price=D('0'), id=i + 1)
        out.append(E._Line(index=i, item=item, softech_id=str(i), qty=qty, unit_price=price))
    return out


line_rows = st.lists(st.tuples(st.integers(1, 20), money('0.00', '800'), pct()), min_size=1, max_size=8)


def _offer(offer_id=1, **kw):
    base = dict(id=offer_id, name='T', name_ar='ت', offer_type='percent', authorization_source='offer',
                value=D('10'), max_discount_amount=None, status='active', starts_at=None, ends_at=None,
                segments=[], channels=[], min_basket_amount=D('0'), min_qty=0, max_uses_total=None,
                max_uses_per_customer=None, stackable=True, priority=0, requires_approval=False,
                require_stock=False, target_all=True)
    base.update(kw)
    return SimpleNamespace(**base)


_EMPTY_CACHE = {'item_ids': set(), 'category_ids': set(), 'tag_ids': set(), 'tagged_item_ids': set(),
                'exclude_ids': set(), 'classification_filters': {}, 'spec': {}, 'stock_ids': None}

# Hypothesis-found: the "last line absorbs the rounding" step in _percent (cap) and _fixed can hand the
# last line a NEGATIVE discount (a surcharge) — e.g. three lines whose earlier shares each round up while
# the last line's gross is 0.00. evaluate_offers then only caps lines at their gross (min), never at zero.
NEGATIVE_LAST_LINE = ('Wave 4 property test found a real bug (not fixed here — money change needs the owner, '
                      'CLAUDE.md stop-and-ask): engine._percent / _fixed give the last qualifying line '
                      '`total − Σ rounded shares`, which goes below zero when the earlier shares round up and the '
                      'last line is tiny (gross 0.00/0.01). A negative per-line discount is a hidden surcharge.')


class OffersCapProperties(SimpleTestCase):

    @PROPS
    @given(rows=line_rows, value=pct(), cap=money('0.01', '500'))
    def test_percent_cap_is_never_exceeded(self, rows, value, cap):
        lines = _lines(rows)
        per = E._percent(_offer(value=value, max_discount_amount=cap), lines)
        uncapped = sum(((l.gross * value / 100).quantize(C1, rounding=ROUND_HALF_UP) for l in lines), D('0'))
        total = sum(per.values(), D('0'))
        self.assertLessEqual(total, cap if uncapped > cap else uncapped)
        if uncapped > cap:
            self.assertEqual(total, cap)                         # the cap is reached exactly, to the piaster
        for amt in per.values():
            self.assertEqual(amt, amt.quantize(C1))

    @PROPS
    @given(rows=line_rows, value=pct(), cap=money('0.01', '500'))
    @example(rows=[(1, D('0.03'), D('0')), (1, D('0.03'), D('0')), (1, D('0.00'), D('0'))],
             value=D('100.00'), cap=D('0.03'))
    def test_percent_cap_never_gives_a_negative_line(self, rows, value, cap):
        lines = _lines(rows)
        per = E._percent(_offer(value=value, max_discount_amount=cap), lines)
        for l in lines:
            self.assertGreaterEqual(per[l.index], 0, NEGATIVE_LAST_LINE)

    @PROPS
    @given(rows=line_rows, value=money('0.00', '3000'))
    def test_fixed_amount_is_spread_exactly(self, rows, value):
        lines = _lines(rows)
        subtotal = sum((l.gross for l in lines), D('0'))
        per = E._fixed(_offer(offer_type='fixed', value=value), lines)
        if subtotal <= 0:
            self.assertEqual(per, {})
            return
        self.assertEqual(sum(per.values(), D('0')), min(value, subtotal))       # exact, to the piaster

    @PROPS
    @given(rows=line_rows, value=money('0.00', '3000'))
    @example(rows=[(1, D('0.01'), D('0'))] * 4, value=D('0.02'))
    def test_fixed_amount_never_gives_a_negative_line(self, rows, value):
        lines = _lines(rows)
        assume(sum((l.gross for l in lines), D('0')) > 0)
        per = E._fixed(_offer(offer_type='fixed', value=value), lines)
        for l in lines:
            self.assertGreaterEqual(per[l.index], 0, NEGATIVE_LAST_LINE)

    def test_plan_never_raises_a_line_above_its_gross(self):
        """End to end: a 0.02 fixed offer on four 0.01 lines (e.g. low-priced or free gift lines) — the last
        line's share is −0.01, so its net (0.02) is above its own gross (0.01)."""
        basket = [{'softech_id': str(i), 'qty': 1, 'unit_price': D('0.01')} for i in range(4)]
        with mock.patch.object(E, '_target_cache', return_value=dict(_EMPTY_CACHE)):
            plan = E.evaluate_offers(basket, offers=[_offer(offer_type='fixed', value=D('0.02'))])
        self.assertEqual(plan['total_discount'], D('0.02'))
        for line in plan['applied'][0]['lines']:
            self.assertGreaterEqual(line['discount'], 0, NEGATIVE_LAST_LINE)

    @PROPS
    @given(rows=line_rows, value=pct())
    def test_item_card_ceiling_is_never_exceeded(self, rows, value):
        lines = _lines(rows)
        per = E._cap_to_posdiscp(E._percent(_offer(value=value), lines), lines)
        for l in lines:
            ceiling = (l.gross * l.pos_discp / 100).quantize(C1, rounding=ROUND_HALF_UP)
            self.assertLessEqual(per[l.index], ceiling)
            self.assertGreaterEqual(per[l.index], 0)

    @PROPS
    @given(rows=line_rows,
           offers=st.lists(st.tuples(st.sampled_from(['percent', 'fixed']), money('0.00', '150'),
                                     st.one_of(st.none(), money('0.01', '300')), st.booleans(),
                                     st.sampled_from(['offer', 'item_card'])),
                           min_size=1, max_size=4))
    def test_plan_discount_never_exceeds_the_basket(self, rows, offers):
        objs = [_offer(i + 1, offer_type=t, value=min(v, D('100')) if t == 'percent' else v,
                       max_discount_amount=cap, stackable=stack, authorization_source=src)
                for i, (t, v, cap, stack, src) in enumerate(offers)]
        basket = [{'softech_id': str(i), 'qty': q, 'unit_price': p} for i, (q, p, _) in enumerate(rows)]
        with mock.patch.object(E, '_target_cache', return_value=dict(_EMPTY_CACHE)):
            plan = E.evaluate_offers(basket, offers=objs)
            again = E.evaluate_offers(basket, offers=objs)
        self.assertEqual(plan, again)                                   # deterministic
        self.assertLessEqual(plan['total_discount'], plan['basket_total'])
        self.assertGreaterEqual(plan['net_total'], 0)
        self.assertEqual(plan['net_total'], plan['basket_total'] - plan['total_discount'])
        expected_total = sum(((D(q) * p).quantize(C1, rounding=ROUND_HALF_UP) for q, p, _ in rows), D('0'))
        self.assertEqual(plan['basket_total'], expected_total)
        for applied in plan['applied']:
            o = objs[applied['offer_id'] - 1]
            if o.max_discount_amount is not None and o.offer_type == 'percent':
                self.assertLessEqual(applied['discount'], o.max_discount_amount)


class OffersBoundsRepairTests(SimpleTestCase):
    """The repair after the rounding split (owner asked for the fix 2026-11-19): only out-of-bounds lines
    change, the offer's total never does."""

    def test_the_two_repro_cases(self):
        from decimal import Decimal as D
        from apps.offers.engine import _keep_in_bounds
        # fixed 0.02 on four 0.01 lines: the split gave [0.01, 0.01, 0.01, -0.01]
        out = _keep_in_bounds({0: D('0.01'), 1: D('0.01'), 2: D('0.01'), 3: D('-0.01')},
                              {0: D('0.01'), 1: D('0.01'), 2: D('0.01'), 3: D('0.01')})
        self.assertEqual(out, {0: D('0.00'), 1: D('0.01'), 2: D('0.01'), 3: D('0')})
        self.assertEqual(sum(out.values()), D('0.02'))
        # 100% capped at 0.03 on lines 0.03 / 0.03 / 0.00: the split gave [0.02, 0.02, -0.01]
        out = _keep_in_bounds({0: D('0.02'), 1: D('0.02'), 2: D('-0.01')},
                              {0: D('0.03'), 1: D('0.03'), 2: D('0.00')})
        self.assertEqual(out, {0: D('0.01'), 1: D('0.02'), 2: D('0')})
        self.assertEqual(sum(out.values()), D('0.03'))

    def test_an_in_bounds_split_is_untouched(self):
        from decimal import Decimal as D
        from apps.offers.engine import _keep_in_bounds
        per = {0: D('3.33'), 1: D('3.33'), 2: D('3.34')}
        self.assertEqual(_keep_in_bounds(per, {0: D('10'), 1: D('10'), 2: D('10')}), per)
