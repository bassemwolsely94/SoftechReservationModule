"""
Doc 25 §21 — B1 purchase-writer pilot readiness. Live posting needs the master switch AND the
case's branch in the pilot list; the purchase carries the poster's SOFTECH user; a pre-write guard
refuses to send anything that differs from the approved calculation; the golden comparison is
read-only and leaves nothing in PG.
"""
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from apps.invoices.models import SupplierInvoice
from apps.replacement import golden
from apps.replacement import legs as LG
from apps.replacement.models import CaseException as X, PostingOperation as Op, ReplacementCase as RC

from . import test_replacement_workflow as TW

D = Decimal
LIVE_130 = dict(REPLACEMENT_POSTING_ENABLED=True, REPLACEMENT_POSTING_BRANCHES=('130',))


class PilotGateTests(TW._Base):
    approved = TW.LegTests.approved

    def prepared(self):
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version, expiries={'100186': '2028-09-09'})
        return c, op

    def post(self, c, op, user=None):
        return LG.post(c.pk, op.op_id, user=user or self.sup, version=RC.objects.get(pk=c.pk).version)

    @override_settings(REPLACEMENT_POSTING_ENABLED=True)          # switch on, but no pilot branch
    def test_master_switch_alone_stays_dry_run(self):
        c, op = self.prepared()
        seen = []
        with mock.patch('apps.invoices.writer.push_final', side_effect=TW._fake_push_final(seen=seen)):
            op = self.post(c, op)
        self.assertEqual((op.status, seen[0]['dry_run']), (Op.ST_DRY_RUN, True))
        self.assertFalse(LG.posting_enabled(RC.objects.get(pk=c.pk)))

    @override_settings(**LIVE_130)
    def test_pilot_branch_posts_live_under_the_posters_softech_user(self):
        c, op = self.prepared()
        seen = []
        with mock.patch('apps.invoices.writer.push_final', side_effect=TW._fake_push_final(seen=seen)):
            op = self.post(c, op)
        self.assertEqual(op.status, Op.ST_VERIFIED)
        self.assertEqual([(s['dry_run'], s['usercode'], s['line_extra']) for s in seen],
                         [(False, '1330', LG.purchase_line_extra)])

    @override_settings(**LIVE_130)
    def test_live_post_without_a_softech_user_is_refused(self):
        c, op = self.prepared()
        self.sup.softech_user_id = ''
        self.sup.save(update_fields=['softech_user_id'])
        with mock.patch('apps.invoices.writer.push_final') as pf, self.assertRaises(ValidationError):
            self.post(c, op)
        pf.assert_not_called()

    @override_settings(**LIVE_130)
    def test_precheck_blocks_a_purchase_that_differs_from_the_approval(self):
        c, op = self.prepared()
        line = op.supplier_invoice.lines.get()
        line.unit_price = D('6000')                                    # what would post ≠ approved 5,618.90
        line.save(update_fields=['unit_price'])
        with mock.patch('apps.invoices.writer.push_final') as pf:
            op = self.post(c, op)
        pf.assert_not_called()                                         # nothing sent to SOFTECH
        self.assertEqual(op.status, Op.ST_FAILED)
        self.assertIn('فحص ما قبل الترحيل', op.error)
        self.assertTrue(X.objects.filter(case_id=c.pk, exception_type='posting_failed', severity='high').exists())

    @override_settings(**LIVE_130)
    def test_live_post_needs_every_expiry(self):
        c = self.approved()
        op = LG.prepare_purchase(c.pk, user=self.sup, version=c.version)          # no expiry captured
        self.assertEqual(op.supplier_invoice.lines.get().expiry_date, '')
        self.assertEqual(LG.precheck_purchase(op), [])                            # fine for a dry run
        with mock.patch('apps.invoices.writer.push_final') as pf:
            op = self.post(c, op)
        pf.assert_not_called()
        self.assertIn('تاريخ الصلاحية مطلوب', op.error)

    def test_expiry_is_validated_and_reaches_the_plan(self):
        c = self.approved()
        with self.assertRaises(ValidationError):
            LG.prepare_purchase(c.pk, user=self.sup, version=c.version, expiries={'100186': '2020-01-01'})
        op = LG.prepare_purchase(c.pk, user=self.sup, version=RC.objects.get(pk=c.pk).version,
                                 expiries={'100186': '2028-09-09', '999999': '2029-01-01'})   # unknown code ignored
        from apps.invoices import writer as IW
        self.assertEqual(IW.build_plan(op.supplier_invoice)['lines'][0]['itemexpirydate'], '2028-09-09')

    def vat_entry(self, op):
        """What the writer's engine produces for a 14 % item: tax split out of the public price."""
        line = op.supplier_invoice.lines.get()
        return line, {'_line': line, 'qty': 1.0, 'transprice': 5618.9, 'transprice_total': 5618.9,
                      'itemsalestax': 985.84, 'itemsaleprice': 8027.0, 'itemsaleprice_tax': 7041.23,
                      'pharmacydiscp': 20.2, 'additionaldiscp': 0.0, 'origintaxp': 0.0}

    def test_vat_line_posts_in_softech_buyback_form_and_passes_the_guard(self):
        """Owner option A: tax 0, sale price with tax = public, discount = the approved %."""
        _, op = self.prepared()
        line, entry = self.vat_entry(op)
        extra = LG.purchase_line_extra(entry)
        self.assertEqual(extra, {'custdiscp': 1.0, 'itemsalestax': 0.0, 'itemsaleprice_tax': 8027.0,
                                 'pharmacydiscp': 30.0})
        with mock.patch('apps.invoices.writer.compute', return_value=([entry], {'doc_value': 5618.9})):
            self.assertEqual(LG.precheck_purchase(op), [])
        self.assertEqual(LG.purchase_line_extra({**entry, 'itemsalestax': 0}), {'custdiscp': 1.0})   # non-VAT

    def test_vat_line_with_a_public_price_off_the_approval_is_refused(self):
        _, op = self.prepared()
        line, entry = self.vat_entry(op)
        line.public_price = D('9000')                                  # ≠ approved public 8,027
        with mock.patch('apps.invoices.writer.compute', return_value=([entry], {'doc_value': 5618.9})):
            problems = LG.precheck_purchase(op)
        self.assertTrue(any('سعر الجمهور' in p for p in problems))

    def test_writer_applies_a_per_line_extra_and_still_accepts_a_dict(self):
        from apps.invoices import writer as IW
        _, op = self.prepared()
        inv = op.supplier_invoice
        self.assertEqual(IW.build_plan(inv, line_extra={'custdiscp': 1.0})['lines'][0]['custdiscp'], 1.0)   # coupons
        plan = IW.build_plan(inv, line_extra=lambda c: {'custdiscp': 2.0, 'storecode2': c['_line'].item.softech_id})
        self.assertEqual((plan['lines'][0]['custdiscp'], plan['lines'][0]['storecode2']), (2.0, '100186'))

    def test_precheck_passes_for_the_approved_purchase(self):
        _, op = self.prepared()
        self.assertEqual(LG.precheck_purchase(op), [])

    def test_dry_run_also_runs_the_precheck(self):
        c, op = self.prepared()
        line = op.supplier_invoice.lines.get()
        line.quantity = D('2')
        line.save(update_fields=['quantity'])
        op = self.post(c, op)
        self.assertEqual(op.status, Op.ST_FAILED)

    def test_serializer_reports_the_per_branch_gate(self):
        c = self.approved()
        with override_settings(**LIVE_130):
            self.assertTrue(self.sup_api.get(f'/api/replacement/cases/{c.pk}/').data['workflow']['posting_enabled'])
        with override_settings(REPLACEMENT_POSTING_ENABLED=True, REPLACEMENT_POSTING_BRANCHES=('140',)):
            self.assertFalse(self.sup_api.get(f'/api/replacement/cases/{c.pk}/').data['workflow']['posting_enabled'])


class GoldenCompareTests(TW._Base):
    """The comparison itself — SOFTECH is replaced by an in-memory native document."""

    def native(self, transprice='5618.900', supplier='4471'):
        hdr = {'branchcode': '130', 'doccode': '10', 'docnumber': 12095, 'docdate': '2026-07-21 00:00:00',
               'cust_branch_code': supplier, 'docvalue': 5618.9, 'storecode': '130', 'fatstatuscode': '10',
               'ptcode': '20', 'usercode': '1309', 'docnumber2': 21072026}
        line = {'branchcode': '130', 'doccode': '10', 'docnumber': 12095, 'itemcode': '100186', 'transqty': 1.0,
                'transprice': float(transprice), 'transprice_total': float(transprice), 'pharmacydiscp': 30.0,
                'itemsaleprice_tax': 8027.0, 'storecode': '130', 'suppliercode': supplier, 'personcode': supplier,
                'dblitemflag': 1, 'newqty': 7.0, 'usercode': '1309'}
        return hdr, [line]

    def test_compare_leaves_nothing_in_pg_and_ignores_save_time_fields(self):
        before = SupplierInvoice.objects.count()
        from datetime import date
        rep = golden.compare('130', 12095, date(2026, 7, 21), native=self.native())
        self.assertEqual(SupplierInvoice.objects.count(), before)        # rolled back
        fields = {d['field'] for d in rep['diff']['header']} | {d['field'] for d in rep['diff']['lines']}
        self.assertFalse(fields & (golden.IGNORED_HEADER | golden.IGNORED_LINE))
        self.assertEqual(rep['supplier'], '4471')

    def test_compare_flags_a_planted_difference(self):
        from datetime import date
        rep = golden.compare('130', 12095, date(2026, 7, 21), native=self.native())
        planted = golden.compare('130', 12095, date(2026, 7, 21), native=self.native(transprice='5000'))
        # rebuilt from the native transprice, so the planted cost shows up as a value / line difference
        self.assertNotEqual(rep['plan_value'], planted['plan_value'])

    def test_diff_plan_is_column_by_column(self):
        plan = {'header': {'docvalue': 100, 'storecode': '130', 'docnumber': '<next>'},
                'lines': [{'itemcode': '1', 'transprice': 10, 'newqty': '<x>'}, {'itemcode': '2', 'transprice': 5}]}
        d = golden.diff_plan({'docvalue': 100.004, 'storecode': '131', 'docnumber': 9},
                             [{'itemcode': '1', 'transprice': 10.5, 'newqty': 3}, {'itemcode': '3'}], plan)
        self.assertEqual([h['field'] for h in d['header']], ['storecode'])
        self.assertEqual([(l['itemcode'], l['field']) for l in d['lines']], [('1', 'transprice')])
        self.assertEqual((d['missing_lines'], d['extra_lines'], d['identical']), (['3'], ['2'], False))
