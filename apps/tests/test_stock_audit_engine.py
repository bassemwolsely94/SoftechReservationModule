"""
apps/tests/test_stock_audit_engine.py

Doc 32 Phase 2 — the checks (apps/stock_audit/rules.py), thresholds (params.py) and the
engine's finding lifecycle (engine.py). Pure rule tests use unsaved ledger lines; engine tests
write StockLedgerLine rows directly. No Sybase.
"""
import datetime as _dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.stock_audit.models import (StockAuditFinding, StockAuditRule, StockAuditRuleOverride,
                                     StockLedgerLine)
from apps.stock_audit.params import ParamError, effective, ensure_rules, validate_params
from apps.stock_audit.rules import (RULES, RuleContext, adjustments_by_user, check_duplicate_line,
                                    check_price_variance_invoice, check_sale_below_cost,
                                    check_stock_adjustment, net_unit_price)

TODAY = _dt.date(2026, 10, 26)
T0 = timezone.make_aware(_dt.datetime(2026, 10, 25, 10, 0))


def ln(**kw):
    base = dict(branchcode='160', doccode='115', docnumber=1000, docdate=_dt.date(2026, 10, 25),
                trans_time=T0, storecode='160', usercode='166', personcode='1', itemcode='100001',
                transqty=Decimal('1'), newqty=Decimal('5'), transprice=Decimal('100'),
                newcostprice=Decimal('80'), itemsaleprice=Decimal('100'), itemsalestax=Decimal('0'),
                itemsaleprice_tax=Decimal('100'), additionaldiscp=Decimal('0'), itemexpirydate=_dt.date(2028, 1, 1))
    base.update({k: (Decimal(str(v)) if isinstance(v, (int, float)) and k in (
        'transqty', 'newqty', 'transprice', 'newcostprice', 'itemsaleprice', 'itemsalestax',
        'itemsaleprice_tax', 'additionaldiscp') else v) for k, v in kw.items()})
    return StockLedgerLine(**base)


def ctx(**kw):
    return RuleContext(_dt.date(2026, 9, 27), TODAY + _dt.timedelta(days=1), **kw)


def p(code, **kw):
    return {**RULES[code]['defaults'], **kw}


# ── 1. below cost ─────────────────────────────────────────────────────────────

class SaleBelowCostTests(SimpleTestCase):

    def test_flags_loss_above_both_floors(self):
        out = check_sale_below_cost([ln(transprice=70, newcostprice=80, transqty=3)], p('sale_below_cost'), ctx())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['value_egp'], Decimal('30.00'))   # (80−70) × 3
        self.assertEqual(out[0]['severity'], 'warning')

    def test_both_floors_must_be_met(self):
        # 12.5% but only 10 EGP → below the 20 EGP floor
        self.assertEqual(check_sale_below_cost([ln(transprice=70)], p('sale_below_cost'), ctx()), [])
        # 1,000 EGP lost but only 1% → below the 5% floor
        self.assertEqual(check_sale_below_cost(
            [ln(transprice=990, newcostprice=1000, transqty=100)], p('sale_below_cost'), ctx()), [])

    def test_critical_needs_the_floors_too(self):
        # 50% loss but 2 EGP: the critical % alone must not create a finding
        self.assertEqual(check_sale_below_cost([ln(transprice=2, newcostprice=4)], p('sale_below_cost'), ctx()), [])
        out = check_sale_below_cost([ln(transprice=40, newcostprice=80)], p('sale_below_cost'), ctx())
        self.assertEqual(out[0]['severity'], 'critical')            # 50%, 40 EGP

    def test_vat_is_removed_before_comparing(self):
        # gross 45 > cost 42, but net of 14% VAT = 39.47 < 42 → a real loss the workbook missed
        taxed = ln(transprice=45, newcostprice=42, transqty=10, itemsalestax=Decimal('5.5263'),
                   additionaldiscp=14, itemsaleprice=45, itemsaleprice_tax=Decimal('39.4737'))
        self.assertAlmostEqual(float(net_unit_price(taxed)), 39.4737, places=3)
        out = check_sale_below_cost([taxed], p('sale_below_cost'), ctx())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['value_egp'], Decimal('25.26'))
        # the same prices on an untaxed item are a profit
        self.assertEqual(check_sale_below_cost([ln(transprice=45, newcostprice=42, transqty=10)],
                                               p('sale_below_cost'), ctx()), [])

    def test_free_pack_customers_are_excluded(self):
        for code in ('4785', '4283'):
            self.assertEqual(check_sale_below_cost([ln(personcode=code, transprice=Decimal('0.17'), newcostprice=1211)],
                                                   p('sale_below_cost'), ctx()), [])

    def test_credit_channel_and_excluded_items(self):
        line = ln(transprice=40, newcostprice=80)
        c = ctx(channel_of_invoice={('160', 1000, line.docdate): '15'}, channel_bucket={'15': 'credit'})
        self.assertEqual(check_sale_below_cost([line], p('sale_below_cost'), c), [])
        self.assertEqual(check_sale_below_cost([line], p('sale_below_cost'), ctx(excluded_item_codes={'100001'})), [])

    def test_returns_and_zero_cost_are_ignored(self):
        self.assertEqual(check_sale_below_cost([ln(doccode='30', transprice=40)], p('sale_below_cost'), ctx()), [])
        self.assertEqual(check_sale_below_cost([ln(transprice=40, newcostprice=0)], p('sale_below_cost'), ctx()), [])


# ── 2. duplicates ─────────────────────────────────────────────────────────────

class DuplicateTests(SimpleTestCase):

    def test_same_line_twice_in_one_document_only_when_switched_on(self):
        lines = [ln(), ln(trans_time=T0 + _dt.timedelta(seconds=5))]
        self.assertEqual(check_duplicate_line(lines, p('duplicate_line'), ctx()), [])     # default off
        out = check_duplicate_line(lines, p('duplicate_line', include_same_document=True), ctx())
        self.assertEqual([o['evidence']['kind'] for o in out], ['same_document'])
        self.assertEqual(out[0]['value_egp'], Decimal('80.00'))

    def test_split_expiry_is_not_a_duplicate(self):
        self.assertEqual(check_duplicate_line([ln(), ln(itemexpirydate=_dt.date(2027, 6, 1))],
                                              p('duplicate_line', include_same_document=True), ctx()), [])

    def test_sale_then_return_is_not_a_duplicate(self):
        self.assertEqual(check_duplicate_line([ln(), ln(doccode='30', docnumber=50)], p('duplicate_line'), ctx()), [])

    def _doc(self, number, minutes, items=('100001', '100002'), person='1'):
        return [ln(docnumber=number, itemcode=i, personcode=person, trans_time=T0 + _dt.timedelta(minutes=minutes))
                for i in items]

    def test_identical_documents_within_window(self):
        out = check_duplicate_line(self._doc(1, 0) + self._doc(2, 10), p('duplicate_line'), ctx())
        self.assertEqual([o['evidence']['kind'] for o in out], ['identical_documents'])
        self.assertEqual(out[0]['evidence']['documents'], [1, 2])

    def test_identical_documents_outside_window_or_other_customer(self):
        self.assertEqual(check_duplicate_line(self._doc(1, 0) + self._doc(2, 25), p('duplicate_line'), ctx()), [])
        self.assertEqual(check_duplicate_line(self._doc(1, 0) + self._doc(2, 5, person='9'), p('duplicate_line'), ctx()), [])

    def test_single_line_repeat_sales_are_normal(self):
        # two customers each buying one Panadol 5 minutes apart
        self.assertEqual(check_duplicate_line(self._doc(1, 0, items=('100001',)) + self._doc(2, 5, items=('100001',)),
                                              p('duplicate_line'), ctx()), [])

    def test_returned_copy_counts_as_corrected(self):
        c = ctx(returned_invoices={('160', 2, _dt.date(2026, 10, 25))})
        self.assertEqual(check_duplicate_line(self._doc(1, 0) + self._doc(2, 10), p('duplicate_line'), c), [])


# ── 3. price variance ─────────────────────────────────────────────────────────

class PriceVarianceTests(SimpleTestCase):

    def test_two_prices_on_one_invoice(self):
        out = check_price_variance_invoice([ln(transprice=100), ln(transprice=80, transqty=2)],
                                           p('price_variance_invoice'), ctx())
        self.assertEqual(out[0]['severity'], 'info')                  # 1.25
        self.assertEqual(out[0]['value_egp'], Decimal('40.00'))       # (100−80) × 2
        out = check_price_variance_invoice([ln(transprice=100), ln(transprice=50)], p('price_variance_invoice'), ctx())
        self.assertEqual(out[0]['severity'], 'warning')               # 2.0 > 1.5

    def test_small_difference_and_near_zero_price_ignored(self):
        self.assertEqual(check_price_variance_invoice([ln(transprice=100), ln(transprice=95)],
                                                      p('price_variance_invoice'), ctx()), [])
        # the workbook's 9999 ratio: a 0.01 line is under the 1 EGP floor
        self.assertEqual(check_price_variance_invoice([ln(transprice=100), ln(transprice=Decimal('0.01'))],
                                                      p('price_variance_invoice'), ctx()), [])


# ── 5. adjustments ────────────────────────────────────────────────────────────

class AdjustmentTests(SimpleTestCase):

    def test_single_large_adjustment(self):
        out = check_stock_adjustment([ln(doccode='150', transqty=10, newcostprice=60)], p('stock_adjustment'), ctx())
        self.assertEqual((out[0]['severity'], out[0]['value_egp']), ('warning', Decimal('600.00')))
        out = check_stock_adjustment([ln(doccode='160', transqty=30, newcostprice=80)], p('stock_adjustment'), ctx())
        self.assertEqual(out[0]['severity'], 'critical')              # 2,400 EGP write-off

    def test_repeated_adjustments_on_one_item(self):
        lines = [ln(doccode=c, docnumber=i, transqty=1, newcostprice=10, docdate=_dt.date(2026, 10, 10 + i))
                 for i, c in enumerate(['150', '50', '150'])]
        out = check_stock_adjustment(lines, p('stock_adjustment'), ctx())
        self.assertEqual([o['evidence']['kind'] for o in out], ['repeated'])
        self.assertEqual(out[0]['evidence']['net_qty'], '-1')         # −1 +1 −1
        self.assertEqual(check_stock_adjustment(lines[:2], p('stock_adjustment'), ctx()), [])

    def test_old_adjustments_outside_days_not_counted(self):
        lines = [ln(doccode='150', docnumber=i, newcostprice=10, docdate=_dt.date(2026, 8, 1 + i)) for i in range(3)]
        self.assertEqual(check_stock_adjustment(lines, p('stock_adjustment'), ctx()), [])

    def test_ranking_by_user(self):
        rank = adjustments_by_user([ln(doccode='150', usercode='7', transqty=2, newcostprice=50),
                                    ln(doccode='50', usercode='8', newcostprice=10), ln(doccode='115')])
        self.assertEqual([(r['usercode'], r['value_egp']) for r in rank], [('7', Decimal('100.00')), ('8', Decimal('10.00'))])


# ── thresholds ────────────────────────────────────────────────────────────────

class ParamTests(TestCase):

    def test_validation(self):
        self.assertEqual(validate_params('price_variance_invoice', {'ratio': '1.2'}), {'ratio': 1.2})
        for bad in ({'ratio': 'x'}, {'ratio': 0.5}, {'nope': 1}):
            with self.assertRaises(ParamError):
                validate_params('price_variance_invoice', bad)
        with self.assertRaises(ParamError):
            validate_params('sale_below_cost', {'excluded_personcodes': 'all'})
        with self.assertRaises(ParamError):
            validate_params('price_variance_invoice', {'ratio': 1.2}, partial=False)
        self.assertEqual(validate_params('duplicate_line', {'include_same_document': True}),
                         {'include_same_document': True})
        with self.assertRaises(ParamError):
            validate_params('duplicate_line', {'include_same_document': 'yes'})

    def test_branch_override_merges_over_chain(self):
        from apps.branches.models import Branch
        rules = ensure_rules()
        r = rules['sale_below_cost']
        r.params = {**r.params, 'min_loss_egp': 50}
        r.save()
        b = Branch.objects.create(softech_branch_id='160', name='B160', name_ar='فرع ١٦٠')
        o = StockAuditRuleOverride.objects.create(rule=r, branch=b, params={'min_loss_pct': 10}, enabled=False)
        en, prm = effective(r, o)
        self.assertEqual((en, prm['min_loss_pct'], prm['min_loss_egp'], prm['critical_loss_pct']), (False, 10, 50, 30))

    def test_ensure_rules_keeps_owner_values(self):
        ensure_rules()
        r = StockAuditRule.objects.get(code='stock_adjustment')
        r.params = {'single_egp': 900}                                # owner value; other keys dropped
        r.save()
        ensure_rules()
        r.refresh_from_db()
        self.assertEqual(r.params['single_egp'], 900)
        self.assertEqual(r.params['count'], 3)                        # missing default restored


# ── engine lifecycle ──────────────────────────────────────────────────────────

class EngineTests(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        self.branch = Branch.objects.create(softech_branch_id='160', name='B160', name_ar='فرع ١٦٠')

    def run_engine(self, **kw):
        from apps.stock_audit.engine import run_stock_audit
        return run_stock_audit(today=TODAY, triggered_by='test', **kw)

    def test_rerun_is_idempotent_and_keeps_review(self):
        ln(transprice=40, newcostprice=80).save()
        run1 = self.run_engine()
        self.assertEqual(run1.status, 'success')
        self.assertEqual(run1.counts['sale_below_cost']['new'], 1)
        f = StockAuditFinding.objects.get()
        self.assertIn('فرع ١٦٠', f.message_ar)                        # branch name, not a bare code
        f.status, f.review_note = StockAuditFinding.ST_REVIEWED, 'checked with branch'
        f.save()
        run2 = self.run_engine()
        self.assertEqual(run2.counts['sale_below_cost'], {'new': 0, 'updated': 1, 'reopened': 0, 'seen': 1})
        f.refresh_from_db()
        self.assertEqual((f.status, f.first_run_id, f.last_run_id), ('reviewed', run1.pk, run2.pk))

    def test_dismissed_reopens_only_when_value_grows_over_half(self):
        StockLedgerLine.objects.create(**{k: v for k, v in ln(transprice=40, newcostprice=80).__dict__.items()
                                          if not k.startswith('_') and k != 'id'})
        self.run_engine()
        f = StockAuditFinding.objects.get()
        f.status = StockAuditFinding.ST_DISMISSED
        f.save()
        StockLedgerLine.objects.update(transqty=Decimal('1.4'))       # +40%: stays dismissed
        self.run_engine()
        f.refresh_from_db()
        self.assertEqual(f.status, 'dismissed')
        StockLedgerLine.objects.update(transqty=Decimal('3'))         # 56 → 120 EGP: reopened
        run = self.run_engine()
        f.refresh_from_db()
        self.assertEqual((f.status, run.counts['sale_below_cost']['reopened']), ('open', 1))
        self.assertIn('أعيد فتحها', f.review_note)

    def test_branch_override_can_switch_a_rule_off(self):
        ln(transprice=40, newcostprice=80).save()
        r = ensure_rules()['sale_below_cost']
        StockAuditRuleOverride.objects.create(rule=r, branch=self.branch, enabled=False)
        run = self.run_engine(rules=['sale_below_cost'])
        self.assertEqual(run.counts['sale_below_cost']['seen'], 0)
        self.assertEqual(run.params_used['sale_below_cost'], {})

    def test_staff_and_item_are_linked(self):
        from apps.catalog.models import Item
        from django.contrib.auth.models import User
        from apps.users.models import StaffProfile
        item = Item.objects.create(softech_id='100001', name='TEST ITEM')
        u = User.objects.create(username='u166')
        staff = StaffProfile.objects.create(user=u, role='salesperson', softech_user_id='166')
        ln(transprice=40, newcostprice=80).save()
        self.run_engine(rules=['sale_below_cost'])
        f = StockAuditFinding.objects.get()
        self.assertEqual((f.item_id, f.staff_id, f.branch_id), (item.pk, staff.pk, self.branch.pk))
        self.assertIn('TEST ITEM', f.message_ar)

    def test_adjustment_rule_reads_its_own_lookback(self):
        # engine window 3 days, but rule 5 counts the last 30
        for i in range(3):
            ln(doccode='150', docnumber=i, newcostprice=10, docdate=_dt.date(2026, 10, 5 + i)).save()
        run = self.run_engine(days=3, rules=['stock_adjustment'])
        self.assertEqual(run.counts['stock_adjustment']['seen'], 1)


class MergeSameKeyTests(TestCase):

    def test_split_lines_with_one_key_become_one_finding(self):
        from apps.branches.models import Branch
        from apps.stock_audit.engine import run_stock_audit
        Branch.objects.create(softech_branch_id='160', name='B160', name_ar='فرع ١٦٠')
        ln(transprice=40, newcostprice=80, transqty=1).save()
        ln(transprice=40, newcostprice=90, transqty=2, itemexpirydate=_dt.date(2027, 3, 1)).save()
        run = run_stock_audit(today=TODAY, rules=['sale_below_cost'])
        self.assertEqual(run.status, 'success')
        f = StockAuditFinding.objects.get()
        self.assertEqual((f.value_egp, f.severity), (Decimal('140.00'), 'critical'))   # 40 + 2 × 50
        self.assertEqual(len(f.evidence['merged']), 1)


# ── Phase 4: checks 4, 6, 10, 11 ──────────────────────────────────────────────

from apps.stock_audit.rules import (check_adjustment_after_count, check_cost_fluctuation,  # noqa: E402
                                    check_frequent_stockout, check_return_without_invoice)


class CostFluctuationTests(SimpleTestCase):

    def purchase(self, number, day, price, qty=10):
        return ln(doccode='10', docnumber=number, docdate=_dt.date(2026, 10, day), transprice=price, transqty=qty,
                  trans_time=timezone.make_aware(_dt.datetime(2026, 10, day, 12)))

    def test_change_against_previous_document(self):
        out = check_cost_fluctuation([self.purchase(1, 5, 100), self.purchase(2, 20, 125)],
                                     p('cost_fluctuation'), ctx())
        self.assertEqual((len(out), out[0]['severity'], out[0]['value_egp']), (1, 'info', Decimal('250.00')))
        out = check_cost_fluctuation([self.purchase(1, 5, 100), self.purchase(2, 20, 40)], p('cost_fluctuation'), ctx())
        self.assertEqual(out[0]['severity'], 'warning')                     # -60%
        self.assertIn('انخفاض', out[0]['message_ar'])

    def test_small_change_same_document_and_free_goods_ignored(self):
        self.assertEqual(check_cost_fluctuation([self.purchase(1, 5, 100), self.purchase(2, 20, 115)],
                                                p('cost_fluctuation'), ctx()), [])
        self.assertEqual(check_cost_fluctuation([self.purchase(1, 5, 100), self.purchase(1, 5, 150)],
                                                p('cost_fluctuation'), ctx()), [])     # one document
        self.assertEqual(check_cost_fluctuation([self.purchase(1, 5, 100), self.purchase(2, 20, 0)],
                                                p('cost_fluctuation'), ctx()), [])     # FOC line

    def test_other_supplier_free_goods_and_virtual_suppliers(self):
        other = ln(doccode='10', docnumber=2, docdate=_dt.date(2026, 10, 20), transprice=150, transqty=1, personcode='565')
        self.assertEqual(check_cost_fluctuation([self.purchase(1, 5, 100), other], p('cost_fluctuation'), ctx()), [])
        self.assertEqual(len(check_cost_fluctuation([self.purchase(1, 5, 100), other],
                                                    p('cost_fluctuation', same_supplier_only=False), ctx())), 1)
        foc = ln(doccode='10', docnumber=2, docdate=_dt.date(2026, 10, 20), transprice=Decimal('3.89'),
                 transqty=1, pharmacydiscp=100)                     # SOFTECH free goods: VAT-only price
        self.assertEqual(check_cost_fluctuation([self.purchase(1, 5, 100), foc], p('cost_fluctuation'), ctx()), [])
        virt = [ln(doccode='10', docnumber=n, docdate=_dt.date(2026, 10, d), transprice=pr, transqty=1, personcode='4470')
                for n, d, pr in ((1, 5, 100), (2, 20, 200))]
        self.assertEqual(check_cost_fluctuation(virt, p('cost_fluctuation'), ctx()), [])

    def test_previous_purchase_too_old(self):
        old = ln(doccode='10', docnumber=1, docdate=_dt.date(2026, 6, 1), transprice=100, transqty=1)
        self.assertEqual(check_cost_fluctuation([old, self.purchase(2, 20, 150)], p('cost_fluctuation'), ctx()), [])


class FrequentStockoutTests(SimpleTestCase):

    def zeros(self, n, item='100001'):
        return [ln(itemcode=item, docnumber=i, newqty=0, docdate=_dt.date(2026, 10, 10 + i)) for i in range(n)]

    def c(self, rate=2, medicine=True):
        return ctx(medicine_items={'100001'} if medicine else set(), monthly_qty={('160', '100001'): Decimal(rate)},
                   on_hand={('160', '100001'): Decimal('4')})

    def test_three_stockouts_of_a_selling_medicine(self):
        out = check_frequent_stockout(self.zeros(3), p('frequent_stockout'), self.c())
        self.assertEqual((len(out), out[0]['severity'], out[0]['metric']), (1, 'info', Decimal(3)))
        self.assertIn('4.00', out[0]['message_ar'])

    def test_not_enough_slow_mover_or_not_medicine(self):
        self.assertEqual(check_frequent_stockout(self.zeros(2), p('frequent_stockout'), self.c()), [])
        self.assertEqual(check_frequent_stockout(self.zeros(3), p('frequent_stockout'), self.c(rate=Decimal('0.5'))), [])
        self.assertEqual(check_frequent_stockout(self.zeros(3), p('frequent_stockout'), self.c(medicine=False)), [])

    def test_stock_left_after_the_line_is_not_a_stockout(self):
        lines = self.zeros(2) + [ln(docnumber=9, newqty=1, docdate=_dt.date(2026, 10, 20))]
        self.assertEqual(check_frequent_stockout(lines, p('frequent_stockout'), self.c()), [])


class ReturnWithoutInvoiceTests(SimpleTestCase):

    SALE = ('160', 5000, _dt.date(2026, 10, 1), '100001')

    def ret(self, qty=1, ref=5000, ref_date=_dt.date(2026, 10, 1), number=70):
        return ln(doccode='30', docnumber=number, transqty=qty, transprice=50, r_docnumber=ref, r_docdate=ref_date)

    def c(self, sold=Decimal('2'), returned=None):
        return ctx(sales={self.SALE: sold} if sold is not None else {},
                   returns_total={self.SALE: returned} if returned is not None else {},
                   ledger_from=_dt.date(2025, 10, 27))

    def test_no_invoice_number(self):
        out = check_return_without_invoice([self.ret(ref=None, ref_date=None)], p('return_without_invoice'), self.c())
        self.assertEqual((out[0]['evidence']['kind'], out[0]['severity'], out[0]['value_egp']),
                         ('no_invoice', 'warning', Decimal('50.00')))

    def test_partial_return_is_fine(self):
        self.assertEqual(check_return_without_invoice([self.ret(qty=1)], p('return_without_invoice'),
                                                      self.c(returned=Decimal('1'))), [])

    def test_over_returned_across_all_returns(self):
        out = check_return_without_invoice([self.ret(qty=1)], p('return_without_invoice'),
                                           self.c(returned=Decimal('3')))   # earlier return of 2 + this 1
        self.assertEqual((out[0]['evidence']['kind'], out[0]['severity'], out[0]['value_egp']),
                         ('over_returned', 'critical', Decimal('50.00')))

    def test_item_not_on_invoice_and_old_reference_skipped(self):
        out = check_return_without_invoice([self.ret()], p('return_without_invoice'), self.c(sold=None))
        self.assertEqual(out[0]['evidence']['kind'], 'invoice_not_found')
        old = self.ret(ref_date=_dt.date(2025, 1, 1))
        self.assertEqual(check_return_without_invoice([old], p('return_without_invoice'), self.c(sold=None)), [])


class AdjustmentAfterCountTests(SimpleTestCase):

    SNAP = timezone.make_aware(_dt.datetime(2026, 10, 20, 9))

    def c(self, expected, counted):
        row = {'session_id': 7, 'snapshot_at': self.SNAP, 'expected': Decimal(expected),
               'counted': Decimal(counted), 'difference': Decimal(counted) - Decimal(expected)}
        return ctx(counts={('160', '100001'): [row]})

    def adj(self, code, qty, hours=5):
        return ln(doccode=code, transqty=qty, docdate=_dt.date(2026, 10, 20),
                  trans_time=self.SNAP + _dt.timedelta(hours=hours))

    def test_posting_the_counted_difference_is_normal(self):
        self.assertEqual(check_adjustment_after_count([self.adj('150', 2)], p('adjustment_after_count'), self.c(10, 8)), [])

    def test_mismatch_and_adjusting_a_matched_item(self):
        out = check_adjustment_after_count([self.adj('150', 5)], p('adjustment_after_count'), self.c(10, 8))
        self.assertEqual((out[0]['metric'], out[0]['threshold'], out[0]['value_egp']),
                         (Decimal('-5.00'), Decimal('-2.00'), Decimal('240.00')))   # 3 units x 80
        out = check_adjustment_after_count([self.adj('50', 1)], p('adjustment_after_count'), self.c(10, 10))
        self.assertEqual(len(out), 1)                                            # counted OK, still adjusted

    def test_outside_the_window_is_ignored(self):
        self.assertEqual(check_adjustment_after_count([self.adj('150', 5, hours=60)],
                                                      p('adjustment_after_count'), self.c(10, 8)), [])


class Phase4EngineTests(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        Branch.objects.create(softech_branch_id='160', name='B160', name_ar='فرع ١٦٠')

    def test_cost_compares_with_purchase_before_the_window(self):
        from apps.stock_audit.engine import run_stock_audit
        ln(doccode='10', docnumber=1, docdate=_dt.date(2026, 10, 1), transprice=100, transqty=1).save()
        ln(doccode='10', docnumber=2, docdate=_dt.date(2026, 10, 25), transprice=140, transqty=1).save()
        run = run_stock_audit(days=3, today=TODAY, rules=['cost_fluctuation'])
        self.assertEqual(run.counts['cost_fluctuation']['new'], 1)

    def test_over_return_found_through_the_mirror(self):
        from apps.stock_audit.engine import run_stock_audit
        ln(doccode='115', docnumber=5000, docdate=_dt.date(2026, 10, 1), transqty=1).save()
        for n, day in ((70, 10), (71, 24)):
            ln(doccode='30', docnumber=n, docdate=_dt.date(2026, 10, day), transqty=1,
               r_docnumber=5000, r_docdate=_dt.date(2026, 10, 1)).save()
        run = run_stock_audit(days=5, today=TODAY, rules=['return_without_invoice'])
        f = StockAuditFinding.objects.get(rule_code='return_without_invoice')
        self.assertEqual((f.evidence['kind'], Decimal(f.evidence['returned']), Decimal(f.evidence['sold'])),
                         ('over_returned', Decimal('2'), Decimal('1')))
        self.assertEqual(run.status, 'success')


# ── Check 9: entries outside working hours ────────────────────────────────────

from apps.branches.hours import HoursError, minutes_outside, validate_windows  # noqa: E402
from apps.stock_audit.rules import check_after_hours_entry  # noqa: E402

LATE = [{'from': '08:00', 'to': '01:00'}]
HQ = [{'from': '08:00', 'to': '21:00', 'label': 'المخزن'},
      {'from': '09:00', 'to': '24:00', 'label': 'الكول سنتر', 'doccodes': ['115', '125']}]


def at(h, m=0, **kw):
    t = timezone.make_aware(_dt.datetime(2026, 10, 25, h, m))
    return ln(trans_time=t, **kw)


class BranchHoursTests(SimpleTestCase):

    def test_overnight_window_and_grace(self):
        self.assertEqual(minutes_outside(LATE, 0 * 60 + 45, '115'), 0)       # 00:45 still open
        self.assertEqual(minutes_outside(LATE, 1 * 60 + 20, '115', grace=30), 0)
        self.assertEqual(minutes_outside(LATE, 3 * 60, '115', grace=30), 90)  # 03:00 = 90 min after 01:30
        self.assertEqual(minutes_outside(LATE, 7 * 60, '115', grace=30), 30)  # 07:00 = 30 min before 07:30

    def test_window_for_some_documents_only(self):
        self.assertEqual(minutes_outside(HQ, 23 * 60, '125'), 0)             # call center until midnight
        self.assertEqual(minutes_outside(HQ, 23 * 60, '10'), 120)            # warehouse closed at 21:00

    def test_validation(self):
        self.assertEqual(validate_windows([{'from': '09:00', 'to': '24:00', 'doccodes': [115]}]),
                         [{'from': '09:00', 'to': '24:00', 'doccodes': ['115']}])
        for bad in ([{'from': '8:00', 'to': '10:00'}], [{'from': '08:00', 'to': '08:00'}],
                    [{'from': '08:00', 'to': '25:00'}], [{'from': '08:00'}], 'x'):
            with self.assertRaises(HoursError):
                validate_windows(bad)


class AfterHoursTests(SimpleTestCase):

    def c(self, hours):
        return ctx(branch_hours={'160': hours})

    def test_flags_one_finding_per_document(self):
        lines = [at(3, 10), at(3, 11, itemcode='100002')]
        out = check_after_hours_entry(lines, p('after_hours_entry'), self.c({'is_24h': False, 'windows': LATE}))
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]['metric'], out[0]['severity']), (Decimal(100), 'info'))   # 03:10 vs 01:30
        self.assertEqual(out[0]['value_egp'], Decimal('160.00'))
        self.assertIn('03:10', out[0]['message_ar'])

    def test_warning_when_far_outside(self):
        out = check_after_hours_entry([at(5)], p('after_hours_entry'), self.c({'is_24h': False, 'windows': LATE}))
        self.assertEqual(out[0]['severity'], 'warning')                       # 210 min > 120

    def test_open_hours_24h_unset_and_excluded_users(self):
        self.assertEqual(check_after_hours_entry([at(14)], p('after_hours_entry'),
                                                 self.c({'is_24h': False, 'windows': LATE})), [])
        self.assertEqual(check_after_hours_entry([at(4)], p('after_hours_entry'), self.c({'is_24h': True, 'windows': []})), [])
        self.assertEqual(check_after_hours_entry([at(4)], p('after_hours_entry'), ctx()), [])
        self.assertEqual(check_after_hours_entry([at(4, usercode='1509')], p('after_hours_entry', excluded_users=['1509']),
                                                 self.c({'is_24h': False, 'windows': LATE})), [])

    def test_hq_call_center_until_midnight(self):
        hq = self.c({'is_24h': False, 'windows': HQ})
        self.assertEqual(check_after_hours_entry([at(23, doccode='125')], p('after_hours_entry'), hq), [])
        out = check_after_hours_entry([at(23, doccode='10')], p('after_hours_entry'), hq)
        self.assertEqual(len(out), 1)                                          # purchase after the warehouse closed


class BranchHoursApiTests(TestCase):

    def test_admin_sets_hours_and_bad_hours_rejected(self):
        from apps.tests.factories import make_branch, make_user
        b = make_branch('فرع', 'B09')
        _, _, admin = make_user('hours_admin', role='admin', branch=b)
        r = admin.patch(f'/api/branches/{b.pk}/settings/', {'working_hours': LATE}, format='json')
        self.assertEqual((r.status_code, r.json()['working_hours']), (200, LATE))
        r = admin.patch(f'/api/branches/{b.pk}/settings/', {'working_hours': [{'from': '8', 'to': '9'}]}, format='json')
        self.assertEqual(r.status_code, 400)
