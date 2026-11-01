"""
Confirm / audit gaps found while writing the button hints (PR 24, 2026-11-01):
customer-note delete, disposal status rules, reservation cancel reason, transfer-suggestion
transitions, delivery assign before «ready», follow-up WhatsApp preview, call-item quantity.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from .factories import make_admin, make_branch, make_branch2, make_customer, make_item, make_user


class CustomerNoteDeleteTests(TestCase):
    def setUp(self):
        from apps.customers.models import CustomerNote
        self.branch = make_branch()
        self.customer = make_customer()
        _, self.author, self.author_c = make_user('note_author', role='call_center', access_all=True)
        _, _, self.other_c = make_user('note_other', role='call_center', access_all=True)
        _, _, self.sup_c = make_user('note_sup', role='supervisor', access_all=True)
        self.note = CustomerNote.objects.create(customer=self.customer, note='يفضّل التواصل مساءً',
                                                created_by=self.author)

    def _url(self, note):
        return f'/api/customers/{self.customer.pk}/notes/{note.pk}/'

    def test_someone_else_cannot_delete(self):
        r = self.other_c.delete(self._url(self.note))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(type(self.note).objects.filter(pk=self.note.pk).exists())

    def test_author_deletes_and_it_is_audited(self):
        r = self.author_c.delete(self._url(self.note))
        self.assertEqual(r.status_code, 204, r.content)
        row = AuditLog.objects.get(action='customer_note_deleted')
        self.assertEqual(row.user_id, self.author.pk)
        self.assertEqual(row.old_data['note'], 'يفضّل التواصل مساءً')

    def test_supervisor_deletes_anyones(self):
        self.assertEqual(self.sup_c.delete(self._url(self.note)).status_code, 204)


class DisposalStatusTests(TestCase):
    def setUp(self):
        from apps.batches.models import ExpiryDisposalRecord
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        module_access.clear_cache()
        for role in ('pharmacist', 'supervisor'):
            RoleModuleAccess.objects.create(role=role, module='catalog', action='view')
        self.addCleanup(module_access.clear_cache)
        branch = make_branch()
        _, self.owner, self.owner_c = make_user('disp_owner', role='pharmacist', branch=branch)
        _, _, self.other_c = make_user('disp_other', role='pharmacist', branch=branch)
        _, _, self.mgr_c = make_user('disp_mgr', role='supervisor', access_all=True)
        self.Rec = ExpiryDisposalRecord
        self.rec = ExpiryDisposalRecord.objects.create(item_code='A', branch_code='100', qty=Decimal('2'),
                                                       decision='dispose', created_by=self.owner)

    def _set(self, client, status, rec=None):
        rec = rec or self.rec
        return client.post(f'/api/batches/stock-expiry/disposal/{rec.pk}/status/', {'status': status},
                           format='json')

    def test_creator_cancels_own_draft_audited(self):
        r = self._set(self.owner_c, 'cancelled')
        self.assertEqual(r.status_code, 200, r.content)
        row = AuditLog.objects.get(action='disposal_status_changed')
        self.assertEqual(row.changes, {'status': ['draft', 'cancelled']})

    def test_other_staff_cannot_cancel(self):
        self.assertEqual(self._set(self.other_c, 'cancelled').status_code, 403)

    def test_creator_cannot_cancel_once_approved(self):
        self.Rec.objects.filter(pk=self.rec.pk).update(status='approved')
        self.assertEqual(self._set(self.owner_c, 'cancelled').status_code, 403)
        self.assertEqual(self._set(self.mgr_c, 'cancelled').status_code, 200)

    def test_done_is_final(self):
        self.Rec.objects.filter(pk=self.rec.pk).update(status='done')
        self.assertEqual(self._set(self.mgr_c, 'cancelled').status_code, 400)
        self.assertEqual(self._set(self.mgr_c, 'draft').status_code, 400)

    def test_reopen_is_manager_only(self):
        self.Rec.objects.filter(pk=self.rec.pk).update(status='cancelled')
        self.assertEqual(self._set(self.owner_c, 'draft').status_code, 403)
        self.assertEqual(self._set(self.mgr_c, 'draft').status_code, 200)


class ReservationCancelReasonTests(TestCase):
    def setUp(self):
        from apps.reservations.models import Reservation
        self.branch = make_branch()
        _, self.profile, self.client_ = make_admin('res_cancel_admin')
        self.res = Reservation.objects.create(item=make_item(), branch=self.branch, quantity_requested=1,
                                              contact_name='عميل', contact_phone='01033333333',
                                              created_by=self.profile)

    def _cancel(self, note):
        return self.client_.post(f'/api/reservations/{self.res.pk}/change-status/',
                                 {'status': 'cancelled', 'note': note}, format='json')

    def test_cancel_needs_a_reason(self):
        self.assertEqual(self._cancel('').status_code, 400)
        self.assertEqual(self._cancel('   ').status_code, 400)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, 'pending')

    def test_cancel_with_reason(self):
        r = self._cancel('سبب الإلغاء: حجز مكرر')
        self.assertEqual(r.status_code, 200, r.content)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, 'cancelled')
        self.assertEqual(self.res.status_logs.last().note, 'سبب الإلغاء: حجز مكرر')

    def test_bulk_cancel_needs_a_reason(self):
        r = self.client_.post('/api/reservations/bulk/', {'action': 'change_status', 'ids': [self.res.pk],
                                                          'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, 'pending')

    def test_other_changes_need_no_note(self):
        r = self.client_.post(f'/api/reservations/{self.res.pk}/change-status/', {'status': 'available'},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)


class TransferRecommendationStatusTests(TestCase):
    def setUp(self):
        from apps.purchasing.models import DemandCalculationRun, TransferRecommendation, TransferRecommendationRun
        run = DemandCalculationRun.objects.create(status='success', calc_date=timezone.localdate())
        trr = TransferRecommendationRun.objects.create(demand_run=run, status='success')
        self.TR = TransferRecommendation
        self.common = dict(run=trr, item=make_item(), from_branch=make_branch(), to_branch=make_branch2(), quantity=1)
        _, self.profile, self.client_ = make_admin('trec_admin')

    def _set(self, rec, status):
        return self.client_.patch(f'/api/purchasing/transfer-recs/{rec.pk}/status/', {'status': status},
                                  format='json')

    def test_rejected_cannot_become_executed(self):
        rec = self.TR.objects.create(status='rejected', **self.common)
        self.assertEqual(self._set(rec, 'executed').status_code, 400)
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'rejected')

    def test_pending_cannot_skip_to_executed(self):
        rec = self.TR.objects.create(status='pending', **self.common)
        self.assertEqual(self._set(rec, 'executed').status_code, 400)

    def test_approved_to_executed_is_audited(self):
        rec = self.TR.objects.create(status='approved', **self.common)
        self.assertEqual(self._set(rec, 'executed').status_code, 200)
        row = AuditLog.objects.get(action='transfer_rec_status_changed')
        self.assertEqual(row.changes, {'status': ['approved', 'executed']})


class DeliveryAssignBeforeReadyTests(TestCase):
    def setUp(self):
        from apps.delivery.models import DeliveryDriver
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        module_access.clear_cache()
        for a in ('view', 'assign'):
            RoleModuleAccess.objects.create(role='call_center', module='delivery', action=a)
        self.addCleanup(module_access.clear_cache)
        self.branch = make_branch()
        self.client_ = make_user('del_cc', role='call_center', access_all=True)[2]
        self.driver = DeliveryDriver.objects.create(full_name='سائق', mobile='0100000009')

    def test_assign_from_created_logs_ready_first(self):
        from apps.delivery.models import DeliveryOrder
        o = DeliveryOrder.objects.create(branch=self.branch, customer_name='عميل',
                                         status=DeliveryOrder.STATUS_CREATED)
        r = self.client_.post(f'/api/delivery/{o.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.status, DeliveryOrder.STATUS_ASSIGNED)
        steps = list(o.status_logs.order_by('pk').values_list('from_status', 'to_status', 'source'))
        self.assertEqual(steps, [('created', 'ready', 'system'), ('ready', 'assigned', 'manual')])

    def test_assign_still_refused_after_dispatch(self):
        from apps.delivery.models import DeliveryOrder
        o = DeliveryOrder.objects.create(branch=self.branch, customer_name='عميل',
                                         status=DeliveryOrder.STATUS_OUT)
        r = self.client_.post(f'/api/delivery/{o.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_accepts_several_statuses(self):
        from apps.delivery.models import DeliveryOrder
        for st in ('created', 'ready', 'delivered'):
            DeliveryOrder.objects.create(branch=self.branch, customer_name=st, status=st)
        r = self.client_.get('/api/delivery/', {'status': 'created,ready'})
        rows = r.data.get('results', r.data)
        self.assertEqual(sorted(o['status'] for o in rows), ['created', 'ready'])


class FollowupWhatsappPreviewTests(TestCase):
    def setUp(self):
        from apps.followups.models import FollowUpTask
        branch = make_branch()
        self.cust = make_customer()
        _, _, self.client_ = make_admin('fu_wa_admin')
        self.task = FollowUpTask.objects.create(customer=self.cust, item=make_item(), branch=branch,
                                                task_type='refill', status='pending',
                                                due_date=timezone.localdate())

    def _post(self, **extra):
        return self.client_.post('/api/followups/tasks/multi-whatsapp/', {'task_ids': [self.task.pk], **extra},
                                 format='json')

    def test_preview_changes_nothing(self):
        r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'pending')

    def test_opening_whatsapp_marks_called(self):
        self.assertEqual(self._post(mark_called=True).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'called')


class CallItemQuantityTests(TestCase):
    def setUp(self):
        from apps.callcenter.models import CallItem, CallLog
        self.branch = make_branch()
        _, _, self.client_ = make_admin('call_qty_admin')
        customer = make_customer()
        self.call = CallLog.objects.create(phone_number=customer.phone, customer=customer, branch=self.branch)
        self.ci = CallItem.objects.create(call_log=self.call, item=make_item(), quantity=1)

    def _patch(self, qty, ci=None):
        ci = ci or self.ci
        return self.client_.patch(f'/api/callcenter/calls/{self.call.pk}/items/{ci.pk}/', {'quantity': qty},
                                  format='json')

    def test_quantity_is_stored(self):
        r = self._patch('3')
        self.assertEqual(r.status_code, 200, r.content)
        self.ci.refresh_from_db()
        self.assertEqual(self.ci.quantity, Decimal('3.00'))

    def test_bad_quantity_refused(self):
        for bad in ('0', '-2', 'abc', None):
            self.assertEqual(self._patch(bad).status_code, 400, bad)

    def test_converted_item_is_locked(self):
        type(self.ci).objects.filter(pk=self.ci.pk).update(converted_to='reservation')
        self.assertEqual(self._patch('5').status_code, 400)
