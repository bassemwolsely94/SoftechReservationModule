"""ETA production item coding queue (batch S1): the shared VAT-treatment confirmation and the queue built on it."""
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Item
from apps.procurement.models import PurchaseLine, SupplierSegmentation
from apps.tax_invoicing import coding_queue, coding_rule, services
from apps.tax_invoicing.models import (EtaCodeUsage, EtaReconUncodedItem, TaxAuditEvent, TaxCodingDecision,
                                       TaxItemProfile)
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

    def test_no_catalog_row_flagged_unless_confirmed(self):
        p = TaxItemProfile.objects.create(softech_itemcode='900027', vat_rate=14)
        self.assertEqual(coding_rule.vat_prefill(None, p), (Decimal('0'), True, 'no_catalog'))
        self.assertEqual(coding_rule.vat_prefill(None, None), (Decimal('0'), True, 'no_catalog'))
        self.assertEqual(coding_rule.vat_prefill(None, self.coded('900028', rate=14)), (Decimal('14'), False, 'confirmed'))


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

    def test_arabic_names_default_to_profile_arabic_name(self):
        TaxItemProfile.objects.filter(pk=self.p.pk).update(item_name_ar='كريم')
        d = coding_queue.decide(self.p.pk, self.accountant, decision='keep_out')
        self.assertEqual((d.code_name, d.code_name_ar, d.description, d.description_ar),
                         ('GLOW CREAM', 'كريم', 'GLOW CREAM', 'كريم'))

    def test_code_needs_rate_0_or_14(self):
        for bad in (None, 5, 'x'):
            with self.assertRaises(services.TaxRuleError):
                coding_queue.decide(self.p.pk, self.accountant, decision='code', vat_rate=bad)
        self.assertFalse(TaxCodingDecision.objects.exists())

    def test_rate_against_accountant_confirmed_errors(self):
        p = self.coded('900031', rate=14, coding_env='preprod')
        with self.assertRaisesMessage(services.TaxRuleError,
                                      'النسبة تخالف المعاملة الضريبية المعتمدة للصنف — عدّلها من شاشة الأصناف أولاً'):
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


QUEUE = '/api/tax-invoicing/codes/queue/'


def sold(code, value, docs=1, day=None, system='production', branch='101'):
    day = day or timezone.localdate() - timedelta(days=1)
    return EtaReconUncodedItem.objects.create(system=system, softech_branchcode=branch, day=day, itemcode=code,
                                              docs=docs, qty=1, value=value)


class QueueApiTests(Fixture, TestCase):
    def setUp(self):
        self.build('qa')
        # The accountant's rows never seed a module (enforced role, R17) and a flushed kept DB has no seed rows:
        # the pharmacist's explicit "no" keeps tax_invoicing seeded, so the matrix is enforced, not fail-open.
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.update_or_create(role='pharmacist', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': False})
        self.api = self.client_for(self.accountant)
        # A: biggest seller, bought official; B: cosmetic at 0 % (flagged); C: no catalog row, sold 200 days ago
        make_item('910001', 'Medicine', 0, name='ALPHA')
        make_item('910002', 'Cosmetics', 0, name='BETA')
        bought('910001', 'S30', 'OFFICIAL_DISTRIBUTOR')
        self.pa = TaxItemProfile.objects.create(softech_itemcode='910001', item_name='ALPHA')
        self.pb = TaxItemProfile.objects.create(softech_itemcode='910002', item_name='BETA')
        self.pc = TaxItemProfile.objects.create(softech_itemcode='910003', item_name='GAMMA')
        sold('910001', 500, docs=3)
        sold('910001', 100, docs=1, branch='102')
        sold('910002', 200, docs=2)
        sold('910003', 50, day=timezone.localdate() - timedelta(days=200))

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def codes(self, body):
        return [r['itemcode'] for r in body['rows']]

    def test_ordering_biggest_first_and_totals(self):
        r = self.api.get(QUEUE)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.codes(r.data), ['910001', '910002', '910003'])
        self.assertEqual((r.data['count'], r.data['page'], r.data['pages'], r.data['total_value']), (3, 1, 1, '850.00'))
        a = r.data['rows'][0]
        self.assertEqual((a['value'], a['docs'], a['premark'], a['premark_reason']), ('600.00', 4, 'code', 'official'))
        self.assertEqual(a['sources'], {'OFFICIAL_DISTRIBUTOR': 5})
        self.assertIsNone(a['decision'])
        self.assertEqual(self.codes(self.api.get(QUEUE, {'ordering': 'itemcode'}).data), ['910001', '910002', '910003'])
        self.assertEqual(self.codes(self.api.get(QUEUE, {'ordering': '-itemcode'}).data), ['910003', '910002', '910001'])
        self.assertEqual(self.api.get(QUEUE, {'ordering': 'name'}).status_code, 400)

    def test_recent_filter(self):
        r = self.api.get(QUEUE, {'recent': 30})
        self.assertEqual(self.codes(r.data), ['910001', '910002'])
        self.assertEqual(r.data['total_value'], '800.00')
        self.assertEqual(self.api.get(QUEUE, {'recent': 'x'}).status_code, 400)

    def test_q_and_premark_filters(self):
        self.assertEqual(self.codes(self.api.get(QUEUE, {'q': 'bet'}).data), ['910002'])
        self.assertEqual(self.codes(self.api.get(QUEUE, {'premark': 'code'}).data), ['910001'])

    def test_decided_filter(self):
        coding_queue.decide(self.pb.pk, self.accountant, decision='keep_out')
        self.assertEqual(self.codes(self.api.get(QUEUE, {'decided': 'yes'}).data), ['910002'])
        self.assertEqual(self.codes(self.api.get(QUEUE, {'decided': 'no'}).data), ['910001', '910003'])
        row = self.api.get(QUEUE, {'decided': 'yes'}).data['rows'][0]
        self.assertEqual(row['decision'], 'keep_out')
        self.assertTrue(row['decided_by'])
        self.assertIsNotNone(row['decided_at'])

    def test_pharmacist_403_accountant_200(self):
        self.assertEqual(self.client_for(self.pharmacist).get(QUEUE).status_code, 403)
        self.assertEqual(self.api.get(QUEUE).status_code, 200)

    def test_accountant_decides_viewer_only_403(self):
        from apps.tests.factories import make_user
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        RoleModuleAccess.objects.update_or_create(role='viewer', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': True})
        RoleModuleAccess.objects.filter(role='viewer', module='tax_invoicing').exclude(action='view').delete()
        module_access.clear_cache()
        viewer, _, _ = make_user('viewer_qa', role='viewer', branch=self.branch)
        vc = self.client_for(viewer)
        self.assertEqual(vc.get(QUEUE).status_code, 200)
        r = vc.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'keep_out'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = vc.post(QUEUE + 'reopen/', {'itemcode': '910001', 'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TaxCodingDecision.objects.exists())
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'code', 'vat_rate': 0},
                          format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data['decided'], r.data['skipped']), (['910001'], []))
        self.assertEqual(TaxCodingDecision.objects.get(profile=self.pa).decision, 'code')

    def test_bulk_code_uses_prefill_and_skips_flagged(self):
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001', '910002', '910003', '999999'],
                                              'decision': 'code'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['decided'], ['910001'])
        self.assertEqual({s['itemcode']: s['why'] for s in r.data['skipped']},
                         {'910002': 'النسبة تحتاج تأكيداً', '910003': 'النسبة تحتاج تأكيداً',
                          '999999': 'صنف غير معروف'})
        self.assertEqual(int(TaxCodingDecision.objects.get(profile=self.pa).vat_rate), 0)
        self.assertFalse(TaxCodingDecision.objects.filter(profile__in=[self.pb, self.pc]).exists())
        self.pc.refresh_from_db()
        self.assertIsNone(self.pc.treatment_confirmed_at)   # no catalog row: nobody chose 0 %, so nothing confirmed

    def test_bulk_unknown_decision_400(self):
        for body in ({'itemcodes': ['910001', '910002'], 'decision': 'maybe'}, {'itemcodes': ['910001', '910002']}):
            self.assertEqual(self.api.post(QUEUE + 'decide/', body, format='json').status_code, 400)
        self.assertFalse(TaxCodingDecision.objects.exists())

    def test_non_string_names_are_coerced(self):
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'code', 'vat_rate': 0,
                                              'names': {'code_name': 5, 'code_name_ar': None}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = TaxCodingDecision.objects.get(profile=self.pa)
        self.assertEqual((d.code_name, d.code_name_ar), ('5', 'ALPHA'))

    def test_already_decided_bulk_skipped_single_409(self):
        coding_queue.decide(self.pa.pk, self.accountant, decision='keep_out')
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001', '910003'], 'decision': 'keep_out'},
                          format='json')
        self.assertEqual(r.data['decided'], ['910003'])
        self.assertEqual(r.data['skipped'], [{'itemcode': '910001', 'why': 'للصنف قرار سابق — أعد فتحه أولاً'}])
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'keep_out'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['detail'], 'للصنف قرار سابق — أعد فتحه أولاً')

    def test_sheet_coded_or_on_eta_item_cannot_be_decided(self):
        TaxItemProfile.objects.filter(pk=self.pa.pk).update(coding_status='approved', coding_env='production')
        before = TaxItemProfile.objects.get(pk=self.pa.pk).tax_treatment
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'code', 'vat_rate': 14},
                          format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.data['detail'], 'الصنف مُكوَّد بالفعل — ليس في طابور الترميز')
        self.assertFalse(TaxCodingDecision.objects.filter(profile=self.pa).exists())
        self.assertEqual(TaxItemProfile.objects.get(pk=self.pa.pk).tax_treatment, before)
        # active on ETA production, not coded on the sheet
        EtaCodeUsage.objects.create(system='production', code_type='EGS', item_code='EG-1-910003', status='Approved',
                                    itemcode='910003')
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910003'], 'decision': 'keep_out'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # bulk skips it with that reason, others still go through
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001', '910003', '910002'], 'decision': 'keep_out'},
                          format='json')
        self.assertEqual(r.data['decided'], ['910002'])
        self.assertEqual({s['itemcode']: s['why'] for s in r.data['skipped']},
                         {'910001': 'الصنف مُكوَّد بالفعل — ليس في طابور الترميز',
                          '910003': 'الصنف مُكوَّد بالفعل — ليس في طابور الترميز'})

    def test_preprod_only_coded_item_can_be_decided(self):
        TaxItemProfile.objects.filter(pk=self.pa.pk).update(coding_status='approved', coding_env='preprod')
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'keep_out'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['decided'], ['910001'])

    def test_single_bad_rate_400_and_too_many(self):
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': ['910001'], 'decision': 'code', 'vat_rate': 5},
                          format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(QUEUE + 'decide/', {'itemcodes': [str(i) for i in range(201)], 'decision': 'keep_out'},
                          format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api.post(QUEUE + 'decide/', {'itemcodes': [], 'decision': 'keep_out'},
                                       format='json').status_code, 400)

    def test_reopen(self):
        coding_queue.decide(self.pa.pk, self.accountant, decision='keep_out')
        r = self.api.post(QUEUE + 'reopen/', {'itemcode': '910001', 'reason': ''}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(QUEUE + 'reopen/', {'itemcode': '910001', 'reason': 'wrong'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(TaxCodingDecision.objects.get(profile=self.pa).decision, '')
        r = self.api.post(QUEUE + 'reopen/', {'itemcode': '999999', 'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_item_coded_on_eta_not_listed_and_last_status_shown(self):
        EtaCodeUsage.objects.create(system='production', code_type='EGS', item_code='EG-1-910001', status='Approved',
                                    itemcode='910001')
        EtaCodeUsage.objects.create(system='production', code_type='EGS', item_code='EG-1-910002', status='Rejected',
                                    itemcode='910002')
        EtaCodeUsage.objects.create(system='preprod', code_type='EGS', item_code='EG-1-910003', status='Approved',
                                    itemcode='910003')
        r = self.api.get(QUEUE)
        self.assertEqual(self.codes(r.data), ['910002', '910003'])
        self.assertEqual([x['eta_last_status'] for x in r.data['rows']], ['Rejected', ''])

    def test_coded_profiles_excluded_unless_test_system_only(self):
        TaxItemProfile.objects.filter(pk=self.pa.pk).update(coding_status='approved', coding_env='')
        TaxItemProfile.objects.filter(pk=self.pb.pk).update(coding_status='pending', coding_env='preprod')
        sold('910004', 999, system='preprod')
        TaxItemProfile.objects.create(softech_itemcode='910004')
        self.assertEqual(self.codes(self.api.get(QUEUE).data), ['910002', '910003'])

    def test_no_catalog_row_listed_with_no_purchase(self):
        row = [x for x in self.api.get(QUEUE).data['rows'] if x['itemcode'] == '910003'][0]
        self.assertEqual((row['name'], row['premark'], row['premark_reason']), ('GAMMA', '', 'no_purchase'))
        self.assertEqual(row['sources'], {})

    def test_flags_catalog_items_without_profile(self):
        self.assertFalse(self.api.get(QUEUE).data['catalog_without_profile'])
        make_item('910099')
        self.assertTrue(self.api.get(QUEUE).data['catalog_without_profile'])

    def test_constant_queries(self):
        with CaptureQueriesContext(connection) as small:
            coding_queue.rows()
        for n in range(5, 25):
            code = f'92{n:04d}'
            make_item(code)
            TaxItemProfile.objects.create(softech_itemcode=code)
            sold(code, n)
            bought(code, f'S{n}', 'MANUFACTURER')
        coding_queue.decide(TaxItemProfile.objects.get(softech_itemcode='920005').pk, self.accountant,
                            decision='keep_out')
        with CaptureQueriesContext(connection) as big:
            self.assertEqual(len(coding_queue.rows()), 23)
        self.assertEqual(len(small), len(big))
