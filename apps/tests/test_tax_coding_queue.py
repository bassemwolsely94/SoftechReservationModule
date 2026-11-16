"""ETA production item coding queue (batch S1): the shared VAT-treatment confirmation and the queue built on it."""
from collections import Counter
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import Item
from apps.procurement.models import PurchaseLine, SupplierSegmentation
from apps.tax_invoicing import coding_queue, coding_rule, services
from apps.tax_invoicing.models import TaxAuditEvent, TaxCodingDecision, TaxItemProfile
from apps.tests.test_tax_invoicing import Fixture


class ConfirmTreatmentTests(Fixture, TestCase):
    def setUp(self):
        self.build('cq')

    def test_taxable_sets_rate_and_confirmation(self):
        p = TaxItemProfile(softech_itemcode='Q1')
        services.confirm_treatment(p, treatment='taxable', vat_rate='14', reference='', actor=self.accountant)
        self.assertEqual(p.tax_treatment, 'taxable')
        self.assertEqual(int(p.vat_rate), 14)
        self.assertIsNotNone(p.treatment_confirmed_at)
        self.assertEqual(p.treatment_confirmed_by, self.accountant)

    def test_exempt_without_reference_raises(self):
        p = TaxItemProfile(softech_itemcode='Q2')
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='exempt', vat_rate=0, reference=' ', actor=self.accountant)

    def test_exempt_with_reference_sets_vat_zero(self):
        p = TaxItemProfile(softech_itemcode='Q3')
        services.confirm_treatment(p, treatment='exempt', vat_rate=14, reference='م/1', actor=self.accountant)
        self.assertEqual(int(p.vat_rate), 0)
        self.assertEqual(p.treatment_reference, 'م/1')

    def test_unclassified_clears_confirmation(self):
        p = self.coded('Q4')
        services.confirm_treatment(p, treatment='unclassified', vat_rate=0, reference='', actor=self.accountant)
        self.assertIsNone(p.treatment_confirmed_at)
        self.assertIsNone(p.treatment_confirmed_by)

    def test_unknown_and_bad_taxable_rate(self):
        p = TaxItemProfile(softech_itemcode='Q5')
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='nope', vat_rate=0, reference='', actor=self.accountant)
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='taxable', vat_rate=0, reference='', actor=self.accountant)


EXEMPT_REF = 'سلعة معفاة — قانون الضريبة على القيمة المضافة رقم 67 لسنة 2016، جدول الإعفاءات'


def make_item(code, mtype='Medicine', tax=0, stockable=True, name=None):
    return Item.objects.create(softech_id=code, name=name or f'ITEM {code}', medicine_type_name=mtype,
                               sale_tax_pct=tax, is_stockable=stockable)


def bought(item_code, supplier, category, qty=5, doccode='10'):
    if category is not None:
        SupplierSegmentation.objects.update_or_create(supplier_code=supplier,
                                                      defaults={'supplier_category': category})
    PurchaseLine.objects.create(branch_code='HQ', supplier_code=supplier, doc_number=f'D{PurchaseLine.objects.count()}',
                                doc_date=date(2025, 6, 1), item_code=item_code, doccode=doccode, raw_qty=qty)


class RuleTests(TestCase):
    def test_services_and_gifts_keep_out(self):
        for item in (make_item('900001', 'Services خدمات'), make_item('900002', 'هدايا عملاء'),
                     make_item('900003', 'Medicine', stockable=False)):
            self.assertEqual(coding_rule.premark(item, Counter({'OFFICIAL_DISTRIBUTOR': 3})),
                             ('keep_out', 'services', 'خدمة / هدية — لا تُكوَّد حالياً'))

    def test_official_codes(self):
        item = make_item('900010')
        bought('900010', 'S1', 'DRUG_WAREHOUSE')
        src = coding_rule.purchase_sources(['900010'])['900010']
        self.assertEqual(coding_rule.premark(item, src), ('code', 'official', 'اشتُري من موزع أو مخزن أو مصنع'))

    def test_small_warehouse_only(self):
        item = make_item('900011')
        bought('900011', 'S2', 'SMALL_WAREHOUSE')
        src = coding_rule.purchase_sources(['900011'])['900011']
        self.assertEqual(coding_rule.premark(item, src), (
            'code', 'small_warehouse_only', 'اشتُري من مخازن صغيرة فقط — تأكد من تسجيله (هيئة الدواء / سلامة الغذاء)'))

    def test_unofficial_only_includes_unknown_supplier(self):
        item = make_item('900012')
        bought('900012', 'S3', 'PHARMACY')
        bought('900012', 'S4', None)   # no segmentation row = UNKNOWN
        src = coding_rule.purchase_sources(['900012'])['900012']
        self.assertEqual(src['UNKNOWN'], 5)
        self.assertEqual(coding_rule.premark(item, src), ('keep_out', 'unofficial_only', 'لم يُشترَ من موزع أو مخزن أو مصنع'))

    def test_no_purchase(self):
        expected = ('', 'no_purchase', 'لا مشتريات معتبرة منذ مايو 2025')
        self.assertEqual(coding_rule.premark(make_item('900013'), None), expected)
        self.assertEqual(coding_rule.premark(None, Counter()), expected)

    def test_no_catalog_row_follows_sources(self):
        self.assertEqual(coding_rule.premark(None, Counter({'MANUFACTURER': 1}))[1], 'official')

    def test_ignored_only_is_no_purchase(self):
        item = make_item('900014')
        bought('900014', 'S5', 'PATIENT_REPURCHASE')
        bought('900014', 'S6', 'INTERNAL_TRANSFER')
        bought('900014', 'S7', 'MANUFACTURER', doccode='120')   # returns are not purchases
        src = coding_rule.purchase_sources(['900014']).get('900014')
        self.assertEqual(coding_rule.premark(item, src)[1], 'no_purchase')

    def test_official_beats_unofficial(self):
        item = make_item('900015')
        bought('900015', 'S8', 'PHARMACY', qty=100)
        bought('900015', 'S9', 'MANUFACTURER', qty=1)
        src = coding_rule.purchase_sources(['900015'])['900015']
        self.assertEqual(coding_rule.premark(item, src)[:2], ('code', 'official'))

    def test_live_segmentation_not_line_category(self):
        bought('900016', 'S10', 'OFFICIAL_DISTRIBUTOR')
        PurchaseLine.objects.filter(item_code='900016').update(supplier_category='PHARMACY')
        self.assertEqual(set(coding_rule.purchase_sources(['900016'])['900016']), {'OFFICIAL_DISTRIBUTOR'})

    def test_sets(self):
        self.assertIn('SMALL_WAREHOUSE', coding_rule.OFFICIAL)
        self.assertIn('CLEARING', coding_rule.IGNORED)


class VatTests(Fixture, TestCase):
    def setUp(self):
        self.build('cv')

    def test_cosmetic_at_zero_flagged(self):
        rate, flagged, _ = coding_rule.vat_prefill(make_item('900020', 'Cosmetics', 0), None)
        self.assertEqual((rate, flagged), (Decimal('0'), True))

    def test_cosmetic_at_14_not_flagged(self):
        self.assertFalse(coding_rule.vat_prefill(make_item('900021', 'Cosmetics', 14), None)[1])

    def test_medicine_at_14_flagged(self):
        self.assertTrue(coding_rule.vat_prefill(make_item('900022', 'Medicine', 14), None)[1])

    def test_medicine_at_zero_not_flagged(self):
        self.assertFalse(coding_rule.vat_prefill(make_item('900023', 'Medicine', 0), None)[1])

    def test_odd_rate_flagged(self):
        rate, flagged, _ = coding_rule.vat_prefill(make_item('900024', 'Medicine', 13), None)
        self.assertEqual((rate, flagged), (Decimal('13'), True))

    def test_confirmed_profile_wins(self):
        p = self.coded('900025', rate=14)
        self.assertEqual(coding_rule.vat_prefill(make_item('900025', 'Medicine', 0), p),
                         (Decimal('14'), False, 'confirmed'))

    def test_unconfirmed_profile_uses_catalog(self):
        p = TaxItemProfile.objects.create(softech_itemcode='900026', vat_rate=14)
        self.assertEqual(coding_rule.vat_prefill(make_item('900026', 'Body Building', 0), p)[:2], (Decimal('0'), True))


class DecisionTests(Fixture, TestCase):
    def setUp(self):
        self.build('cd')
        self.item = make_item('900030', 'Cosmetics', 14, name='GLOW CREAM')
        self.p = TaxItemProfile.objects.create(softech_itemcode='900030', item=self.item)

    def test_code_14_confirms_taxable(self):
        d = coding_queue.decide(self.p.pk, self.accountant, decision='code', vat_rate=14)
        self.p.refresh_from_db()
        self.assertEqual((self.p.tax_treatment, int(self.p.vat_rate)), ('taxable', 14))
        self.assertIsNotNone(self.p.treatment_confirmed_at)
        self.assertEqual(self.p.treatment_confirmed_by, self.accountant)
        self.assertEqual((d.decision, int(d.vat_rate), d.decided_by), ('code', 14, self.accountant))
        self.assertEqual((d.code_name, d.code_name_ar, d.description, d.description_ar), ('GLOW CREAM',) * 4)
        self.assertTrue(TaxAuditEvent.objects.filter(action='coding_decision', entity_id='900030').exists())
        self.assertTrue(TaxAuditEvent.objects.filter(action='item_mapping_changed', entity_id='900030').exists())

    def test_code_0_is_exempt_with_reference(self):
        coding_queue.decide(self.p.pk, self.accountant, decision='code', vat_rate='0',
                            names={'code_name': 'X', 'code_name_ar': 'س'})
        self.p.refresh_from_db()
        self.assertEqual((self.p.tax_treatment, int(self.p.vat_rate)), ('exempt', 0))
        self.assertEqual(self.p.treatment_reference, EXEMPT_REF)
        d = TaxCodingDecision.objects.get(profile=self.p)
        self.assertEqual((d.code_name, d.code_name_ar, d.description), ('X', 'س', 'GLOW CREAM'))

    def test_code_needs_rate_0_or_14(self):
        for bad in (None, 5, 'x'):
            with self.assertRaises(services.TaxRuleError):
                coding_queue.decide(self.p.pk, self.accountant, decision='code', vat_rate=bad)
        self.assertFalse(TaxCodingDecision.objects.exists())

    def test_rate_against_accountant_confirmed_errors(self):
        p = self.coded('900031', rate=14)
        with self.assertRaisesMessage(services.TaxRuleError, 'النسبة تخالف المعاملة المعتمدة من المحاسب'):
            coding_queue.decide(p.pk, self.accountant, decision='code', vat_rate=0)
        coding_queue.decide(p.pk, self.accountant, decision='code', vat_rate=14)
        self.assertFalse(TaxAuditEvent.objects.filter(action='item_mapping_changed', entity_id='900031').exists())

    def test_decide_twice_errors(self):
        coding_queue.decide(self.p.pk, self.accountant, decision='keep_out')
        with self.assertRaisesMessage(services.TaxRuleError, 'للصنف قرار سابق — أعد فتحه أولاً'):
            coding_queue.decide(self.p.pk, self.accountant2, decision='code', vat_rate=14)

    def test_keep_out_leaves_profile(self):
        before = TaxItemProfile.objects.filter(pk=self.p.pk).values().get()
        d = coding_queue.decide(self.p.pk, self.accountant, decision='keep_out', note='later')
        after = TaxItemProfile.objects.filter(pk=self.p.pk).values().get()
        self.assertEqual(before, after)
        self.assertEqual((d.decision, d.vat_rate, d.note), ('keep_out', None, 'later'))
        self.assertFalse(TaxAuditEvent.objects.filter(action='item_mapping_changed').exists())

    def test_premark_and_flag_snapshot(self):
        bought('900030', 'S20', 'OFFICIAL_DISTRIBUTOR')
        d = coding_queue.decide(self.p.pk, self.accountant, decision='keep_out')
        self.assertEqual((d.premark, d.premark_reason, d.vat_flagged), ('code', 'official', False))

    def test_unknown_decision(self):
        with self.assertRaises(services.TaxRuleError):
            coding_queue.decide(self.p.pk, self.accountant, decision='maybe')

    def test_reopen_needs_reason_then_decide_again(self):
        coding_queue.decide(self.p.pk, self.accountant, decision='keep_out')
        with self.assertRaises(services.TaxRuleError):
            coding_queue.reopen(self.p.pk, self.admin, '  ')
        d = coding_queue.reopen(self.p.pk, self.admin, 'wrong call')
        self.assertEqual((d.decision, d.decided_by, d.reopened_by, d.reopen_reason),
                         ('', None, self.admin, 'wrong call'))
        self.assertIsNotNone(d.reopened_at)
        self.assertTrue(TaxAuditEvent.objects.filter(action='coding_decision_reopened', entity_id='900030',
                                                     reason='wrong call').exists())
        d2 = coding_queue.decide(self.p.pk, self.accountant, decision='code', vat_rate=14)
        self.assertEqual(d2.pk, d.pk)
        self.assertEqual(TaxCodingDecision.objects.count(), 1)

    def test_reopen_undecided_errors(self):
        with self.assertRaises(services.TaxRuleError):
            coding_queue.reopen(self.p.pk, self.admin, 'why')
