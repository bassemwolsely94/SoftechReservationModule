"""
apps/tests/test_callcenter_network_stock.py — full audit Wave 2, C01.

Network stock inside the call centre and the omni inbox reuses the existing APIs:
  • the call screen's «📍» drawer reserves / transfers ONE call item through the call's own convert
    endpoints (item_ids=[that item]) — linked to the call, and allowed for the call-centre role, which
    may not create transfers directly;
  • convert-to-reservation stores the form's pickup / delivery choice in fulfillment_method; it used to
    write 'pickup' into Reservation.channel (a POS sale type), outside its choices;
  • a reservation is never stored with a masked contact number («••••678»);
  • demand / reservations created from the call centre or omni carry their source tag.
"""
from django.core.management import call_command
from django.test import TestCase

from apps.callcenter.models import CallItem, CallLog
from apps.demand.models import DemandRecord
from apps.reservations.models import Reservation
from apps.transfers.models import TransferRequest

from .factories import make_branch, make_branch2, make_call_center, make_customer, make_item


class _CallBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)    # the role matrix is enforced only once seeded

    def setUp(self):
        self.branch = make_branch()
        self.other = make_branch2()
        _, _, self.cc = make_call_center('cc_c01')
        self.customer = make_customer()
        self.call = CallLog.objects.create(phone_number=self.customer.phone, customer=self.customer,
                                           branch=self.branch)
        self.item_a = make_item('باراسيتامول', 'IT001')
        self.item_b = make_item('أموكسيسيللين', 'IT002')
        self.ci_a = CallItem.objects.create(call_log=self.call, item=self.item_a, quantity=2)
        self.ci_b = CallItem.objects.create(call_log=self.call, item=self.item_b, quantity=1)

    def _url(self, action):
        return f'/api/callcenter/calls/{self.call.pk}/{action}/'


class ConvertOneItemFromDrawerTests(_CallBase):
    def test_reserve_one_item_at_another_branch_stays_linked(self):
        r = self.cc.post(self._url('convert-to-reservation'),
                         {'branch_id': self.other.pk, 'item_ids': [self.ci_a.pk]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.ci_a.refresh_from_db(); self.ci_b.refresh_from_db()
        self.assertEqual(self.ci_a.converted_to, 'reservation')
        self.assertEqual(self.ci_b.converted_to, 'none')          # only the drawer's item
        res = self.ci_a.converted_reservation
        self.assertEqual(res.branch_id, self.other.pk)            # reserved where the stock is
        self.assertEqual(res.order_source, 'cc_call')
        self.assertEqual(res.quantity_requested, 2)               # the call item's quantity

    def test_transfer_one_item_from_a_source_branch_as_call_center(self):
        r = self.cc.post(self._url('convert-to-transfer'), {
            'requesting_branch_id': self.branch.pk, 'supplying_branch_id': self.other.pk,
            'item_ids': [self.ci_b.pk]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        tr = TransferRequest.objects.get(pk=r.json()['transfer_request_id'])
        self.assertEqual((tr.requesting_branch_id, tr.supplying_branch_id), (self.branch.pk, self.other.pk))
        self.assertEqual(list(tr.items.values_list('item_id', flat=True)), [self.item_b.pk])
        self.ci_b.refresh_from_db()
        self.assertEqual(self.ci_b.converted_to, 'transfer')

    def test_call_center_cannot_create_a_transfer_directly(self):
        """Why the call screen's drawer goes through the call: transfers are view-only for this role."""
        r = self.cc.post('/api/transfers/', {
            'requesting_branch': self.branch.pk, 'supplying_branch': self.other.pk,
            'items': [{'item': self.item_a.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 403, r.content)


class ConvertReservationChannelTests(_CallBase):
    def _convert(self, **extra):
        r = self.cc.post(self._url('convert-to-reservation'),
                         {'branch_id': self.branch.pk, 'item_ids': [self.ci_a.pk], **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.ci_a.refresh_from_db()
        return self.ci_a.converted_reservation

    def test_pickup_goes_to_fulfillment_not_channel(self):
        res = self._convert(channel='pickup')
        self.assertEqual(res.channel, 'cash_sales')
        self.assertEqual(res.fulfillment_method, 'pickup')
        self.assertIn(res.channel, dict(Reservation.CHANNEL_CHOICES))

    def test_home_delivery(self):
        res = self._convert(channel='home_delivery')
        self.assertEqual((res.channel, res.fulfillment_method), ('home_delivery', 'delivery'))

    def test_default_is_a_valid_channel(self):
        res = self._convert()
        self.assertIn(res.channel, dict(Reservation.CHANNEL_CHOICES))
        self.assertEqual(res.fulfillment_method, 'pickup')


class DrawerDirectCreateTests(TestCase):
    """The omni drawer creates through the normal APIs with the conversation's source."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_c01_omni')
        self.item = make_item()
        self.customer = make_customer()

    def _reserve(self, phone):
        return self.cc.post('/api/reservations/', {
            'branch': self.branch.pk, 'item': self.item.pk, 'quantity_requested': 1,
            'contact_phone': phone, 'contact_name': 'عميل', 'customer': self.customer.pk,
            'order_source': 'cc_whatsapp', 'notes': 'حجز من الكول سنتر — واتساب'}, format='json')

    def test_reservation_keeps_the_omni_source(self):
        r = self._reserve('01012345678')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Reservation.objects.get(pk=r.json()['id']).order_source, 'cc_whatsapp')

    def test_masked_contact_number_is_refused(self):
        r = self._reserve('••••••••678')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('contact_phone', r.json())
        self.assertFalse(Reservation.objects.exists())

    def test_demand_keeps_the_call_center_source(self):
        r = self.cc.post('/api/demand/', {
            'phone': '01012345678', 'customer_name': 'عميل', 'branch': self.branch.pk,
            'source': 'call_center',
            'items': [{'item': self.item.pk, 'quantity': 1, 'demand_type': 'out_of_stock'}]}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(DemandRecord.objects.get().source, 'call_center')
