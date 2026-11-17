"""ETA production coding, batch S4 task 2: production code requests prepared from the coding queue's decisions,
ETA's approval making a decided item white, and the «جرّب GS1» offer after an EGS rejection. No HTTP."""
from datetime import date

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Item, ItemBarcode
from apps.tax_invoicing import coding, coding_queue
from apps.tax_invoicing.models import (EtaCodeUsage, TaxAuditEvent, TaxCodeRequest, TaxCodingDecision, TaxGpcBrick,
                                       TaxItemProfile)
from apps.tests.test_tax_coding_queue import BRICK, QUEUE, bought, sold
from apps.tests.test_tax_invoicing import Fixture

GTIN = '6223000000007'


class ProductionRequestTests(Fixture, TestCase):

    def setUp(self):
        self.build('pr')
        # a flushed kept DB has no seed rows: the pharmacist's explicit "no" keeps the matrix enforced
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.update_or_create(role='pharmacist', module='tax_invoicing', action='view',
                                                  defaults={'is_allowed': False})
        self.api = APIClient()
        self.api.force_authenticate(self.accountant)
        self.n = 0

    def profile(self, decide=True, barcode=''):
        self.n += 1
        code = f'94{self.n:04d}'
        item = Item.objects.create(softech_id=code, name=f'ITEM {code}', medicine_type_name='Cosmetics',
                                   sale_tax_pct=14, barcode=barcode)
        bought(code, f'SP{self.n}', 'MANUFACTURER')
        sold(code, 100)
        p = TaxItemProfile.objects.create(softech_itemcode=code, item=item, item_name=item.name, item_name_ar='صنف')
        if decide:
            coding_queue.decide(p.pk, self.accountant, decision='code', vat_rate=14, brick=BRICK,
                                names={'code_name': 'Cream', 'code_name_ar': 'كريم', 'description': 'Skin cream',
                                       'description_ar': 'كريم للبشرة'})
            p.refresh_from_db()
        return p

    def prepare(self, *profiles):
        return coding.prepare_from_decisions([p.softech_itemcode for p in profiles], self.accountant)

    def rejected(self, p):
        TaxCodeRequest.objects.filter(pk=self.prepare(p)['created'][0]).update(status=TaxCodeRequest.REJECTED)
        TaxItemProfile.objects.filter(pk=p.pk).update(coding_status=TaxItemProfile.CODE_REJECTED)

    def row(self, p):
        return [r for r in coding_queue.rows() if r['id'] == p.pk][0]

    # ── prepare ──────────────────────────────────────────────────────────────────────────────────────
    def test_prepared_from_the_decision(self):
        p = self.profile()
        out = self.prepare(p)
        self.assertEqual(out['skipped'], [])
        r = TaxCodeRequest.objects.get(pk=out['created'][0])
        self.assertEqual((r.environment, r.purpose, r.status, r.parent_code), ('production', 'new', 'prepared', BRICK))
        self.assertEqual((r.code_name, r.code_name_ar, r.description, r.description_ar),
                         ('Cream', 'كريم', 'Skin cream', 'كريم للبشرة'))
        self.assertEqual(r.item_code, f'EG-100200300-{p.softech_itemcode}')
        self.assertEqual(r.active_from, date(timezone.localdate().year, 1, 1))
        self.assertEqual(r.request_reason, 'صنف صيدلي يُباع للعملاء')
        ev = TaxAuditEvent.objects.get(action='code_request_prepared', entity_id=str(r.pk))
        self.assertEqual((ev.after['brick_from'], ev.after['environment']), ('decision', 'production'))
        p.refresh_from_db()
        self.assertEqual(p.coding_status, TaxItemProfile.CODE_MISSING)     # preparing changes nothing on the item

    def test_skip_reasons(self):
        no_decision = self.profile(decide=False)
        keep_out = self.profile(decide=False)
        coding_queue.decide(keep_out.pk, self.accountant, decision='keep_out')
        no_brick = self.profile()
        TaxCodingDecision.objects.filter(profile=no_brick).update(brick='')
        unconfirmed = self.profile()
        TaxItemProfile.objects.filter(pk=unconfirmed.pk).update(treatment_confirmed_at=None)
        approved = self.profile()
        TaxItemProfile.objects.filter(pk=approved.pk).update(coding_status=TaxItemProfile.CODE_APPROVED)
        opened = self.profile()
        self.prepare(opened)
        out = coding.prepare_from_decisions(
            [p.softech_itemcode for p in (no_decision, keep_out, no_brick, unconfirmed, approved, opened)] + ['999999'],
            self.accountant)
        self.assertEqual(out['created'], [])
        self.assertEqual({s['itemcode']: s['why'] for s in out['skipped']}, {
            no_decision.softech_itemcode: 'لا قرار تكويد', keep_out.softech_itemcode: 'لا قرار تكويد',
            no_brick.softech_itemcode: 'تحتاج فئة GPC', unconfirmed.softech_itemcode: 'المعاملة الضريبية غير معتمدة',
            approved.softech_itemcode: 'الصنف مُعتمد بالفعل',
            opened.softech_itemcode: 'يوجد طلب مفتوح في المنظومة الفعلية', '999999': 'صنف غير معروف'})
        self.assertEqual(TaxCodeRequest.objects.count(), 1)

    def test_brick_not_in_gpc_list_skipped(self):
        p = self.profile()
        TaxGpcBrick.objects.create(code='10000001', name_ar='فئة')
        self.assertEqual(self.prepare(p)['skipped'], [{'itemcode': p.softech_itemcode, 'why': 'تحتاج فئة GPC'}])

    def test_approved_request_or_eta_usage_skipped_preprod_request_not(self):
        a, b, c = self.profile(), self.profile(), self.profile()
        self.prepare(a)
        TaxCodeRequest.objects.filter(profile=a).update(status=TaxCodeRequest.APPROVED)
        EtaCodeUsage.objects.create(system='production', code_type='EGS', item_code='EG-1-x',
                                    itemcode=b.softech_itemcode, status='Approved')
        coding.prepare([c.pk], self.accountant, parent_code=BRICK, system='preprod')     # a test-system request
        out = self.prepare(a, b, c)
        self.assertEqual([s['why'] for s in out['skipped']], ['الصنف مُعتمد بالفعل', 'الصنف مُعتمد بالفعل'])
        self.assertEqual(TaxCodeRequest.objects.get(pk=out['created'][0]).profile_id, c.pk)

    def test_rejected_can_be_prepared_again(self):
        p = self.profile()
        self.rejected(p)
        self.assertEqual(len(self.prepare(p)['created']), 1)

    def test_api_permissions_and_shape(self):
        p = self.profile()
        url = QUEUE + 'prepare/'
        ph = APIClient()
        ph.force_authenticate(self.pharmacist)
        self.assertEqual(ph.post(url, {'itemcodes': [p.softech_itemcode]}, format='json').status_code, 403)
        self.assertEqual(self.api.post(url, {'itemcodes': 'x'}, format='json').status_code, 400)
        too_many = {'itemcodes': [str(n) for n in range(201)]}
        self.assertEqual(self.api.post(url, too_many, format='json').status_code, 400)
        r = self.api.post(url, {'itemcodes': [p.softech_itemcode, '999999']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data['created']), 1)
        self.assertEqual(r.data['skipped'], [{'itemcode': '999999', 'why': 'صنف غير معروف'}])
        self.assertEqual(ph.post(QUEUE + 'gs1/', {'itemcode': p.softech_itemcode}, format='json').status_code, 403)

    # ── the queue row ────────────────────────────────────────────────────────────────────────────────
    def test_queue_row_carries_latest_request_and_readiness(self):
        p, undecided = self.profile(), self.profile(decide=False)
        row = self.row(p)
        self.assertEqual((row['request'], row['request_ready'], row['request_blocker']), (None, True, ''))
        self.assertEqual((self.row(undecided)['request_ready'], self.row(undecided)['request_blocker']),
                         (False, 'لا قرار تكويد'))
        first = self.prepare(p)['created'][0]
        self.assertEqual(self.row(p)['request_blocker'], 'يوجد طلب مفتوح في المنظومة الفعلية')
        TaxCodeRequest.objects.filter(pk=first).update(status=TaxCodeRequest.FAILED, error='مرفوض', eta_status='x')
        row = self.row(p)
        self.assertEqual(row['request'], {'id': first, 'status': 'failed', 'status_label': 'لم يُقبل الطلب',
                                          'eta_status': 'x', 'error': 'مرفوض', 'purpose': 'new'})
        self.assertEqual(row['gs1_offer'], {'available': False, 'gtin': ''})
        self.assertTrue(row['request_ready'])

    # ── ETA approval → white ────────────────────────────────────────────────────────────────────────
    def _answer(self, row, status):
        TaxCodeRequest.objects.filter(pk=row.pk).update(status=TaxCodeRequest.SUBMITTED)
        with transaction.atomic():
            coding._apply_eta_answer(TaxCodeRequest.objects.select_related('profile').get(pk=row.pk),
                                     {'status': status, 'activeFrom': '2026-01-01T00:00:00Z'}, self.admin)

    def test_approval_of_a_decided_item_makes_it_white(self):
        p = self.profile()
        TaxItemProfile.objects.filter(pk=p.pk).update(disposition=TaxItemProfile.DISP_REVIEW)
        self._answer(TaxCodeRequest.objects.get(pk=self.prepare(p)['created'][0]), 'Approved')
        p.refresh_from_db()
        self.assertEqual((p.coding_status, p.list_status, p.disposition, p.coding_env),
                         ('approved', 'white', 'include', 'production'))
        ev = TaxAuditEvent.objects.filter(action='item_coding_from_eta', entity_id=str(p.pk)).latest('id')
        self.assertEqual((ev.before['list_status'], ev.before['disposition']), ('none', 'review'))
        self.assertEqual((ev.after['list_status'], ev.after['disposition'], ev.after['coding_env']),
                         ('white', 'include', 'production'))

    def test_approval_without_a_code_decision_leaves_the_list_alone(self):
        p = self.profile(decide=False)
        TaxItemProfile.objects.filter(pk=p.pk).update(disposition=TaxItemProfile.DISP_REVIEW)
        coding.prepare([p.pk], self.accountant, parent_code=BRICK, system='production')     # the old codes tab
        self._answer(TaxCodeRequest.objects.get(profile=p), 'Approved')
        p.refresh_from_db()
        self.assertEqual((p.coding_status, p.list_status, p.disposition), ('approved', 'none', 'review'))

    def test_rejection_or_preprod_approval_never_white(self):
        p, q = self.profile(), self.profile()
        self._answer(TaxCodeRequest.objects.get(pk=self.prepare(p)['created'][0]), 'Rejected')
        coding.prepare([q.pk], self.accountant, parent_code=BRICK, system='preprod')
        self._answer(TaxCodeRequest.objects.get(profile=q), 'Approved')
        p.refresh_from_db()
        q.refresh_from_db()
        self.assertEqual((p.coding_status, p.list_status), ('rejected', 'none'))
        self.assertEqual((q.coding_status, q.list_status), ('missing', 'none'))

    # ── «جرّب GS1» ───────────────────────────────────────────────────────────────────────────────────
    def test_gs1_offer_only_after_egs_rejection_with_a_gtin(self):
        p = self.profile(barcode='6221234567890')     # wrong check digit: not a GTIN
        ItemBarcode.objects.create(item=p.item, barcode=GTIN)
        bad = self.profile(barcode='12345')
        url = QUEUE + 'gs1/'
        self.assertEqual(self.api.post(url, {'itemcode': p.softech_itemcode}, format='json').status_code, 400)
        self.rejected(p)
        self.rejected(bad)
        self.assertEqual(self.row(p)['gs1_offer'], {'available': True, 'gtin': GTIN})
        self.assertEqual(self.row(bad)['gs1_offer'], {'available': False, 'gtin': ''})
        self.assertEqual(self.api.post(url, {'itemcode': bad.softech_itemcode}, format='json').status_code, 400)
        self.assertEqual(self.api.post(url, {'itemcode': '999999'}, format='json').status_code, 404)
        self.assertFalse(TaxCodeRequest.objects.filter(purpose='gs1').exists())     # never automatic
        r = self.api.post(url, {'itemcode': p.softech_itemcode}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        gs1 = TaxCodeRequest.objects.get(pk=r.data['created'][0])
        self.assertEqual((gs1.purpose, gs1.environment, gs1.item_code, gs1.status),
                         ('gs1', 'production', GTIN, 'prepared'))
        row = self.row(p)
        self.assertEqual((row['request']['purpose'], row['gs1_offer']['available']), ('gs1', False))
        self.assertEqual(self.api.post(url, {'itemcode': p.softech_itemcode}, format='json').status_code, 400)

    def test_rejected_gs1_request_offers_nothing_more(self):
        p = self.profile(barcode=GTIN)
        self.rejected(p)
        coding.prepare_gs1_offer(p.softech_itemcode, self.accountant)
        TaxCodeRequest.objects.filter(purpose='gs1').update(status=TaxCodeRequest.REJECTED)
        self.assertEqual(self.row(p)['gs1_offer'], {'available': False, 'gtin': ''})

    def test_constant_queries_with_requests(self):
        self.profile(barcode=GTIN)
        with CaptureQueriesContext(connection) as small:
            coding_queue.rows()
        for _ in range(6):
            self.rejected(self.profile(barcode=GTIN))
        with CaptureQueriesContext(connection) as big:
            self.assertEqual(sum(r['gs1_offer']['available'] for r in coding_queue.rows()), 6)
        self.assertEqual(len(small), len(big))
