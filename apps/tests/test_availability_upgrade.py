"""
Supplier availability lists — owner batch 2026-10-05:
branch scope (one / several branches, default all), trust score + approvals, barcode and
supplier-code matching (VendorItemMapping, conflicts never overwritten), finalize/unlock with
a full audit trail (every write refused while locked), data-freshness endpoint.
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import availability as av
from apps.supply.models import AvailabilityBatch, AvailabilityLine


def _run():
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.create(status='success', calc_date=date.today())


def _metric(run, item, branch, *, stock=0, safety=0, gap=0):
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.create(run=run, item=item, branch=branch, calc_date=date.today(),
                                            current_stock=stock, safety_stock=safety, gap=gap)


class BranchScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        cls.item = Item.objects.create(softech_id='620001', name='SCOPEDRUG 50MG 20TAB', is_active=True)
        cls.a = Branch.objects.create(softech_branch_id='170', name='Abbasia')
        cls.r = Branch.objects.create(softech_branch_id='160', name='Ramsis')
        cls.g = Branch.objects.create(softech_branch_id='140', name='Giza')
        cls.h = Branch.objects.create(softech_branch_id='100', name='HQ')
        run = _run()
        _metric(run, cls.item, cls.a, stock=0, safety=2, gap=4)
        _metric(run, cls.item, cls.r, stock=1, safety=2, gap=6)
        _metric(run, cls.item, cls.g, stock=0, safety=2, gap=10)
        _metric(run, cls.item, cls.h, stock=5, safety=2, gap=-3)       # over target, surplus 3
        from apps.purchasing.models import ItemDemandAggregated
        ItemDemandAggregated.objects.create(run=run, item=cls.item, calc_date=date.today(),
                                            total_current_stock=6, total_gap=17)

    def _batch(self, scope=None):
        b = AvailabilityBatch.objects.create(source='whatsapp', branch_scope=scope or [])
        AvailabilityLine.objects.create(batch=b, raw_text='scopedrug 50 10', item=self.item,
                                        match_score=1.0, is_confirmed=True, supplier_qty=50)
        return b

    def test_default_is_all_branches_total(self):
        row = av.analyze_batch(self._batch())['lines'][0]
        self.assertEqual(row['required'], 17.0)
        self.assertEqual(row['branches'], [])

    def test_only_chosen_branches_count(self):
        an = av.analyze_batch(self._batch([self.a.id, self.r.id]))
        row = an['lines'][0]
        self.assertEqual(an['scope']['branch_ids'], [self.a.id, self.r.id])
        self.assertEqual(row['required'], 10.0)                         # 4 + 6, Giza not included
        self.assertEqual({b['branch_id']: b['required'] for b in row['branches']},
                         {self.a.id: 4.0, self.r.id: 6.0})
        self.assertEqual(row['internal_cover'], 3.0)                    # HQ surplus 5 − safety 2
        self.assertEqual(row['residual_gap'], 7.0)
        self.assertEqual(row['suggested_buy'], 7.0)

    def test_preview_override_and_single_branch(self):
        b = self._batch()
        row = av.analyze_batch(b, branch_ids=[self.g.id])['lines'][0]
        self.assertEqual(row['required'], 10.0)
        self.assertEqual(av.analyze_batch(b)['lines'][0]['required'], 17.0)   # stored scope untouched

    def test_branch_without_target_has_no_engine_need(self):
        from apps.branches.models import Branch
        other = Branch.objects.create(softech_branch_id='200', name='Sheraton')
        row = av.analyze_batch(self._batch([other.id]))['lines'][0]
        self.assertEqual(row['required'], 0.0)
        self.assertEqual(row['state'], 'not_needed')


class TrustAndMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item, ItemBarcode
        from apps.invoices.models import VendorProfile
        cls.item = Item.objects.create(softech_id='620101', name='ZINNAT 250MG 10TAB', is_active=True,
                                       barcode='6221234567890', supplier_code='565')
        cls.other = Item.objects.create(softech_id='620102', name='ZINNAT 500MG 10TAB', is_active=True)
        ItemBarcode.objects.create(item=cls.other, barcode='6229999999991')
        cls.vendor = VendorProfile.objects.create(name='PHARMA OVER SEAS', softech_personcode='565')

    def _batch(self):
        return AvailabilityBatch.objects.create(source='whatsapp', supplier=self.vendor)

    def test_barcode_in_line_matches_exactly_and_is_not_a_quantity(self):
        line = av.build_line(self._batch(), 'زينات ٢٥٠ 6221234567890 متاح 12', vendor_code='565')
        self.assertEqual(line.item_id, self.item.id)
        self.assertEqual(line.match_reason['via'], 'barcode')
        self.assertEqual(float(line.supplier_qty), 12.0)
        line2 = av.build_line(self._batch(), 'something 6229999999991')       # an extra barcode
        self.assertEqual(line2.item_id, self.other.id)
        line3 = av.build_line(self._batch(), 'Zinnat 250 01001234567')       # a phone number → no barcode
        self.assertNotEqual(line3.match_reason.get('via'), 'barcode')

    def test_supplier_code_learned_on_confirm_and_reused(self):
        b = self._batch()
        line = AvailabilityLine.objects.create(batch=b, raw_text='Zinat 250 code ZN25',
                                               supplier_item_code='ZN25',
                                               match_reason={'name_part': 'Zinat 250'})
        av.confirm_line(line, self.item, vendor_code='565')
        from apps.invoices.models import VendorItemMapping
        self.assertTrue(VendorItemMapping.objects.filter(vendor=self.vendor, vendor_item_code='ZN25',
                                                         item=self.item).exists())
        nxt = av.build_line(self._batch(), 'totally different text code ZN25 qty 5', vendor_code='565')
        self.assertEqual((nxt.item_id, nxt.match_reason['via']), (self.item.id, 'vendor_code'))

    def test_conflicting_supplier_code_is_flagged_not_overwritten(self):
        from apps.invoices.models import VendorItemMapping
        VendorItemMapping.objects.create(vendor=self.vendor, raw_name_normalized='zinat 250',
                                         vendor_item_code='ZN25', item=self.item)
        b = self._batch()
        line = AvailabilityLine.objects.create(batch=b, raw_text='Zinat 500 code ZN25',
                                               supplier_item_code='ZN25',
                                               match_reason={'name_part': 'Zinat 500'})
        av.confirm_line(line, self.other, vendor_code='565')
        line.refresh_from_db()
        self.assertEqual(line.match_reason['vendor_code_conflict']['item_id'], self.item.id)
        self.assertEqual(VendorItemMapping.objects.get(vendor_item_code='ZN25').item_id, self.item.id)
        row = av.analyze_rows(b, [line.pk])[0]
        self.assertIn('vendor_code_conflict', row['flags'])

    def test_trust_and_approvals(self):
        b = self._batch()
        ln = AvailabilityLine.objects.create(batch=b, raw_text='zinnat 250', item=self.item, match_score=0.8,
                                             match_reason={'name_part': 'zinnat 250',
                                                           'review_flags': ['strength_mismatch']})
        self.assertEqual(av.trust_score(ln), 50)                       # 80 − 30
        self.assertEqual(av.trust_score(ln, approvals=2), 56)          # + 3 × 2
        from apps.shortage import learning
        learning.learn_alias('zinnat 250', self.item, vendor_code='565')
        learning.learn_alias('zinnat 250', self.item, vendor_code='565')
        row = av.analyze_rows(b, [ln.pk])[0]
        self.assertEqual(row['approvals'], 2)
        self.assertTrue(row['main_supplier'])                          # item.supplier_code == 565
        ln.is_confirmed = True
        self.assertEqual(av.trust_score(ln), 100)


class LockAndAuditApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from .factories import make_user
        cls.item = Item.objects.create(softech_id='620201', name='OZEMPIC 1MG PEN', is_active=True)
        cls.user, _, _ = make_user('op_avail_lock', role='purchasing')

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.user)
        self.b = AvailabilityBatch.objects.create(source='whatsapp')
        self.line = AvailabilityLine.objects.create(batch=self.b, raw_text='ozempic 1mg 3', item=self.item,
                                                    match_score=0.9)
        self.url = f'/api/supply/availability/{self.b.id}/'

    def test_lock_blocks_every_write_and_unlock_needs_reason(self):
        r = self.c.post(self.url + 'lock/', {'note': 'final for order'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['is_locked'])
        for method, path, body in [
            ('patch', f'lines/{self.line.id}/', {'item': self.item.id, 'is_confirmed': True}),
            ('post', f'lines/{self.line.id}/items/', {'item_ids': [self.item.id]}),
            ('post', 'confirm-matches/', {}),
            ('post', 'add-line/', {'raw_text': 'brufen 400 5'}),
            ('delete', f'lines/{self.line.id}/delete/', None),
            ('post', 'scope/', {'branch_ids': []}),
        ]:
            resp = getattr(self.c, method)(self.url + path, body, format='json')
            self.assertEqual(resp.status_code, 423, (path, resp.content))
        self.assertTrue(AvailabilityLine.objects.filter(pk=self.line.pk, is_confirmed=False).exists())
        # analysis still works while locked
        self.assertEqual(self.c.get(self.url + 'analysis/').status_code, 200)
        self.assertEqual(self.c.post(self.url + 'unlock/', {}, format='json').status_code, 400)
        r = self.c.post(self.url + 'unlock/', {'reason': 'supplier sent a correction'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['is_locked'])
        ok = self.c.patch(self.url + f'lines/{self.line.id}/', {'item': self.item.id, 'is_confirmed': True},
                          format='json')
        self.assertEqual(ok.status_code, 200)

    def test_history_records_who_what_before_after(self):
        self.c.patch(self.url + f'lines/{self.line.id}/', {'item': self.item.id, 'is_confirmed': True},
                     format='json')
        self.c.post(self.url + 'lock/', {}, format='json')
        self.c.post(self.url + 'unlock/', {'reason': 'need to fix qty'}, format='json')
        h = self.c.get(self.url + 'history/').json()
        events = [x['event'] for x in h]
        self.assertEqual(events[:3], ['unlocked', 'locked', 'line_updated'])
        self.assertEqual(h[0]['note'], 'need to fix qty')
        self.assertEqual(h[2]['changes']['confirmed'], [False, True])
        self.assertTrue(all(x['user'] for x in h))

    def test_scope_endpoint_validates_and_audits(self):
        from apps.branches.models import Branch
        br = Branch.objects.create(softech_branch_id='170', name='Abbasia')
        self.assertEqual(self.c.post(self.url + 'scope/', {'branch_ids': [999999]}, format='json').status_code, 400)
        r = self.c.post(self.url + 'scope/', {'branch_ids': [br.id]}, format='json')
        self.assertEqual(r.json()['branch_ids'], [br.id])
        self.b.refresh_from_db()
        self.assertEqual(self.b.branch_scope, [br.id])
        h = self.c.get(self.url + 'history/').json()
        self.assertEqual(h[0]['changes']['branch_scope'], [[], [br.id]])

    def test_freshness_endpoint(self):
        r = self.c.get('/api/supply/freshness/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for k in ('rates', 'stock', 'sales', 'items'):
            self.assertIn('stale', d[k])
        self.assertIn('sync_stock', d['can'])
