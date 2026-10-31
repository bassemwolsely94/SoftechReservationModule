"""
apps/tests/test_shortage_transfers.py

P-33 (a) (docs/product-review/06_SPEC_P-33_supply_quick_fixes.md): «إنشاء مقترحات التحويل» on the
shortage screen — the same two linked PROPOSED IsrPush legs as the WhatsApp path (donor → 100 →
requesting branch), from the plan's donor excess. PG only; SOFTECH is written later by the usual
approve → push in the ISR tab. Never twice for the same need, whichever screen is used.
"""
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .test_branch_requests import _branch, _fake_items_plan, _items, _user

URL = '/api/shortage/lists/'


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class ShortageTransferTests(TestCase):

    def setUp(self):
        from apps.shortage.models import ShortageItem, ShortageList
        self.br = _branch('130')
        self.a, self.b = _items('ELIQUIS 2.5MG 20TAB (XX)  (2STRIPSX10)', 'CELLCEPT 500MG 50TAB (XX) (5 STRIPSX10)')
        self.sl = ShortageList.objects.create(branch=self.br, title='نواقص')
        ShortageItem.objects.create(shortage_list=self.sl, item=self.a, raw_name='eliquis', quantity_needed=5,
                                    is_confirmed=True)
        ShortageItem.objects.create(shortage_list=self.sl, item=self.b, raw_name='cellcept', quantity_needed=3,
                                    is_confirmed=False)                                   # not confirmed → never moved
        p = mock.patch('apps.purchasing.isr_writer.build_items_plan', side_effect=_fake_items_plan)
        p.start()
        self.addCleanup(p.stop)
        self.c = APIClient()
        self.c.force_authenticate(_user('18', group=19))

    def snap(self, pi):
        a, b = self.a.softech_id, self.b.softech_id
        return {'isr_numbers': [pi['isr']], 'branches': ['130', '150', '160'], 'branch_names': {}, 'down': [],
                'fallback': {}, 'run_id': None, 'taken_at': '2026-10-31T10:00:00', 'names': {}, 'eng': {},
                'stock': {'150': {a: 3.0, b: 9.0}, '160': {a: 1.0}, '100': {}}, 'isrs': [pi]}

    def post(self, url=None, client=None):
        from apps.purchasing import isr_fulfillment as F
        with mock.patch.object(F, 'collect_requests', side_effect=lambda isrs: self.snap(isrs[0])) as col:
            r = (client or self.c).post(url or f'{URL}{self.sl.pk}/transfers/', {'coverage': 1.5, 'basis': 'requested'}, format='json')
        return r, col

    def test_pseudo_isr_from_list(self):
        from apps.supply.branch_requests import pseudo_isr_from_list
        pi = pseudo_isr_from_list(self.sl)
        self.assertEqual((pi['isr'], pi['kind'], pi['branch']), (f'SL-{self.sl.pk}', 'shortage', '130'))
        self.assertEqual([(l['code'], l['qty']) for l in pi['lines']], [(self.a.softech_id, 5.0)])

    def test_two_linked_legs_per_donor_from_the_donor_excess(self):
        from apps.purchasing.models import IsrPush
        r, col = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertEqual([l['code'] for l in col.call_args[0][0][0]['lines']], [self.a.softech_id])
        # 5 asked, but the donors only hold 3 + 1 — never more than the plan's donor quantities
        self.assertEqual([(c['donor'], c['qty']) for c in r.data['created']], [('150', 3.0), ('160', 1.0)])
        for c in r.data['created']:
            leg1, leg2 = IsrPush.objects.get(pk=c['leg1_id']), IsrPush.objects.get(pk=c['leg2_id'])
            self.assertEqual((leg1.kind, leg1.branchcode, leg1.dest_branchcode), ('branch_to_hq', c['donor'], '100'))
            self.assertEqual((leg2.kind, leg2.branchcode, leg2.dest_branchcode), ('hq_to_branch', '100', '130'))
            for p in (leg1, leg2):
                self.assertEqual((p.status, p.origin_shortage_list_id, p.origin_request_id),
                                 ('proposed', self.sl.pk, None))
                self.assertIn(f'SL-{self.sl.pk}', p.notes)
        self.assertEqual(len(r.data['plan']['transfers']), 2)

    def test_second_click_creates_nothing(self):
        from apps.purchasing.models import IsrPush
        self.post()
        r, _ = self.post()
        self.assertEqual((r.status_code, r.data['created']), (200, []))
        self.assertEqual({s['reason'] for s in r.data['skipped']}, {'exists'})
        self.assertEqual(IsrPush.objects.count(), 4)

    def test_db_blocks_a_parallel_duplicate_leg(self):
        from django.db import IntegrityError, transaction
        from apps.purchasing.models import IsrPush
        kw = dict(branchcode='150', dest_branchcode='100', kind='branch_to_hq', origin_shortage_list=self.sl,
                  origin_donor='150')
        IsrPush.objects.create(**kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IsrPush.objects.create(**kw)

    def test_does_not_supersede_the_daily_route_draft(self):
        from apps.purchasing.models import IsrPush
        general = IsrPush.objects.create(branchcode='150', dest_branchcode='100', kind='branch_to_hq',
                                         status='proposed', line_count=1)
        r, _ = self.post()
        self.assertEqual(r.status_code, 201)
        general.refresh_from_db()
        self.assertEqual(general.status, 'proposed')

    def test_a_list_made_from_a_whatsapp_request_moves_once(self):
        from apps.purchasing.models import IsrPush
        from apps.supply.models import BranchRequest, BranchRequestLine as L
        req = BranchRequest.objects.create(branch=self.br, shortage_list=self.sl)
        L.objects.create(request=req, raw_text='Eliquis 2.5', item=self.a, qty=5, confirmed=True, score=0.95)
        r, _ = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(set(IsrPush.objects.values_list('origin_request_id', 'origin_shortage_list_id')),
                         {(req.pk, None)})
        r, _ = self.post(url=f'/api/purchasing/isr/branch-requests/{req.pk}/transfers/')
        self.assertEqual(r.data['created'], [])
        self.assertEqual(IsrPush.objects.count(), 4)

    def test_plan_is_read_only(self):
        from apps.purchasing import isr_fulfillment as F
        from apps.purchasing.models import IsrPush
        with mock.patch.object(F, 'collect_requests', side_effect=lambda isrs: self.snap(isrs[0])):
            r = self.c.get(f'{URL}{self.sl.pk}/transfer-plan/', {'coverage': 1.5, 'basis': 'requested'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['isrs'][0]['isr'], f'SL-{self.sl.pk}')
        self.assertTrue(r.data['can_transfer'])
        self.assertFalse(IsrPush.objects.exists())

    def test_nothing_confirmed_is_refused(self):
        self.sl.items.update(is_confirmed=False)
        r, _ = self.post()
        self.assertEqual(r.status_code, 400)

    def test_without_purchasing_write_rights(self):
        c = APIClient()
        c.force_authenticate(_user('1399', group=14))
        r, _ = self.post(client=c)
        self.assertEqual(r.status_code, 403)
