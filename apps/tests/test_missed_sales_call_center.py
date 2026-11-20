"""
C28 — missed-sale suggestions from call-centre items that were not ordered.

Second source into the Project 3 inbox, behind its own switch (MISSED_SALES_CALLCENTER_ENABLED,
default OFF). Rules: call old enough, item not converted, real known customer, not bought since
the call, no open suggestion (either source) or reservation; idempotent per call item. Postgres
only — no SOFTECH contact, nothing created without a person.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter.models import CallItem, CallLog
from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from apps.pos_orders.missed_sales import (
    call_center_enabled, detect_call_center_missed_sales, detect_missed_sales,
)
from apps.pos_orders.models import MissedSaleSuggestion, PosSelectionEvent
from apps.reservations.models import Reservation
from .factories import make_branch, make_branch2, make_customer, make_item, make_pharmacist

ON = override_settings(MISSED_SALES_ENABLED=True, MISSED_SALES_CALLCENTER_ENABLED=True,
                       MISSED_SALES_CALL_WAIT_DAYS=2, MISSED_SALES_EXPIRE_DAYS=14,
                       MISSED_SALES_MIN_AGE_MINUTES=60)


class _Base(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.item = make_item()
        self.item.pack_price = Decimal('40')
        self.item.save()
        self.customer = make_customer()
        self.customer.softech_pic = '170HD9'
        self.customer.save()

    def _call_item(self, *, days_ago=3, customer=None, branch='default', converted='none', qty=2):
        log = CallLog.objects.create(
            phone_number='01012345678', customer=customer or self.customer, purpose='demand',
            branch=self.branch if branch == 'default' else branch,
            called_at=timezone.now() - timedelta(days=days_ago))
        return CallItem.objects.create(call_log=log, item=self.item, quantity=qty, converted_to=converted)


@ON
class DetectorTests(_Base):
    def test_unordered_call_item_becomes_call_center_suggestion(self):
        ci = self._call_item()
        s = detect_missed_sales()
        self.assertEqual(s['call_center']['created'], 1)
        m = MissedSaleSuggestion.objects.get()
        self.assertEqual((m.source, m.call_item, m.customer, m.branch, m.item_code, m.status),
                         ('call_center', ci, self.customer, self.branch, 'IT001', 'new'))
        self.assertEqual(m.value, Decimal('80.00'))          # 2 × pack price
        self.assertIsNone(m.cart_token)

    def test_rerun_is_idempotent(self):
        self._call_item()
        detect_call_center_missed_sales()
        self.assertEqual(detect_call_center_missed_sales()['created'], 0)
        self.assertEqual(MissedSaleSuggestion.objects.count(), 1)

    def test_too_recent_or_too_old_skipped(self):
        self._call_item(days_ago=0)
        self._call_item(days_ago=20)
        self.assertEqual(detect_call_center_missed_sales()['created'], 0)

    def test_converted_item_skipped(self):
        self._call_item(converted='reservation')
        self.assertEqual(detect_call_center_missed_sales()['created'], 0)

    def test_manual_item_without_catalog_skipped(self):
        log = CallLog.objects.create(phone_number='010', customer=self.customer, purpose='demand',
                                     branch=self.branch, called_at=timezone.now() - timedelta(days=3))
        CallItem.objects.create(call_log=log, manual_item_name='صنف يدوي')
        self.assertEqual(detect_call_center_missed_sales()['created'], 0)

    def test_placeholder_customer_excluded(self):
        self.customer.is_account_placeholder = True
        self.customer.save()
        self._call_item()
        s = detect_call_center_missed_sales()
        self.assertEqual((s['created'], s['skipped_customer']), (0, 1))

    def test_unknown_caller_excluded(self):
        log = CallLog.objects.create(phone_number='010', purpose='demand', branch=self.branch,
                                     called_at=timezone.now() - timedelta(days=3))
        CallItem.objects.create(call_log=log, item=self.item)
        self.assertEqual(detect_call_center_missed_sales()['created'], 0)

    def test_bought_after_the_call_skipped(self):
        self._call_item()
        p = PurchaseHistory.objects.create(customer=self.customer, softech_invoice_id='CC1',
                                           branch=self.branch, doc_code='115',
                                           invoice_date=timezone.now() - timedelta(days=1))
        PurchaseHistoryLine.objects.create(purchase=p, item=self.item, quantity=1, unit_price=40,
                                           line_total=40)
        self.assertEqual(detect_call_center_missed_sales()['skipped_sold'], 1)

    def test_open_reservation_blocks(self):
        Reservation.objects.create(customer=self.customer, item=self.item, branch=self.branch,
                                   contact_phone='01012345678', contact_name='x', status='pending')
        self._call_item()
        self.assertEqual(detect_call_center_missed_sales()['skipped_open'], 1)

    def test_no_branch_skipped(self):
        self.customer.preferred_branch = None
        self.customer.save()
        self._call_item(branch=None)
        self.assertEqual(detect_call_center_missed_sales()['skipped_branch'], 1)

    def test_falls_back_to_customer_branch(self):
        self.customer.preferred_branch = self.branch
        self.customer.save()
        self._call_item(branch=None)
        detect_call_center_missed_sales()
        self.assertEqual(MissedSaleSuggestion.objects.get().branch, self.branch)

    def test_dedupe_with_pos_source(self):
        """A POS suggestion for the same customer + item blocks the call one, and vice versa."""
        PosSelectionEvent.objects.create(
            cart_token=uuid.uuid4(), branch=self.branch, softech_branchcode=self.branch.softech_branch_id,
            doc_kind='sale', event_type='add', item_code='IT001', item_name='باراسيتامول',
            itemsaleprice='50', transprice='50', transqty=1, transprice_total='50', custcode='1510',
            seller_usercode='1509', customer=self.customer,
            occurred_at=timezone.now() - timedelta(minutes=120))
        self._call_item()
        s = detect_missed_sales()
        self.assertEqual(s['created'], 1)                      # POS first
        self.assertEqual(s['call_center']['skipped_open'], 1)
        self.assertEqual(MissedSaleSuggestion.objects.get().source, 'pos')

    def test_two_calls_same_item_one_suggestion(self):
        self._call_item(days_ago=3)
        self._call_item(days_ago=4)
        detect_call_center_missed_sales()
        self.assertEqual(MissedSaleSuggestion.objects.count(), 1)


class SwitchTests(_Base):
    @override_settings(MISSED_SALES_ENABLED=True, MISSED_SALES_CALLCENTER_ENABLED=False)
    def test_call_center_source_off_by_default_switch(self):
        self._call_item()
        self.assertFalse(call_center_enabled())
        s = detect_missed_sales()
        self.assertNotIn('call_center', s)
        self.assertEqual(MissedSaleSuggestion.objects.count(), 0)

    @override_settings(MISSED_SALES_ENABLED=False, MISSED_SALES_CALLCENTER_ENABLED=True)
    def test_needs_the_inbox_switch_too(self):
        self.assertFalse(call_center_enabled())


@ON
class InboxTests(_Base):
    def setUp(self):
        super().setUp()
        self.ci = self._call_item()
        detect_call_center_missed_sales()
        self.m = MissedSaleSuggestion.objects.get()
        _, self.prof, self.client = make_pharmacist('ph_cc_missed', branch=self.branch)

    def test_list_shows_source_and_call(self):
        r = self.client.get('/api/pos-orders/missed-sales/')
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()['results'][0]
        self.assertEqual((row['source'], row['call_log']), ('call_center', self.ci.call_log_id))
        self.assertEqual(row['source_label'], 'الكول سنتر')

    def test_source_filter(self):
        self.assertEqual(len(self.client.get('/api/pos-orders/missed-sales/?source=pos').json()['results']), 0)
        self.assertEqual(len(self.client.get('/api/pos-orders/missed-sales/?source=call_center')
                             .json()['results']), 1)

    def test_other_branch_cannot_see(self):
        _, _, c2 = make_pharmacist('ph_cc_other', branch=make_branch2())
        self.assertEqual(c2.get('/api/pos-orders/missed-sales/').json()['results'], [])

    def test_confirm_notes_the_call(self):
        body = {'customer': self.customer.pk, 'item': self.item.pk, 'branch': self.branch.pk,
                'quantity_requested': 2, 'contact_phone': '01012345678', 'contact_name': 'أحمد',
                'order_source': 'pos_missed', 'missed_sale': self.m.pk}
        r = self.client.post('/api/reservations/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        res = Reservation.objects.get()
        self.assertTrue(res.activities.filter(message__contains='طُلب في مكالمة').exists())
        self.m.refresh_from_db()
        self.assertEqual(self.m.status, 'confirmed')
