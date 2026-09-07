"""
apps/tests/test_pos_api.py

API + RBAC for the Indirect-POS endpoints. No SOFTECH contact (push is dry-run).
"""
from rest_framework.test import APIClient
from rest_framework import status
from django.test import TestCase

from apps.pos_orders.models import SoftechSalesOrder
from .factories import make_branch, make_call_center, make_user

BASE = '/api/pos-orders/'


def _payload(branch_id, channel='cash'):
    return {
        'branch': branch_id, 'channel': channel, 'doc_kind': 'sale',
        'softech_pic': '130HD9668', 'customer_name': 'TEST',
        'lines': [
            {'softech_itemcode': '107295', 'item_name': 'I1', 'qty': 1, 'item_sale_price': 108, 'cust_discp': 15},
            {'softech_itemcode': '94965',  'item_name': 'I2', 'qty': 1, 'item_sale_price': 216, 'cust_discp': 15},
        ],
    }


class PosApiTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_pos')                      # operator (can push)
        _, _, self.viewer = make_user('viewer_pos', role='viewer')      # active but not a push role

    def test_anonymous_denied(self):
        r = APIClient().get(BASE)
        self.assertIn(r.status_code, (401, 403))

    def test_reference_endpoint_reports_writer_disabled(self):
        r = self.cc.get(BASE + 'reference/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['writer_enabled'])

    def test_client_token_create_is_idempotent(self):
        # a replayed offline create (same client_token) must return the SAME order, not a dup
        payload = {**_payload(self.branch.id), 'client_token': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}
        r1 = self.cc.post(BASE, payload, format='json')
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        r2 = self.cc.post(BASE, payload, format='json')          # the replay
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(SoftechSalesOrder.objects.filter(
            client_token='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee').count(), 1)

    def test_malformed_client_token_does_not_500(self):
        # a junk token must be ignored (fresh order), not crash the UUIDField query
        payload = {**_payload(self.branch.id), 'client_token': 'not-a-uuid'}
        r = self.cc.post(BASE, payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_queue_status_and_flush_gate(self):
        r = self.cc.get(BASE + 'queue-status/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('queued', r.data)
        # flush is blocked while the writer is disabled (default in tests)
        r = self.cc.post(BASE + 'flush/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT, r.data)

    def test_full_flow_create_ready_push_dryrun(self):
        # create
        r = self.cc.post(BASE, _payload(self.branch.id), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        oid = r.data['id']
        self.assertEqual(len(r.data['lines']), 2)
        # ready (compute) with a balanced cash tender (net = 275.40)
        r = self.cc.post(f'{BASE}{oid}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '275.40'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['doc_value'], '275.40')
        self.assertEqual(r.data['status'], 'ready')
        # push (dry-run) — returns the plan, writes nothing
        r = self.cc.post(f'{BASE}{oid}/push/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['mode'], 'dry_run')
        self.assertFalse(r.data['wrote_to_softech'])
        self.assertIn('header', r.data['plan'])

    def test_ready_rejects_unbalanced_payment(self):
        r = self.cc.post(BASE, _payload(self.branch.id), format='json')
        oid = r.data['id']
        r = self.cc.post(f'{BASE}{oid}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '100.00'}]}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_viewer_can_create_but_not_push(self):
        # CanOperatePosOrders allows any active staff to create
        r = self.viewer.post(BASE, _payload(self.branch.id), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        oid = r.data['id']
        # CanPushPosOrders blocks a non-operator role from pushing
        r = self.viewer.post(f'{BASE}{oid}/push/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_unsettled(self):
        r = self.cc.post(BASE, _payload(self.branch.id), format='json')
        oid = r.data['id']
        r = self.cc.post(f'{BASE}{oid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(SoftechSalesOrder.objects.get(pk=oid).status, 'cancelled')


class CustomerDirectoryTests(TestCase):
    def setUp(self):
        _, _, self.cc = make_call_center('cc_dir')

    def test_customer_types_endpoint(self):
        r = self.cc.get(BASE + 'customer-types/')
        self.assertEqual(r.status_code, 200, r.data)
        keys = {t['key'] for t in r.data['types']}
        self.assertTrue({'cash', 'delivery', 'contract', 'insurance', 'employee'} <= keys)

    def test_entities_requires_branch_and_type(self):
        r = self.cc.get(BASE + 'customer-entities/')
        self.assertEqual(r.status_code, 400)
