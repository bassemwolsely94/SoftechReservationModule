"""
Phase-1 tests for the DemandSignal provenance/dedup ledger (doc 24 §22/§23).

Covers: idempotent ingestion, the reconcile rules (customer SUM, branch MAX-dedup,
statistical indicator), provenance preservation, and each source adapter.
"""
from django.test import TestCase

from apps.supply.models import DemandSignal
from apps.supply import demand_signals as ds
from apps.supply.reconcile import reconcile_item, reconcile_items


def _sig(item, cls, qty, ref, *, branch=None, status=DemandSignal.STATUS_OPEN):
    """Create a DemandSignal directly (source_type irrelevant to reconcile)."""
    s, _ = ds.record_signal('manual', ref, provenance_class=cls, qty=qty,
                            item_id=item.id, branch_id=(branch.id if branch else None),
                            status=status)
    return s


class RecordSignalIdempotencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        cls.item = Item.objects.create(softech_id='300001', name='ITEM', is_active=True)

    def test_upsert_is_idempotent_and_updates_qty(self):
        s1, c1 = ds.record_signal('reservation', '42',
                                  provenance_class=DemandSignal.CLASS_CUSTOMER,
                                  qty=3, item_id=self.item.id)
        s2, c2 = ds.record_signal('reservation', '42',
                                  provenance_class=DemandSignal.CLASS_CUSTOMER,
                                  qty=5, item_id=self.item.id)
        self.assertTrue(c1)
        self.assertFalse(c2)              # same source_ref → updated, not duplicated
        self.assertEqual(s1.id, s2.id)
        self.assertEqual(DemandSignal.objects.count(), 1)
        self.assertEqual(float(s2.qty), 5.0)


class ReconcileRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='310001', name='DRUG', is_active=True)
        cls.b1 = Branch.objects.create(softech_branch_id='130', name='B130')
        cls.b2 = Branch.objects.create(softech_branch_id='140', name='B140')

    def test_customer_commitments_sum(self):
        # 3 independent customers waiting for 1 each → 3 (additive).
        for i in range(3):
            _sig(self.item, DemandSignal.CLASS_CUSTOMER, 1, f'c{i}', branch=self.b1)
        r = reconcile_item(self.item.id)
        self.assertEqual(r['customer_demand'], 3.0)
        self.assertEqual(r['deduped_total'], 3.0)

    def test_branch_echoes_dedup_to_max_not_sum(self):
        # ISR-like 5 + WhatsApp-like 5 for the SAME item+branch → 5, not 10 (§22).
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b-a', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b-b', branch=self.b1)
        r = reconcile_item(self.item.id)
        self.assertEqual(r['branch_request'], 5.0)
        self.assertEqual(r['raw_total'], 10.0)             # naive sum
        self.assertEqual(r['double_count_avoided'], 5.0)

    def test_branch_dedup_takes_larger_expression(self):
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b-a', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_BRANCH, 8, 'b-b', branch=self.b1)
        r = reconcile_item(self.item.id)
        self.assertEqual(r['branch_request'], 8.0)         # max, the larger single ask

    def test_branch_demand_sums_across_branches_but_dedups_within(self):
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b1-a', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b1-b', branch=self.b1)  # echo at b1
        _sig(self.item, DemandSignal.CLASS_BRANCH, 3, 'b2-a', branch=self.b2)
        r = reconcile_item(self.item.id)
        self.assertEqual(r['branch_request'], 8.0)         # max(5,5)=5 at b1 + 3 at b2

    def test_branch_filter_scopes_to_one_branch(self):
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b1-a', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_BRANCH, 3, 'b2-a', branch=self.b2)
        r = reconcile_item(self.item.id, branch_id=self.b1.id)
        self.assertEqual(r['branch_request'], 5.0)

    def test_customer_plus_branch_combine_statistical_is_indicator_only(self):
        _sig(self.item, DemandSignal.CLASS_CUSTOMER, 2, 'c1', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b1', branch=self.b1)
        _sig(self.item, DemandSignal.CLASS_STATISTICAL, 12, 's1')
        r = reconcile_item(self.item.id)
        self.assertEqual(r['customer_demand'], 2.0)
        self.assertEqual(r['branch_request'], 5.0)
        self.assertEqual(r['statistical'], 12.0)
        self.assertEqual(r['deduped_total'], 7.0)          # 2 + 5 — statistical NOT added

    def test_closed_signals_are_ignored(self):
        _sig(self.item, DemandSignal.CLASS_CUSTOMER, 4, 'c1', branch=self.b1,
             status=DemandSignal.STATUS_SUPERSEDED)
        r = reconcile_item(self.item.id)
        self.assertEqual(r['deduped_total'], 0.0)
        self.assertEqual(r['signal_count'], 0)

    def test_provenance_is_preserved_in_output(self):
        _sig(self.item, DemandSignal.CLASS_BRANCH, 5, 'b-a', branch=self.b1)
        r = reconcile_item(self.item.id)
        self.assertEqual(len(r['signals']), 1)
        prov = r['signals'][0]
        self.assertEqual(prov['provenance_class'], DemandSignal.CLASS_BRANCH)
        self.assertEqual(prov['branch_id'], self.b1.id)
        self.assertEqual(prov['qty'], 5.0)


class ReservationAdapterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        from apps.customers.models import Customer
        cls.item = Item.objects.create(softech_id='320001', name='ITM', is_active=True)
        cls.item2 = Item.objects.create(softech_id='320002', name='ITM2', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B')
        cls.cust = Customer.objects.create(softech_pic='130HD1', name='Cust')

    def test_open_reservation_becomes_signal_fulfilled_is_closed(self):
        from apps.reservations.models import Reservation
        r_open = Reservation.objects.create(item=self.item, branch=self.branch,
                                            customer=self.cust, quantity_requested=2,
                                            status='pending', contact_phone='0100',
                                            contact_name='A')
        Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=9,
                                   status='fulfilled', contact_phone='0101', contact_name='B')
        res = ds.sync_reservations()
        self.assertEqual(res['created'], 1)                # only the open one
        sig = DemandSignal.objects.get(source_type='reservation', source_ref=str(r_open.pk))
        self.assertEqual(sig.provenance_class, DemandSignal.CLASS_CUSTOMER)
        self.assertEqual(float(sig.qty), 2.0)
        self.assertEqual(sig.customer_id, self.cust.id)

    def test_cancelled_reservation_closes_prior_open_signal(self):
        from apps.reservations.models import Reservation
        r = Reservation.objects.create(item=self.item, branch=self.branch,
                                       quantity_requested=1, status='pending',
                                       contact_phone='0100', contact_name='A')
        ds.sync_reservations()
        self.assertEqual(DemandSignal.objects.filter(status='open').count(), 1)
        r.status = 'cancelled'
        r.save(update_fields=['status'])
        ds.sync_reservations()
        sig = DemandSignal.objects.get(source_ref=str(r.pk))
        self.assertEqual(sig.status, DemandSignal.STATUS_SUPERSEDED)

    def test_multi_item_basket_creates_one_signal_per_line(self):
        from apps.reservations.models import Reservation, ReservationLine
        r = Reservation.objects.create(branch=self.branch, quantity_requested=1,
                                       status='pending', contact_phone='0100', contact_name='A')
        ReservationLine.objects.create(reservation=r, item=self.item, quantity_requested=2)
        ReservationLine.objects.create(reservation=r, item=self.item2, quantity_requested=3)
        res = ds.sync_reservations()
        self.assertEqual(res['created'], 2)
        self.assertEqual(DemandSignal.objects.filter(source_type='reservation').count(), 2)


class ShortageAndDemandAdapterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='330001', name='ITM', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B')

    def test_matched_shortage_item_becomes_branch_signal(self):
        from apps.shortage.models import ShortageList, ShortageItem
        sl = ShortageList.objects.create(branch=self.branch, status='open')
        ShortageItem.objects.create(shortage_list=sl, raw_name='drug', item=self.item,
                                    quantity_needed=6, is_confirmed=True)
        res = ds.sync_shortage_items()
        self.assertEqual(res['created'], 1)
        sig = DemandSignal.objects.get(source_type='shortage_item')
        self.assertEqual(sig.provenance_class, DemandSignal.CLASS_BRANCH)
        self.assertEqual(float(sig.qty), 6.0)
        self.assertEqual(sig.branch_id, self.branch.id)

    def test_resolved_list_excluded_and_closes_signal(self):
        from apps.shortage.models import ShortageList, ShortageItem
        sl = ShortageList.objects.create(branch=self.branch, status='open')
        ShortageItem.objects.create(shortage_list=sl, raw_name='drug', item=self.item,
                                    quantity_needed=6)
        ds.sync_shortage_items()
        sl.status = 'resolved'
        sl.save(update_fields=['status'])
        ds.sync_shortage_items()
        self.assertEqual(DemandSignal.objects.filter(source_type='shortage_item',
                                                     status='open').count(), 0)

    def test_demand_item_becomes_customer_signal(self):
        from apps.demand.models import DemandRecord, DemandItem
        dr = DemandRecord.objects.create(phone='0100', customer_name='X', branch=self.branch)
        DemandItem.objects.create(demand=dr, item=self.item, quantity=4, item_status='pending')
        res = ds.sync_demand_items()
        self.assertEqual(res['created'], 1)
        sig = DemandSignal.objects.get(source_type='demand_item')
        self.assertEqual(sig.provenance_class, DemandSignal.CLASS_CUSTOMER)
        self.assertEqual(float(sig.qty), 4.0)

    def test_sync_all_runs_every_adapter(self):
        result = ds.sync_all()
        self.assertEqual({r['source'] for r in result['sources']},
                         {'reservation', 'demand_item', 'shortage_item', 'market_shortage'})
        self.assertIn('totals', result)


class EndToEndDedupTests(TestCase):
    """The §22 scenario end to end: a branch ISR-style shortage AND the same need pasted
    from WhatsApp must NOT read as double the demand."""
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='340001', name='OZEMPIC', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B')

    def test_two_shortage_lists_same_need_reconcile_to_one(self):
        from apps.shortage.models import ShortageList, ShortageItem
        for tag in ('isr', 'whatsapp'):
            sl = ShortageList.objects.create(branch=self.branch, status='open', title=tag)
            ShortageItem.objects.create(shortage_list=sl, raw_name='ozempic',
                                        item=self.item, quantity_needed=5)
        ds.sync_shortage_items()
        r = reconcile_item(self.item.id)
        self.assertEqual(r['branch_request'], 5.0)         # deduped, NOT 10
        self.assertEqual(r['raw_total'], 10.0)
        self.assertEqual(r['double_count_avoided'], 5.0)
