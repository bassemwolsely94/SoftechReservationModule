"""
apps/tests/test_pos_checkout_tenders.py — D-18 server tender split (pricing.resolve_tenders) and the
basket hash. Pure: SimpleTestCase, no database (doc 39 §4.2).

Property tests use a SEEDED generator (no new dependency — doc 39 S7): 10 000 cases, fixed seed, the
failing case is printed. Properties: Σ rows = amount due exactly (Decimal equality, zero tolerance);
no negative or zero row; at most one نقدى and one آجل row; a platform account never has a نقدى row;
out-of-range intents raise ValueError with an Arabic message; same input → same output; the rows go
through split_payment and the balance check with zero difference.
"""
import random
import re
from decimal import Decimal, ROUND_HALF_UP

from django.test import SimpleTestCase

from apps.pos_orders import pricing
from apps.pos_orders.checkout import request_hash
from apps.pos_orders.models import CHANNEL_TO_PTCLASSIF, CLAIM_CHANNELS

SEED = 20261119
CASES = 10_000
Q2 = Decimal('0.01')
ARABIC = re.compile('[؀-ۿ]')
EDGE_VALUES = ['0.005', '1.005', '2.675', '0.015', '0.05', '0.45', '10.25', '99999.99', '0.01']
CHANNELS = sorted(CHANNEL_TO_PTCLASSIF)


def _r2(v):
    return Decimal(str(v)).quantize(Q2, rounding=ROUND_HALF_UP)


def _gen(rng):
    dv = (Decimal(rng.choice(EDGE_VALUES)) if rng.random() < 0.2
          else Decimal(rng.randint(1, 9_999_999)) / 100)
    cd = Decimal(rng.randint(0, 50)) / 100 if rng.random() < 0.5 else Decimal('0')
    channel = rng.choice(CHANNELS)
    platform = channel in CLAIM_CHANNELS and rng.random() < 0.1   # a platform account is a claim channel
    kind = rng.choice(pricing.TENDER_INTENT_KINDS)
    due = _r2(dv) - cd
    pick = rng.choice(['neg', 'zero', 'inside', 'equal', 'above', 'blank', 'odd'])
    amount = {'neg': -Decimal('1.00'), 'zero': Decimal('0'), 'equal': due, 'above': due + Decimal('0.01'),
              'inside': (due * Decimal(str(rng.random()))).quantize(Q2) if due > 0 else Decimal('0'),
              'blank': '', 'odd': Decimal(rng.randint(0, 100000)) / 1000}[pick]
    intent = {'kind': kind}
    if kind == 'credit_portion':
        intent['credit'] = str(amount)
    elif kind == 'patient_copay':
        intent['patient'] = str(amount)
    return dv, cd, channel, platform, intent


def _expected_valid(dv, cd, channel, platform, intent):
    """Independent statement of when resolve_tenders must succeed (None = returns None)."""
    kind = intent['kind']
    if platform and kind != 'default':
        return False
    if kind == 'default' and cd == 0 and not platform:
        return None
    due = _r2(dv) - cd
    if due <= 0:
        return False
    if kind == 'default':
        return True
    key = 'credit' if kind == 'credit_portion' else 'patient'
    if kind == 'credit_portion' and channel in ('cash', 'delivery'):
        return False
    if kind == 'patient_copay' and channel not in CLAIM_CHANNELS:
        return False
    if str(intent[key]).strip() == '':
        return False
    amt = _r2(intent[key])
    return Decimal('0') <= amt <= due


class ResolveTendersPropertyTests(SimpleTestCase):

    def test_generated_cases(self):
        rng = random.Random(SEED)
        for n in range(CASES):
            dv, cd, channel, platform, intent = _gen(rng)
            case = f'case #{n}: dv={dv} cd={cd} channel={channel} platform={platform} intent={intent}'
            want = _expected_valid(dv, cd, channel, platform, intent)

            def call():
                return pricing.resolve_tenders(channel, dv, cd, intent, is_platform=platform,
                                               claim_channels=CLAIM_CHANNELS)
            if want is False:
                with self.assertRaises(ValueError, msg=case) as ctx:
                    call()
                self.assertRegex(str(ctx.exception), ARABIC, case)
                continue
            rows = call()
            if want is None:
                self.assertIsNone(rows, case)
                continue
            due = _r2(dv) - cd
            self.assertEqual(sum((r['amount'] for r in rows), Decimal('0')), due, case)
            self.assertTrue(all(r['amount'] > 0 for r in rows), case)
            self.assertTrue(all(r['amount'] == r['amount'].quantize(Q2) for r in rows), case)
            types = [r['pay_type'] for r in rows]
            self.assertLessEqual(types.count('cash'), 1, case)
            self.assertLessEqual(types.count('credit'), 1, case)
            self.assertTrue(set(types) <= {'cash', 'credit'}, case)
            if platform:
                self.assertNotIn('cash', types, case)
            if channel in ('cash', 'delivery'):
                self.assertNotIn('credit', types, case)
            self.assertEqual(rows, call(), case)                                  # idempotent
            # through split_payment + the writer's balance check with ZERO tolerance
            _, _, norm = pricing.split_payment(channel, dv, rows)
            total = sum((t['amount'] for t in norm), Decimal('0'))
            self.assertEqual(total - due, Decimal('0'), case)


class ResolveTendersExamplesTests(SimpleTestCase):
    R = staticmethod(lambda *a, **k: pricing.resolve_tenders(*a, claim_channels=CLAIM_CHANNELS, **k))

    def test_default_without_change_discount_leaves_todays_rules(self):
        for ch in CHANNELS:
            self.assertIsNone(self.R(ch, '275.40', '0', {'kind': 'default'}))

    def test_default_with_change_discount_is_one_row_of_the_channel_default(self):
        self.assertEqual(self.R('cash', '275.40', '0.40', {'kind': 'default'}),
                         [{'pay_type': 'cash', 'amount': Decimal('275.00')}])
        self.assertEqual(self.R('employee', '275.40', '0.40', {'kind': 'default'}),
                         [{'pay_type': 'credit', 'amount': Decimal('275.00')}])

    def test_classic_float_edges(self):
        self.assertEqual(self.R('permanent', '1.005', '0', {'kind': 'credit_portion', 'credit': '0.5'}),
                         [{'pay_type': 'cash', 'amount': Decimal('0.51')},
                          {'pay_type': 'credit', 'amount': Decimal('0.50')}])
        self.assertEqual(self.R('contract', '2.675', '0', {'kind': 'patient_copay', 'patient': '2.675'}),
                         [{'pay_type': 'cash', 'amount': Decimal('2.68')}])

    def test_platform_is_all_credit_and_refuses_other_intents(self):
        self.assertEqual(self.R('contract', '100', '0', {'kind': 'default'}, is_platform=True),
                         [{'pay_type': 'credit', 'amount': Decimal('100.00')}])
        with self.assertRaises(ValueError):
            self.R('contract', '100', '0', {'kind': 'patient_copay', 'patient': '10'}, is_platform=True)

    def test_credit_refused_on_walk_in_channels(self):
        for ch in ('cash', 'delivery'):
            with self.assertRaises(ValueError):
                self.R(ch, '100', '0', {'kind': 'credit_portion', 'credit': '10'})

    def test_unknown_intent(self):
        with self.assertRaises(ValueError):
            self.R('cash', '100', '0', {'kind': 'card'})


def _js_to_fixed2(x: float) -> Decimal:
    """JavaScript Number.prototype.toFixed(2): the exact binary value, ties to the larger n."""
    return Decimal(x).quantize(Q2, rounding=ROUND_HALF_UP)


def _browser_net(lines, change_discount):
    """usePosOrder.js `totals` (~558–590) ported line for line: float maths + toFixed."""
    net = 0.0
    for price, qty, disc in lines:
        line_net = float(_js_to_fixed2(price * (1 - disc / 100))) * qty
        net += line_net
    net = max(0.0, net - change_discount)
    return _js_to_fixed2(net)


def _server_due(lines, change_discount):
    rows = [pricing.compute_line(item_sale_price=Decimal(str(p)), sale_tax_pct=0, qty=Decimal(str(q)),
                                 cust_discp=Decimal(str(d))) for p, q, d in lines]
    return pricing.compute_header(rows)['doc_value'] - Decimal(str(change_discount))


class BrowserVsServerTotalTests(SimpleTestCase):
    """Doc 39 §4.2 parity property: MEASURES finding F2 (browser float total vs server Decimal total)
    instead of guessing. The count is printed; the new path never uses the browser number."""

    def test_measure_one_piaster_disagreements(self):
        rng = random.Random(SEED)
        diffs, worst = 0, Decimal('0')
        n_baskets = 2000
        for _ in range(n_baskets):
            lines = []
            for _ in range(rng.randint(1, 6)):
                price = rng.randint(50, 200000) / 100
                qty = rng.choice([1, 2, 3, 0.5, 0.33333, 0.25, 1.5])
                disc = rng.choice([0, 5, 7.5, 10, 12.5, 15, 25, 33])
                lines.append((price, qty, disc))
            cd = rng.choice([0, 0, 0.25, 0.5])
            b, s = _browser_net(lines, cd), _server_due(lines, cd)
            if b != s:
                diffs += 1
                worst = max(worst, abs(b - s))
        print(f'\n[D-18 F2] browser vs server due: {diffs}/{n_baskets} baskets differ, worst {worst}')
        self.assertLessEqual(worst, Decimal('1.00'))     # a sanity bound, not the finding itself


class RequestHashTests(SimpleTestCase):
    BASE = {'branch': 3, 'channel': 'cash', 'doc_kind': 'sale', 'softech_pic': '',
            'lines': [{'softech_itemcode': '107295', 'qty': 1, 'item_sale_price': 108, 'cust_discp': 15}],
            'checkout': {'tender_intent': {'kind': 'default'}}}

    def _h(self, **over):
        import copy
        d = copy.deepcopy(self.BASE)
        d.update(over)
        return request_hash(d)

    def test_number_spelling_does_not_change_the_hash(self):
        same = self._h(lines=[{'softech_itemcode': '107295', 'qty': '1.00', 'item_sale_price': '108.0',
                               'cust_discp': '15'}], branch='3')
        self.assertEqual(self._h(), same)

    def test_basket_changes_change_the_hash(self):
        base = self._h()
        self.assertNotEqual(base, self._h(channel='delivery'))
        self.assertNotEqual(base, self._h(change_discount='0.25'))
        self.assertNotEqual(base, self._h(lines=[{'softech_itemcode': '107295', 'qty': 2,
                                                  'item_sale_price': 108, 'cust_discp': 15}]))
        self.assertNotEqual(base, self._h(checkout={'tender_intent': {'kind': 'credit_portion', 'credit': 5}}))

    def test_mode_and_expected_due_do_not_change_the_basket(self):
        """A dry run followed by the live press of the same basket is the same basket."""
        self.assertEqual(self._h(), self._h(checkout={'mode': 'live', 'confirm': True, 'expected_due': '91.80',
                                                      'tender_intent': {'kind': 'default'}}))
