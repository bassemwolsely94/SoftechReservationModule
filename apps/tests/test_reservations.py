"""
apps/tests/test_reservations.py

Tests covering:
  - Reservation CRUD (create, list, retrieve, update)
  - Branch-scoped data isolation (pharmacist only sees own branch)
  - Status machine: valid + invalid transitions
  - ERP match: role guard (403 for wrong role)
  - ERP match: status guard (400 for non-fulfilled)
  - ERP match: rate-limit guard (429 on rapid re-check)
  - Activity / chatter log
  - Downpayments: create, list
  - Image upload
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.reservations.models import Reservation, ReservationActivity
from .factories import (
    make_branch, make_branch2, make_admin, make_pharmacist,
    make_call_center, make_salesperson, make_item, make_customer,
)

RES_URL      = '/api/reservations/'
LOGIN_URL    = '/api/auth/login/'


def _res_url(pk, action=''):
    base = f'{RES_URL}{pk}/'
    return base + action + ('/' if action else '')


class ReservationCreateTests(TestCase):

    def setUp(self):
        self.branch  = make_branch()
        self.item    = make_item()
        self.customer = make_customer()
        _, self.profile, self.client = make_pharmacist('pharma_create', branch=self.branch)

    def _payload(self, **kw):
        base = {
            'item': self.item.id,
            'branch': self.branch.id,
            'quantity_requested': 2,
            'contact_name': 'أحمد تجريبي',
            'contact_phone': '01099990001',
            'priority': 'normal',
            'channel': 'cash_sales',          # valid POS channel (pickup is a fulfillment_method)
            'fulfillment_method': 'pickup',
        }
        base.update(kw)
        return base

    def test_create_reservation_success(self):
        r = self.client.post(RES_URL, self._payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        # create serializer returns write fields only; check DB for status
        res = Reservation.objects.get(pk=r.data['id'])
        self.assertEqual(res.status, 'pending')

    def test_create_sets_created_by(self):
        r = self.client.post(RES_URL, self._payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        res = Reservation.objects.get(pk=r.data['id'])
        self.assertEqual(res.created_by, self.profile)

    def test_create_requires_auth(self):
        anon = APIClient()
        r = anon.post(RES_URL, self._payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_item_or_manual_name(self):
        """A reservation without item and without manual_item_name must fail."""
        payload = self._payload()
        payload.pop('item')
        r = self.client.post(RES_URL, payload, format='json')
        self.assertIn(r.status_code, [
            status.HTTP_400_BAD_REQUEST,  # explicit validation error
        ])

    def test_create_manual_item_name(self):
        """Reservation with no FK item but manual_item_name is valid."""
        payload = {
            'manual_item_name': 'دواء غير مكوَّد',
            'branch': self.branch.id,
            'quantity_requested': 1,
            'contact_name': 'محمد',
            'contact_phone': '01099990002',
            'priority': 'normal',
            'channel': 'cash_sales',          # valid POS channel (pickup is a fulfillment_method)
            'fulfillment_method': 'pickup',
        }
        r = self.client.post(RES_URL, payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_quantity_zero_rejected(self):
        r = self.client.post(RES_URL, self._payload(quantity_requested=0), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_quantity_negative_rejected(self):
        r = self.client.post(RES_URL, self._payload(quantity_requested=-1), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class ReservationBranchScopingTests(TestCase):
    """Pharmacist must only see reservations for their own branch."""

    def setUp(self):
        self.branch1 = make_branch('فرع 1', 'B01')
        self.branch2 = make_branch2('فرع 2', 'B02')
        self.item = make_item()

        _, self.prof1, self.client1 = make_pharmacist('pharma_scope1', branch=self.branch1)
        _, self.prof2, self.client2 = make_pharmacist('pharma_scope2', branch=self.branch2)
        _, _, self.admin_client = make_admin('admin_scope')

        # Create one reservation per branch
        self.res1 = Reservation.objects.create(
            item=self.item, branch=self.branch1,
            quantity_requested=1, contact_name='عميل 1',
            contact_phone='01011111111', created_by=self.prof1,
        )
        self.res2 = Reservation.objects.create(
            item=self.item, branch=self.branch2,
            quantity_requested=1, contact_name='عميل 2',
            contact_phone='01022222222', created_by=self.prof2,
        )

    def test_pharmacist_sees_only_own_branch(self):
        r = self.client1.get(RES_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        ids = [row['id'] for row in results]
        self.assertIn(self.res1.id, ids)
        self.assertNotIn(self.res2.id, ids)

    def test_pharmacist_cannot_retrieve_other_branch(self):
        """Pharmacist from branch1 cannot access branch2 reservation by PK."""
        r = self.client1.get(_res_url(self.res2.id))
        # Should be 404 (not in their queryset) or 403
        self.assertIn(r.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])

    def test_admin_sees_all_branches(self):
        r = self.admin_client.get(RES_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        ids = [row['id'] for row in results]
        self.assertIn(self.res1.id, ids)
        self.assertIn(self.res2.id, ids)


class ReservationStatusMachineTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.item   = make_item()
        _, self.profile, self.client = make_pharmacist('pharma_sm', branch=self.branch)
        self.res = Reservation.objects.create(
            item=self.item, branch=self.branch,
            quantity_requested=1, contact_name='عميل SM',
            contact_phone='01033333333', created_by=self.profile,
        )

    def _change_status(self, new_status, note=''):
        return self.client.post(
            _res_url(self.res.id, 'change-status'),
            {'status': new_status, 'note': note},
            format='json',
        )

    def test_pending_to_available(self):
        r = self._change_status('available')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, 'available')

    def test_pending_to_fulfilled_not_directly_allowed(self):
        """Gap-6 FIXED: pending → fulfilled is not in the valid transition graph."""
        r = self._change_status('fulfilled')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST,
                         'Direct jump from pending to fulfilled must be rejected')

    def test_same_status_returns_400(self):
        r = self._change_status('pending')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_status_change_logs_activity(self):
        initial_count = ReservationActivity.objects.filter(reservation=self.res).count()
        self._change_status('available')
        new_count = ReservationActivity.objects.filter(reservation=self.res).count()
        self.assertGreater(new_count, initial_count,
                           'Status change must create a ReservationActivity entry')

    def test_status_change_requires_auth(self):
        anon = APIClient()
        r = anon.post(_res_url(self.res.id, 'change-status'), {'status': 'available'})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class ReservationERPMatchGuardTests(TestCase):
    """ERP match endpoint must enforce role + status + rate-limit guards."""

    def setUp(self):
        self.branch = make_branch()
        self.item   = make_item()
        _, self.prof_admin, self.admin_client = make_admin('admin_erp')
        _, self.prof_pharma, self.pharma_client = make_pharmacist('pharma_erp', branch=self.branch)
        _, self.prof_sales, self.sales_client = make_salesperson('sales_erp', branch=self.branch)

        self.res_pending = Reservation.objects.create(
            item=self.item, branch=self.branch,
            quantity_requested=1, contact_name='Test',
            contact_phone='01044444444', created_by=self.prof_pharma,
            status='pending',
        )
        self.res_fulfilled = Reservation.objects.create(
            item=self.item, branch=self.branch,
            quantity_requested=1, contact_name='Test Fulfilled',
            contact_phone='01055555555', created_by=self.prof_pharma,
            status='fulfilled',
        )

    def _check(self, client, res_id):
        return client.post(_res_url(res_id, 'check-erp-match'))

    def test_wrong_role_salesperson_gets_403(self):
        r = self._check(self.sales_client, self.res_fulfilled.id)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_fulfilled_status_gets_400(self):
        r = self._check(self.pharma_client, self.res_pending.id)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anon_gets_401(self):
        r = self._check(APIClient(), self.res_fulfilled.id)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rate_limit_429_within_20_seconds(self):
        """
        After one check, the 20-second cooldown must fire on the second call.
        We simulate this by setting erp_last_checked to now.
        """
        self.res_fulfilled.erp_last_checked = timezone.now()
        self.res_fulfilled.save(update_fields=['erp_last_checked'])

        r = self._check(self.pharma_client, self.res_fulfilled.id)
        self.assertEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                         'Second check within 20s must return 429')

    def test_rate_limit_detail_contains_seconds(self):
        self.res_fulfilled.erp_last_checked = timezone.now()
        self.res_fulfilled.save(update_fields=['erp_last_checked'])

        r = self._check(self.pharma_client, self.res_fulfilled.id)
        self.assertIn('ثانية', r.data.get('detail', ''),
                      'Rate-limit error must mention the wait time in Arabic')


class ReservationChatterTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.item   = make_item()
        _, self.profile, self.client = make_pharmacist('pharma_chat', branch=self.branch)
        self.res = Reservation.objects.create(
            item=self.item, branch=self.branch,
            quantity_requested=1, contact_name='عميل محادثة',
            contact_phone='01066666666', created_by=self.profile,
        )

    def test_post_activity_note(self):
        r = self.client.post(
            _res_url(self.res.id, 'log'),
            {'activity_type': 'note', 'message': 'ملاحظة اختبار'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_post_empty_activity_fails(self):
        """Empty message + no attachment + no voice = 400."""
        r = self.client.post(
            _res_url(self.res.id, 'log'),
            {'activity_type': 'note', 'message': ''},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_activity_requires_auth(self):
        r = APIClient().post(
            _res_url(self.res.id, 'log'),
            {'activity_type': 'note', 'message': 'test'},
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class ReservationDownpaymentTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.item   = make_item()
        _, self.profile, self.client = make_pharmacist('pharma_dp', branch=self.branch)
        self.res = Reservation.objects.create(
            item=self.item, branch=self.branch,
            quantity_requested=1, contact_name='عميل دفعة',
            contact_phone='01077777777', created_by=self.profile,
        )

    def test_create_downpayment(self):
        r = self.client.post(
            _res_url(self.res.id, 'downpayments'),
            {'amount': '100.00', 'payment_method': 'cash'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(r.data['amount']), 100.0)

    def test_downpayment_zero_amount_rejected(self):
        r = self.client.post(
            _res_url(self.res.id, 'downpayments'),
            {'amount': '0', 'payment_method': 'cash'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_downpayment_negative_rejected(self):
        r = self.client.post(
            _res_url(self.res.id, 'downpayments'),
            {'amount': '-50', 'payment_method': 'cash'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_downpayments(self):
        self.client.post(
            _res_url(self.res.id, 'downpayments'),
            {'amount': '50', 'payment_method': 'card'},
            format='json',
        )
        r = self.client.get(_res_url(self.res.id, 'downpayments'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # Endpoint returns {total_paid, downpayments: [...]} — check the list
        dps = r.data.get('downpayments', r.data)
        self.assertEqual(len(dps), 1)
