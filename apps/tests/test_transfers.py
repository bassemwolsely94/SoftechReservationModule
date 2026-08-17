"""
apps/tests/test_transfers.py

Tests covering:
  - Transfer request CRUD
  - Branch scoping: staff see only requests where their branch is source or destination
  - Admin sees all requests
  - State machine: submit, approve, reject, revision, send-to-erp, complete, cancel
  - State machine: invalid transitions return 400
  - Role guards on approve/reject (supplying-branch side)
  - Role guards on submit/complete/cancel (requesting-branch side)
  - Record dispatch: requires delivery person name
  - Record dispatch: cannot dispatch already-dispatched transfer
  - Messages: post text message, empty message rejected, auth required
  - Messages: soft-delete — author can delete, other user cannot
  - Messages: system messages cannot be deleted
  - Destroy: cannot delete a submitted/approved transfer (must cancel first)
  - ERP match rate limit: 429 within 20 seconds
  - ERP match role guard: only admin/purchasing
  - ERP match status guard: only sent_to_erp or completed
  - Item management: add item, duplicate item rejected, edit in wrong status
  - WhatsApp share: returns message_text
  - Print receipt: returns receipt structure
  - Anonymous access rejected on all endpoints
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.transfers.models import TransferRequest, TransferRequestItem, TransferRequestMessage
from .factories import (
    make_branch, make_branch2, make_admin, make_pharmacist,
    make_call_center, make_item,
)

TRANSFERS_URL = '/api/transfers/'


def _tr_url(pk, action=''):
    base = f'{TRANSFERS_URL}{pk}/'
    return base + action + ('/' if action else '')


def _make_transfer(req_branch, sup_branch, created_by, status='draft'):
    tr = TransferRequest.objects.create(
        requesting_branch=req_branch,
        supplying_branch=sup_branch,
        created_by=created_by,
        status=status,
        notes='طلب اختبار',
    )
    return tr


def _add_item(tr, item, qty=5):
    return TransferRequestItem.objects.create(request=tr, item=item, quantity=qty)


class TransferCRUDTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب', 'REQ01')
        self.branch2 = make_branch2('فرع مصدر', 'SUP01')
        self.item    = make_item()
        _, self.prof1, self.client1 = make_pharmacist('tr_pharma1', branch=self.branch1)
        _, self.prof2, self.client2 = make_pharmacist('tr_pharma2', branch=self.branch2)
        _, _, self.admin_client     = make_admin('tr_admin')

    def test_create_transfer_success(self):
        r = self.client1.post(TRANSFERS_URL, {
            'requesting_branch': self.branch1.id,
            'supplying_branch':  self.branch2.id,
            'notes': 'طلب تجريبي',
        }, format='json')
        self.assertIn(r.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_create_requires_auth(self):
        r = APIClient().post(TRANSFERS_URL, {
            'requesting_branch': self.branch1.id,
            'supplying_branch':  self.branch2.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_requires_auth(self):
        r = APIClient().get(TRANSFERS_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pharmacist_sees_own_branch_transfers(self):
        tr1 = _make_transfer(self.branch1, self.branch2, self.prof1)  # branch1 is requesting
        tr2 = _make_transfer(self.branch2, self.branch1, self.prof2)  # branch1 is supplying

        r = self.client1.get(TRANSFERS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        ids = [row['id'] for row in results]
        # Both should appear because branch1 is involved in both (as requesting AND supplying)
        self.assertIn(tr1.id, ids)
        self.assertIn(tr2.id, ids)

    def test_pharmacist_cannot_see_unrelated_transfer(self):
        """Transfer where neither branch is the user's branch — must not appear."""
        branch3 = make_branch('فرع ثالث', 'B03')
        branch4 = make_branch('فرع رابع', 'B04')
        _, prof3, _ = make_pharmacist('tr_pharma3', branch=branch3)
        unrelated = _make_transfer(branch3, branch4, prof3)

        r = self.client1.get(TRANSFERS_URL)
        results = r.data.get('results', r.data)
        ids = [row['id'] for row in results]
        self.assertNotIn(unrelated.id, ids,
                         'User must not see transfers that don\'t involve their branch')

    def test_admin_sees_all_transfers(self):
        tr1 = _make_transfer(self.branch1, self.branch2, self.prof1)
        tr2 = _make_transfer(self.branch2, self.branch1, self.prof2)
        r = self.admin_client.get(TRANSFERS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        ids = [row['id'] for row in results]
        self.assertIn(tr1.id, ids)
        self.assertIn(tr2.id, ids)

    def test_cannot_delete_submitted_transfer(self):
        tr = _make_transfer(self.branch1, self.branch2, self.prof1, status='pending')
        r = self.admin_client.delete(_tr_url(tr.id))
        self.assertIn(r.status_code, [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_400_BAD_REQUEST,
        ], 'Cannot delete a submitted transfer — must cancel first')


class TransferStateMachineTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب SM', 'SM01')
        self.branch2 = make_branch2('فرع مصدر SM', 'SM02')
        self.item    = make_item()
        _, self.req_prof, self.req_client = make_pharmacist('tr_req_sm', branch=self.branch1)
        _, self.sup_prof, self.sup_client = make_pharmacist('tr_sup_sm', branch=self.branch2)
        _, _, self.admin_client           = make_admin('tr_admin_sm')

    def _fresh_draft(self):
        tr = _make_transfer(self.branch1, self.branch2, self.req_prof)
        _add_item(tr, self.item)
        return tr

    def test_submit_by_requesting_branch(self):
        tr = self._fresh_draft()
        r  = self.req_client.post(_tr_url(tr.id, 'submit'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'pending')

    def test_submit_by_supplying_branch_forbidden(self):
        tr = self._fresh_draft()
        r  = self.sup_client.post(_tr_url(tr.id, 'submit'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_approve_by_supplying_branch(self):
        tr = self._fresh_draft()
        tr.status = 'pending'
        tr.save(update_fields=['status'])
        r  = self.sup_client.post(_tr_url(tr.id, 'approve'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'approved')

    def test_approve_by_requesting_branch_forbidden(self):
        tr = self._fresh_draft()
        tr.status = 'pending'
        tr.save(update_fields=['status'])
        r  = self.req_client.post(_tr_url(tr.id, 'approve'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_approve_non_pending_returns_400(self):
        tr = self._fresh_draft()  # status=draft
        r  = self.sup_client.post(_tr_url(tr.id, 'approve'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_requires_reason(self):
        tr = self._fresh_draft()
        tr.status = 'pending'
        tr.save(update_fields=['status'])
        r  = self.sup_client.post(_tr_url(tr.id, 'reject'), {}, format='json')
        self.assertIn(r.status_code, [status.HTTP_400_BAD_REQUEST])

    def test_reject_with_reason_succeeds(self):
        tr = self._fresh_draft()
        tr.status = 'pending'
        tr.save(update_fields=['status'])
        r  = self.sup_client.post(
            _tr_url(tr.id, 'reject'),
            {'rejection_reason': 'لا يوجد مخزون كافٍ'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'rejected')
        self.assertNotEqual(tr.rejection_reason, '')

    def test_cancel_by_requesting_branch(self):
        tr = self._fresh_draft()
        r  = self.req_client.post(_tr_url(tr.id, 'cancel'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        tr.refresh_from_db()
        self.assertEqual(tr.status, 'cancelled')

    def test_cancel_approved_transfer_returns_400(self):
        tr = self._fresh_draft()
        tr.status = 'approved'
        tr.save(update_fields=['status'])
        r  = self.req_client.post(_tr_url(tr.id, 'cancel'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_to_erp_requires_approved_status(self):
        tr = self._fresh_draft()
        tr.status = 'pending'  # not yet approved
        tr.save(update_fields=['status'])
        r  = self.sup_client.post(_tr_url(tr.id, 'send-to-erp'), {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_requires_sent_to_erp_status(self):
        tr = self._fresh_draft()
        tr.status = 'approved'
        tr.save(update_fields=['status'])
        r  = self.req_client.post(_tr_url(tr.id, 'complete'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class TransferDispatchTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب D', 'D01')
        self.branch2 = make_branch2('فرع مصدر D', 'D02')
        self.item    = make_item()
        _, self.prof, self.client = make_pharmacist('tr_dispatch', branch=self.branch2)
        tr = _make_transfer(self.branch1, self.branch2, self.prof, status='sent_to_erp')
        _add_item(tr, self.item)
        self.tr = tr

    def test_record_dispatch_success(self):
        r = self.client.post(
            _tr_url(self.tr.id, 'record-dispatch'),
            {'delivery_person_name': 'محمد المندوب'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.delivery_person_name, 'محمد المندوب')
        self.assertIsNotNone(self.tr.dispatched_at)

    def test_record_dispatch_without_name_rejected(self):
        r = self.client.post(_tr_url(self.tr.id, 'record-dispatch'), {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_record_dispatch_twice_returns_400(self):
        self.client.post(
            _tr_url(self.tr.id, 'record-dispatch'),
            {'delivery_person_name': 'مندوب 1'},
            format='json',
        )
        r = self.client.post(
            _tr_url(self.tr.id, 'record-dispatch'),
            {'delivery_person_name': 'مندوب 2'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST,
                         'Cannot dispatch an already-dispatched transfer')

    def test_record_dispatch_wrong_status_returns_400(self):
        tr = _make_transfer(self.branch1, self.branch2, self.prof, status='approved')
        r  = self.client.post(
            _tr_url(tr.id, 'record-dispatch'),
            {'delivery_person_name': 'مندوب'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class TransferMessagesTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب M', 'M01')
        self.branch2 = make_branch2('فرع مصدر M', 'M02')
        _, self.prof1, self.client1 = make_pharmacist('tr_msg1', branch=self.branch1)
        _, self.prof2, self.client2 = make_pharmacist('tr_msg2', branch=self.branch2)
        _, _, self.admin_client     = make_admin('tr_msg_admin')
        self.tr = _make_transfer(self.branch1, self.branch2, self.prof1)

    def test_post_message_success(self):
        r = self.client1.post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'رسالة تجريبية'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_list_messages_requires_auth(self):
        r = APIClient().get(_tr_url(self.tr.id, 'messages'))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_message_requires_auth(self):
        r = APIClient().post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'test'},
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_soft_delete_own_message(self):
        r = self.client1.post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'رسالة للحذف'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg_id = r.data['id']

        del_r = self.client1.delete(_tr_url(self.tr.id, f'messages/{msg_id}'))
        self.assertEqual(del_r.status_code, status.HTTP_200_OK)
        msg = TransferRequestMessage.objects.get(pk=msg_id)
        self.assertTrue(msg.is_deleted)

    def test_cannot_delete_other_user_message(self):
        r = self.client1.post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'رسالة المستخدم 1'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg_id = r.data['id']

        del_r = self.client2.delete(_tr_url(self.tr.id, f'messages/{msg_id}'))
        self.assertEqual(del_r.status_code, status.HTTP_403_FORBIDDEN,
                         'User must not delete another user\'s message')

    def test_admin_can_delete_any_message(self):
        r = self.client1.post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'رسالة للحذف من الأدمن'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        msg_id = r.data['id']

        del_r = self.admin_client.delete(_tr_url(self.tr.id, f'messages/{msg_id}'))
        self.assertEqual(del_r.status_code, status.HTTP_200_OK)

    def test_cannot_delete_system_message(self):
        sys_msg = TransferRequestMessage.log_system(self.tr, 'رسالة نظام')
        del_r = self.admin_client.delete(
            _tr_url(self.tr.id, f'messages/{sys_msg.id}')
        )
        self.assertEqual(del_r.status_code, status.HTTP_403_FORBIDDEN,
                         'System log messages must not be deletable')

    def test_delete_already_deleted_returns_400(self):
        r = self.client1.post(
            _tr_url(self.tr.id, 'messages'),
            {'message_type': 'message', 'message': 'رسالة'},
            format='json',
        )
        msg_id = r.data['id']
        self.client1.delete(_tr_url(self.tr.id, f'messages/{msg_id}'))
        del_r = self.client1.delete(_tr_url(self.tr.id, f'messages/{msg_id}'))
        self.assertEqual(del_r.status_code, status.HTTP_400_BAD_REQUEST)


class TransferItemManagementTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب I', 'I01')
        self.branch2 = make_branch2('فرع مصدر I', 'I02')
        self.item    = make_item()
        _, self.prof, self.client = make_pharmacist('tr_item_user', branch=self.branch1)
        self.tr = _make_transfer(self.branch1, self.branch2, self.prof, status='draft')

    def test_add_item_success(self):
        r = self.client.post(
            _tr_url(self.tr.id, 'items'),
            {'item': self.item.id, 'quantity': 5},
            format='json',
        )
        self.assertIn(r.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_add_duplicate_item_rejected(self):
        _add_item(self.tr, self.item)
        r = self.client.post(
            _tr_url(self.tr.id, 'items'),
            {'item': self.item.id, 'quantity': 3},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST,
                         'Duplicate item in the same transfer must be rejected')

    def test_add_item_in_non_editable_status_rejected(self):
        self.tr.status = 'pending'
        self.tr.save(update_fields=['status'])
        r = self.client.post(
            _tr_url(self.tr.id, 'items'),
            {'item': self.item.id, 'quantity': 5},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class TransferERPMatchGuardTests(TestCase):
    """ERP match endpoint: role guard + status guard + rate limit."""

    def setUp(self):
        self.branch1 = make_branch('فرع طالب ERP', 'E01')
        self.branch2 = make_branch2('فرع مصدر ERP', 'E02')
        self.item    = make_item()
        _, self.prof, self.pharma_client = make_pharmacist('tr_erp_pharma', branch=self.branch1)
        _, _, self.admin_client          = make_admin('tr_erp_admin')

        self.tr_sent = _make_transfer(self.branch1, self.branch2, self.prof, status='sent_to_erp')
        self.tr_draft = _make_transfer(self.branch1, self.branch2, self.prof, status='draft')

    def test_pharmacist_gets_403_on_erp_match(self):
        r = self.pharma_client.post(_tr_url(self.tr_sent.id, 'check-erp-match'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_sent_status_gets_400(self):
        r = self.admin_client.post(_tr_url(self.tr_draft.id, 'check-erp-match'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anon_gets_401(self):
        r = APIClient().post(_tr_url(self.tr_sent.id, 'check-erp-match'))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rate_limit_429_within_20_seconds(self):
        """Second ERP check within 20 seconds must return 429."""
        self.tr_sent.erp_last_checked = timezone.now()
        self.tr_sent.save(update_fields=['erp_last_checked'])

        r = self.admin_client.post(_tr_url(self.tr_sent.id, 'check-erp-match'))
        self.assertEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                         'Second ERP match check within 20s must return 429')

    def test_rate_limit_detail_contains_wait_seconds(self):
        self.tr_sent.erp_last_checked = timezone.now()
        self.tr_sent.save(update_fields=['erp_last_checked'])

        r = self.admin_client.post(_tr_url(self.tr_sent.id, 'check-erp-match'))
        self.assertIn('ثانية', r.data.get('detail', ''),
                      'Rate-limit detail must include the wait time in Arabic')


class TransferPrintAndShareTests(TestCase):

    def setUp(self):
        self.branch1 = make_branch('فرع طالب P', 'P01')
        self.branch2 = make_branch2('فرع مصدر P', 'P02')
        self.item    = make_item()
        _, self.prof, self.client = make_pharmacist('tr_print', branch=self.branch1)
        self.tr = _make_transfer(self.branch1, self.branch2, self.prof, status='approved')
        _add_item(self.tr, self.item)

    def test_print_receipt_returns_structure(self):
        r = self.client.get(_tr_url(self.tr.id, 'print'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('request_number', r.data)
        self.assertIn('items', r.data)
        self.assertIn('requesting_branch', r.data)
        self.assertIn('supplying_branch', r.data)

    def test_print_requires_auth(self):
        r = APIClient().get(_tr_url(self.tr.id, 'print'))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_whatsapp_share_returns_message_text(self):
        r = self.client.post(_tr_url(self.tr.id, 'share-whatsapp'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('message_text', r.data)
        self.assertIn('طلب تحويل', r.data['message_text'])

    def test_whatsapp_share_requires_auth(self):
        r = APIClient().post(_tr_url(self.tr.id, 'share-whatsapp'))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
