"""C04 / P-28 — near-expiry action worklist (apps/batches/near_expiry.py). Pure rules + local mirrors; no SOFTECH."""
import datetime as dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.batches import near_expiry as NE
from apps.batches.stock_expiry import fefo_at_risk, fefo_at_risk_lots

T = dt.date(2026, 10, 7)


def day(n, base=T):
    return base + dt.timedelta(days=n)


class FefoPerLotTests(SimpleTestCase):

    def test_per_lot_sums_to_the_p26_total(self):
        batches = [(day(40), 30), (day(50), 30), (day(170), 12), (day(-3), 9), (day(400), 50)]
        lots = fefo_at_risk_lots([(e, q, i) for i, (e, q) in enumerate(batches)], 1.0, T, 180)
        self.assertEqual(round(sum(l['at_risk_qty'] for l in lots), 3), fefo_at_risk(batches, 1.0, T, 180))
        self.assertEqual([l['ref'] for l in lots], [0, 1, 2])            # expired and > horizon skipped
        self.assertEqual([round(l['at_risk_qty'], 3) for l in lots], [0.0, 10.0, 0.0])


class SuggestTests(SimpleTestCase):
    LOT = {'at_risk_qty': 20.0, 'days_left': 60}

    def test_return_first_takes_the_whole_at_risk_qty(self):
        self.assertEqual(NE.suggest(self.LOT, ret={'supplier_code': '565'}, move_qty=50),
                         ('return', {'return': 20.0}))

    def test_move_then_sell_first_and_split_sums(self):
        action, split = NE.suggest(self.LOT, move_qty=8)
        self.assertEqual((action, split), ('move', {'move': 8.0, 'sell_first': 12.0}))
        self.assertEqual(sum(split.values()), 20.0)

    def test_no_move_for_fridge_or_hold(self):
        self.assertEqual(NE.suggest(self.LOT, move_qty=50, can_move=False)[0], 'sell_first')

    def test_sell_first_never_for_blocked_items_or_too_late(self):
        self.assertEqual(NE.suggest(self.LOT, sellable=False), ('accept_loss', {'accept_loss': 20.0}))
        self.assertEqual(NE.suggest({'at_risk_qty': 5, 'days_left': 10}, sell_first_min_days=30)[0], 'accept_loss')


class ClassifyTests(SimpleTestCase):

    def run_(self, **kw):
        opts = dict(t0_qty=50, at_risk_qty=44, now_qty=0, expired=False, evidence={}, unit_cost=10)
        opts.update(kw)
        return NE.classify(**opts)

    def test_sold_saved_value_capped_at_at_risk(self):
        r = self.run_(evidence={'sold': 50})
        self.assertEqual((r['outcome'], r['qty'], r['saved_value'], r['lost_value']), ('sold', {'sold': 50.0}, 440.0, 0.0))

    def test_moved_and_written_off(self):
        self.assertEqual(self.run_(evidence={'moved': 48})['outcome'], 'moved')
        r = self.run_(evidence={'written_off': 50})
        self.assertEqual((r['outcome'], r['lost_value'], r['saved_value']), ('written_off', 500.0, 0.0))

    def test_expired_on_shelf(self):
        r = self.run_(now_qty=50, expired=True)
        self.assertEqual((r['outcome'], r['lost_value']), ('expired', 500.0))
        self.assertEqual(self.run_(now_qty=50)['outcome'], 'on_hand')

    def test_mixed_and_unexplained_never_saved(self):
        r = self.run_(evidence={'sold': 20, 'moved': 20})
        self.assertEqual(r['outcome'], 'mixed')
        self.assertEqual(r['qty'], {'moved': 20.0, 'sold': 20.0, 'unexplained': 10.0})
        self.assertEqual(r['saved_qty'], 40.0)
        r = self.run_(evidence={})
        self.assertEqual((r['outcome'], r['saved_value']), ('unexplained', 0.0))

    def test_ledger_more_than_drop_is_capped(self):
        r = self.run_(now_qty=30, evidence={'sold': 999})
        self.assertEqual(r['qty'], {'sold': 20.0, 'on_hand': 30.0})


class Base(TestCase):
    """Branch 130 holds 50 of X expiring in 60 days and sells 0.1/day → 44 at risk; 140 sells 1/day."""

    def setUp(self):
        from apps.batches.models import StockExpiryBalance
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.tests.factories import make_branch, make_hq
        self.today = timezone.localdate()
        self.hq = make_hq('100', self)
        self.b130, self.b140 = make_branch('فرع 130', '130'), make_branch('فرع 140', '140')
        self.item = Item.objects.create(softech_id='700001', name='DRUG', cost_price=Decimal('10'), is_active=True)
        self.fast = Item.objects.create(softech_id='700002', name='FAST', cost_price=Decimal('5'), is_active=True)
        self.exp = self.today + dt.timedelta(days=60)
        mk = StockExpiryBalance.objects.create
        mk(branch_code='130', store_code='130', item_code='700001', batch_no='L1', expiry_date=self.exp, qty=Decimal('50'))
        mk(branch_code='130', store_code='103', item_code='700001', batch_no='Q', expiry_date=self.exp,
           qty=Decimal('500'))                                                      # quarantine store: never listed
        mk(branch_code='100', store_code='100', item_code='700001', batch_no='H',
           expiry_date=self.today + dt.timedelta(days=100),
           qty=Decimal('70'))                                                       # HQ: never listed
        mk(branch_code='130', store_code='130', item_code='700001', batch_no='FAR',
           expiry_date=self.today + dt.timedelta(days=400), qty=Decimal('80'))      # beyond the horizon
        mk(branch_code='130', store_code='130', item_code='700002', batch_no='F1', expiry_date=self.exp,
           qty=Decimal('10'))                                                       # sells in time
        run = DemandCalculationRun.objects.create()
        for it, br, q90 in ((self.item, self.b130, 9), (self.item, self.b140, 90), (self.fast, self.b130, 900)):
            ItemDemandMetrics.objects.create(run=run, item=it, branch=br, calc_date=self.today, qty_90d=q90)
        self.key = NE.lot_key('130', '130', '700001', 'L1', self.exp)

    def rows(self, **kw):
        return NE.worklist(today=self.today, **kw)['rows']


class WorklistSelectionTests(Base):

    def test_only_at_risk_shelf_lots_of_retail_branches(self):
        rows = self.rows()
        self.assertEqual([r['key'] for r in rows], [self.key])
        r = rows[0]
        self.assertEqual((r['at_risk_qty'], r['at_risk_value'], r['days_left']), (44.0, 440.0, 60))
        self.assertEqual((r['suggested_action'], r['split']), ('move', {'move': 44.0}))
        self.assertEqual(r['detail']['move'][0]['to'], '140')

    def test_fridge_item_is_not_moved(self):
        self.item.requires_fridge = True
        self.item.save(update_fields=['requires_fridge'])
        self.assertEqual(self.rows()[0]['suggested_action'], 'sell_first')

    def test_return_suggested_inside_the_window(self):
        from apps.batches.models import PurchaseExpiryEntry
        from apps.tests.test_return_window import _seed_policies
        _seed_policies()
        PurchaseExpiryEntry.objects.create(branch_code='100', supplier_code='565', supplier_name='S565', doc_number='1',
                                           doc_date=self.today - dt.timedelta(days=200), item_code='700001',
                                           entered_expiry=self.exp, qty=Decimal('100'))
        r = self.rows()[0]
        self.assertEqual((r['suggested_action'], r['detail']['return']['supplier_code']), ('return', '565'))

    def test_pilot_list_narrows_branches(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='near_expiry_worklist_branches', defaults={'value': '140'})
        self.assertEqual(self.rows(), [])


class ActionUniquenessTests(Base):

    def setUp(self):
        super().setUp()
        from apps.tests.factories import make_user
        _, self.staff, self.client_ = make_user('pur_ne', role='purchasing')

    def test_choosing_twice_keeps_one_open_action_and_audits(self):
        from apps.audit.models import AuditLog
        from apps.batches.models import NearExpiryAction
        self.assertEqual(NE.choose([self.key], 'sell_first', self.staff, today=self.today)['created'], 1)
        out = NE.choose([self.key], 'move', self.staff, today=self.today)
        self.assertEqual((out['created'], out['updated']), (0, 1))
        act = NearExpiryAction.objects.get()
        self.assertEqual((act.chosen_action, act.suggested_action, act.t0_at_risk_qty), ('move', 'move', Decimal('44')))
        self.assertEqual(AuditLog.objects.filter(action__startswith='near_expiry_action').count(), 2)

    def test_accept_loss_needs_a_reason_and_unknown_lots_are_skipped(self):
        with self.assertRaises(ValueError):
            NE.choose([self.key], 'accept_loss', self.staff, today=self.today)
        self.assertEqual(NE.choose(['130|x|y|z|2030-01-01'], 'sell_first', self.staff, today=self.today)['skipped'], 1)

    def test_request_return_twice_creates_one_record(self):
        from apps.batches.models import ExpiryDisposalRecord, NearExpiryAction, PurchaseExpiryEntry
        from apps.tests.test_return_window import _seed_policies
        _seed_policies()
        PurchaseExpiryEntry.objects.create(branch_code='100', supplier_code='565', supplier_name='S565', doc_number='1',
                                           doc_date=self.today - dt.timedelta(days=200), item_code='700001',
                                           entered_expiry=self.exp, qty=Decimal('100'))
        first = NE.request_return([self.key], self.staff, today=self.today)
        second = NE.request_return([self.key], self.staff, today=self.today)
        self.assertEqual((first['created'], first['linked'], second['created'], second['linked']), (1, 1, 0, 1))
        self.assertEqual(ExpiryDisposalRecord.objects.count(), 1)
        act = NearExpiryAction.objects.get()
        self.assertEqual((act.chosen_action, act.disposal_record_id), ('return', ExpiryDisposalRecord.objects.get().pk))

    def test_link_transfer_checks_item_and_branch(self):
        from apps.batches.models import NearExpiryAction
        from apps.tests.factories import make_user
        from apps.transfers.models import TransferRequest, TransferRequestItem
        _, ph, _ = make_user('ph_ne', role='pharmacist', branch=self.b140)
        wrong = TransferRequest.objects.create(requesting_branch=self.b130, supplying_branch=self.b140, created_by=ph)
        TransferRequestItem.objects.create(request=wrong, item=self.item, quantity=44)
        r = self.client_.post('/api/batches/near-expiry/link-transfer/', {'key': self.key, 'transfer_id': wrong.pk},
                              format='json')
        self.assertEqual(r.status_code, 403)                     # purchasing cannot create transfers
        _, _, adm = make_user('adm_ne', role='admin', access_all=True)
        r = adm.post('/api/batches/near-expiry/link-transfer/', {'key': self.key, 'transfer_id': wrong.pk}, format='json')
        self.assertEqual(r.status_code, 400)                     # wrong direction
        good = TransferRequest.objects.create(requesting_branch=self.b140, supplying_branch=self.b130, created_by=ph)
        TransferRequestItem.objects.create(request=good, item=self.item, quantity=44)
        r = adm.post('/api/batches/near-expiry/link-transfer/', {'key': self.key, 'transfer_id': good.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(NearExpiryAction.objects.get().transfer_request_id, good.pk)
        self.assertEqual(self.rows()[0]['open_transfer']['id'], good.pk)


class OutcomeTests(Base):

    def setUp(self):
        super().setUp()
        from apps.tests.factories import make_user
        _, self.staff, _ = make_user('pur_out', role='purchasing')
        NE.choose([self.key], 'sell_first', self.staff, today=self.today)

    def line(self, doc, qty, num, storecode2='', exp=None):
        from apps.stock_audit.models import StockLedgerLine
        return StockLedgerLine.objects.create(branchcode='130', doccode=doc, docnumber=num, docdate=self.today,
                                              itemcode='700001', transqty=Decimal(qty), storecode2=storecode2,
                                              itemexpirydate=exp)

    def test_not_due_stays_open(self):
        self.assertEqual(NE.evaluate_outcomes(today=self.today)['closed'], 0)

    def test_sold_out_closes_once_and_each_line_is_used_once(self):
        from apps.batches.models import NearExpiryAction, StockExpiryBalance
        self.line('115', 45, 1)
        self.line('30', 5, 2)                                     # a sale return nets out
        self.line('125', 10, 3, storecode2='140')
        StockExpiryBalance.objects.filter(batch_no='L1').delete()  # the lot left the shelf
        out = NE.evaluate_outcomes(today=self.today)
        self.assertEqual(out['closed'], 1)
        a = NearExpiryAction.objects.get()
        self.assertEqual((a.status, a.outcome, a.outcome_qty), ('closed', 'mixed', {'moved': 10.0, 'sold': 40.0}))
        self.assertEqual((a.saved_value, a.lost_value), (Decimal('440.00'), Decimal('0.00')))
        self.assertEqual(NE.evaluate_outcomes(today=self.today + dt.timedelta(days=90)), {'closed': 0, 'open': 0})
        # a new action on another lot of the same item finds the old lines already used
        from apps.batches.models import StockExpiryBalance as SEB
        SEB.objects.create(branch_code='130', store_code='130', item_code='700001', batch_no='L2',
                           expiry_date=self.exp, qty=Decimal('50'))
        k2 = NE.lot_key('130', '130', '700001', 'L2', self.exp)
        NE.choose([k2], 'sell_first', self.staff, today=self.today)
        SEB.objects.filter(batch_no='L2').delete()
        NE.evaluate_outcomes(today=self.today)
        self.assertEqual(NearExpiryAction.objects.get(batch_no='L2').outcome, 'unexplained')

    def test_expired_on_the_shelf_is_lost(self):
        from apps.batches.models import NearExpiryAction
        NE.evaluate_outcomes(today=self.exp + dt.timedelta(days=1))
        a = NearExpiryAction.objects.get()
        self.assertEqual((a.outcome, a.lost_value), ('expired', Decimal('500.00')))


class ScopeAndPermissionTests(Base):

    def test_branch_user_sees_and_acts_on_own_branch_only(self):
        from apps.batches.models import NearExpiryAction
        from apps.tests.factories import make_user
        _, _, ph140 = make_user('ph140', role='pharmacist', branch=self.b140)
        r = ph140.get('/api/batches/near-expiry/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['rows'], [])
        self.assertTrue(r.data['branch_only'])
        r = ph140.post('/api/batches/near-expiry/choose/', {'lots': [self.key], 'action': 'sell_first'}, format='json')
        self.assertEqual((r.status_code, r.data['created']), (200, 0))
        self.assertFalse(NearExpiryAction.objects.exists())
        _, _, ph130 = make_user('ph130', role='pharmacist', branch=self.b130)
        self.assertEqual(len(ph130.get('/api/batches/near-expiry/').data['rows']), 1)
        r = ph130.post('/api/batches/near-expiry/choose/', {'lots': [self.key], 'action': 'sell_first'}, format='json')
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(len(ph140.get('/api/batches/near-expiry/outcomes/').data['rows']), 0)
        self.assertEqual(len(ph130.get('/api/batches/near-expiry/outcomes/').data['rows']), 1)

    def test_viewer_cannot_choose(self):
        from apps.tests.factories import make_viewer
        _, _, viewer = make_viewer('viewer_ne', branch=self.b130)
        r = viewer.post('/api/batches/near-expiry/choose/', {'lots': [self.key], 'action': 'sell_first'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(viewer.post('/api/batches/near-expiry/check-outcomes/').status_code, 403)
