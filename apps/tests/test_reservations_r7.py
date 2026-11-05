"""
R7 — apps/reservations per-app tests.

Route groups (apps/reservations/urls.py):
  ReservationViewSet (router '')           CRUD, change-status, check-erp-match, activities / log /
                                           delete-activity, downpayments, print, share-whatsapp,
                                           dashboard, images, lines, merge, bulk, analytics,
                                           customer-history
  reservation_activity (<id>/activity/)    ActivityLog GET / POST

Permission: the code role matrix (seed_permissions) answers through the view's own check.
Business rules: the status transition graph, merge, ERP match qty tolerance, auto-expire lives in
apps/sync (tested in test_sync_r7).
"""
import datetime
import io
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.reservations.activity_models import ActivityLog
from apps.reservations.erp_matcher import (
    ReservationERPMatcher, _build_receipt_lines, _not_found, _to_float, apply_match_result,
)
from apps.reservations.models import (
    Reservation, ReservationActivity, ReservationDownpayment, ReservationImage, ReservationLine,
    ReservationStatusLog,
)
from apps.reservations.views import ReservationViewSet
from apps.tests.factories import (
    make_branch, make_branch2, make_customer, make_item, make_user,
)
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

URL = '/api/reservations/'


def _u(pk, action=''):
    return f'{URL}{pk}/' + (f'{action}/' if action else '')


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (255, 0, 0)).save(buf, format='PNG')
    return buf.getvalue()


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch('فرع R7', 'B01')
        self.branch2 = make_branch2('فرع R7 ب', 'B02')
        self.item = make_item('باراسيتامول R7', 'R7I1')
        self.item2 = make_item('أموكسيسيلين R7', 'R7I2')
        self.customer = make_customer('عميل R7', '01011112222')
        _, self.admin, self.admin_c = make_user('r7res_admin', role='admin', access_all=True)
        _, self.pharm, self.pharm_c = make_user('r7res_pharm', role='pharmacist', branch=self.branch)
        _, self.sales, self.sales_c = make_user('r7res_sales', role='salesperson', branch=self.branch)

    def tearDown(self):
        module_access.clear_cache()

    def res(self, **kw):
        base = dict(item=self.item, branch=self.branch, quantity_requested=Decimal('2'),
                    contact_name='زبون', contact_phone='01000000001', created_by=self.pharm)
        base.update(kw)
        return Reservation.objects.create(**base)


# ── Permission (role matrix) ──────────────────────────────────────────────────

class ReservationPermissionTests(_Base):

    def _bearer(self, role):
        user, _, _ = make_user(f'r7res_b_{role}', role=role, branch=self.branch)
        return bearer_client(user)

    def test_delivery_role_cannot_list_reservations(self):
        self.res()
        r = self._bearer('delivery').get(URL)
        self.assertEqual(r.status_code, 403)

    def test_viewer_can_read_but_not_create(self):
        self.res()
        c = self._bearer('viewer')
        self.assertEqual(c.get(URL).status_code, 200)
        r = c.post(URL, {'item': self.item.id, 'branch': self.branch.id, 'quantity_requested': 1,
                         'contact_name': 'x', 'contact_phone': '01000000009'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_delivery_role_cannot_open_analytics(self):
        r = self._bearer('delivery').get(_u('analytics'))
        self.assertEqual(r.status_code, 403)

    def test_activity_view_refuses_delivery(self):
        res = self.res()
        r = self._bearer('delivery').get(f'{URL}{res.pk}/activity/')
        self.assertEqual(r.status_code, 403)


# ── CRUD + duplicate detection ────────────────────────────────────────────────

class ReservationCrudTests(_Base):

    def _payload(self, **kw):
        p = {'item': self.item.id, 'branch': self.branch.id, 'customer': self.customer.id,
             'quantity_requested': 1, 'contact_name': 'عميل', 'contact_phone': '01011112222',
             'priority': 'normal', 'channel': 'cash_sales', 'fulfillment_method': 'pickup'}
        p.update(kw)
        return p

    def test_duplicate_open_reservation_is_409_until_forced(self):
        first = self.res(customer=self.customer)
        r = self.pharm_c.post(URL, self._payload(), format='json')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data['duplicate'])
        self.assertEqual([d['id'] for d in r.data['duplicates']], [first.id])
        r2 = self.pharm_c.post(URL + '?force=true', self._payload(), format='json')
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(Reservation.objects.filter(customer=self.customer).count(), 2)

    def test_create_walk_in_makes_guest_customer_and_logs(self):
        p = self._payload(contact_phone='01055554444', contact_name='ضيف')
        p.pop('customer')
        r = self.pharm_c.post(URL, p, format='json')
        self.assertEqual(r.status_code, 201)
        res = Reservation.objects.get(pk=r.data['id'])
        self.assertTrue(res.customer.is_guest)
        self.assertEqual(res.customer.phone, '01055554444')
        log = ReservationStatusLog.objects.get(reservation=res)
        self.assertEqual((log.old_status, log.new_status), ('', 'pending'))
        self.assertTrue(res.activities.filter(activity_type='status_changed').exists())

    def test_list_filters_and_retrieve(self):
        a = self.res(status='pending')
        b = self.res(status='available', item=self.item2)
        r = self.admin_c.get(URL, {'status__in': 'available,confirmed'})
        self.assertEqual(r.status_code, 200)
        ids = [row['id'] for row in r.data.get('results', r.data)]
        self.assertEqual(ids, [b.id])
        r = self.admin_c.get(_u(a.id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['id'], a.id)

    def test_branch_change_on_update_is_logged(self):
        res = self.res()
        r = self.admin_c.patch(_u(res.id), {'branch': self.branch2.id}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        res.refresh_from_db()
        self.assertEqual(res.branch, self.branch2)
        self.assertTrue(res.activities.filter(message__contains='تم تغيير الفرع').exists())

    def test_admin_can_delete(self):
        res = self.res()
        r = self.admin_c.delete(_u(res.id))
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Reservation.objects.filter(pk=res.pk).exists())


# ── Status transitions (business rule) ────────────────────────────────────────

class StatusTransitionRuleTests(_Base):

    def test_transition_graph_exact(self):
        self.assertEqual(ReservationViewSet._VALID_TRANSITIONS, {
            'pending':   {'available', 'cancelled', 'expired'},
            'available': {'contacted', 'confirmed', 'cancelled', 'expired'},
            'contacted': {'confirmed', 'available', 'cancelled', 'expired'},
            'confirmed': {'fulfilled', 'cancelled', 'expired'},
            'expired':   {'pending'},
            'fulfilled': set(),
            'cancelled': set(),
        })

    def test_full_happy_path_logs_every_step(self):
        res = self.res()
        for new in ('available', 'contacted', 'confirmed', 'fulfilled'):
            r = self.pharm_c.post(_u(res.id, 'change-status'), {'status': new}, format='json')
            self.assertEqual(r.status_code, 200, (new, r.data))
        res.refresh_from_db()
        self.assertEqual(res.status, 'fulfilled')
        chain = list(res.status_logs.order_by('changed_at', 'id').values_list('old_status', 'new_status'))
        self.assertEqual(chain, [('pending', 'available'), ('available', 'contacted'),
                                 ('contacted', 'confirmed'), ('confirmed', 'fulfilled')])
        self.assertEqual(res.activities.filter(activity_type='item_dispensed').count(), 1)

    def test_cancel_needs_a_reason(self):
        res = self.res()
        r = self.pharm_c.post(_u(res.id, 'change-status'), {'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 400)
        res.refresh_from_db()
        self.assertEqual(res.status, 'pending')

    def test_terminal_state_refused_with_allowed_list_for_branch_role(self):
        res = self.res(status='fulfilled')
        r = self.pharm_c.post(_u(res.id, 'change-status'),
                              {'status': 'cancelled', 'note': 'خطأ'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['allowed_transitions'], [])

    def test_admin_escape_hatch_cancels_terminal(self):
        res = self.res(status='fulfilled')
        r = self.admin_c.post(_u(res.id, 'change-status'),
                              {'status': 'cancelled', 'note': 'تصحيح'}, format='json')
        self.assertEqual(r.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.status, 'cancelled')

    def test_expired_reopens_to_pending_only(self):
        res = self.res(status='expired')
        r = self.pharm_c.post(_u(res.id, 'change-status'), {'status': 'available'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['allowed_transitions'], ['pending'])
        r = self.pharm_c.post(_u(res.id, 'change-status'), {'status': 'pending'}, format='json')
        self.assertEqual(r.status_code, 200)


# ── ERP match ─────────────────────────────────────────────────────────────────

class ErpMatchTests(_Base):

    HEADER = ('9001', '115', 'B01', datetime.datetime(2026, 11, 1, 10, 0), '45.50', 'U7', '100', 'PIC9')

    def _fetch(self, lines):
        return mock.patch.object(ReservationERPMatcher, '_fetch_sybase',
                                 return_value=(self.HEADER, lines, True, {'user_id': 'ahmed',
                                                                          'user_name': 'أحمد'}, None))

    def test_qty_within_20_percent_is_matched(self):
        res = self.res(quantity_requested=Decimal('10'), erp_reference='9001')
        with self._fetch([('R7I1', 12, 30, '100', None)]):
            result = ReservationERPMatcher(res).run()
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_items'][0]['match_level'], 'full')
        self.assertEqual(result['doc_value'], 45.5)
        self.assertEqual(result['doc_date'], datetime.date(2026, 11, 1))
        self.assertEqual(result['phcode'], 'PIC9')
        self.assertEqual(result['user_name'], 'أحمد')

    def test_qty_beyond_20_percent_is_partial(self):
        res = self.res(quantity_requested=Decimal('10'), erp_reference='9001')
        with self._fetch([('R7I1', 13, 30, '100', None)]):
            result = ReservationERPMatcher(res).run()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['matched_items'][0]['erp_qty'], 13.0)

    def test_item_missing_from_lines_is_partial_not_found_level(self):
        res = self.res(quantity_requested=Decimal('1'), erp_reference='9001')
        with self._fetch([('OTHER', 1, 5, '100', None)]):
            result = ReservationERPMatcher(res).run()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['matched_items'][0]['match_level'], 'not_found')

    def test_manual_item_header_is_enough(self):
        res = self.res(item=None, manual_item_name='صنف يدوي', erp_reference='9001')
        with self._fetch([]):
            result = ReservationERPMatcher(res).run()
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_items'], [])

    def test_branch_without_softech_id_is_not_found(self):
        b = make_branch('بلا كود', 'B77')
        b.softech_branch_id = ''
        b.save()
        res = self.res(branch=b)
        self.assertEqual(ReservationERPMatcher(res).run()['status'], 'not_found')

    def test_receipt_lines_merge_duplicate_codes(self):
        lines = _build_receipt_lines([('R7I1', 1, 10, '100 ', None), ('R7I1', 2.5, 10, '100', None),
                                      ('', 1, 1, '', None), ('ZZZ', '3', 'x', None, None)])
        self.assertEqual(lines, [
            {'itemcode': 'R7I1', 'itemname': 'باراسيتامول R7', 'qty': 3.5, 'price': 10.0, 'storecode': '100'},
            {'itemcode': 'ZZZ', 'itemname': '', 'qty': 3.0, 'price': 0.0, 'storecode': ''},
        ])
        self.assertEqual(_build_receipt_lines([]), [])

    def test_apply_result_matched_then_not_found_clears(self):
        res = self.res()
        apply_match_result(res, {'status': 'matched', 'detail': 'ok', 'doc_value': '12.30',
                                 'receipt_lines': [{'x': 1}], 'erp_customer': {'name': 'n'}})
        self.assertEqual(res.erp_match_doc_value, Decimal('12.30'))
        self.assertEqual(res.erp_check_attempts, 1)
        apply_match_result(res, _not_found('none'))
        self.assertEqual((res.erp_receipt_lines, res.erp_customer_info, res.erp_check_attempts),
                         ([], {}, 2))
        self.assertIsNone(_to_float('abc'))
        self.assertIsNone(_to_float(None))

    def test_view_persists_discovered_doc_and_logs(self):
        res = self.res(status='fulfilled')
        result = _not_found('x')
        result.update(status='matched', detail='✅ تم', discovered_doc='7777', doc_code='115')
        with mock.patch.object(ReservationERPMatcher, 'run', return_value=result):
            r = self.pharm_c.post(_u(res.id, 'check-erp-match'))
        self.assertEqual(r.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.erp_reference, '7777')
        self.assertEqual(res.erp_match_status, 'matched')
        self.assertTrue(res.activities.filter(activity_type='stock_checked', message='✅ تم').exists())


# ── Chatter: activities / log / delete ────────────────────────────────────────

class ChatterTests(_Base):

    def test_list_and_soft_delete_rules(self):
        res = self.res()
        r = self.pharm_c.post(_u(res.id, 'log'), {'activity_type': 'note', 'message': 'مرحبا'},
                              format='json')
        self.assertEqual(r.status_code, 201)
        act_id = r.data['id']
        r = self.pharm_c.get(_u(res.id, 'activities'))
        self.assertEqual(r.status_code, 200)
        self.assertIn(act_id, [a['id'] for a in r.data])

        # someone else (not admin) may not delete it
        r = self.sales_c.delete(f'{_u(res.id)}activities/{act_id}/')
        self.assertEqual(r.status_code, 403)
        # the author can — a tombstone stays
        r = self.pharm_c.delete(f'{_u(res.id)}activities/{act_id}/')
        self.assertEqual(r.status_code, 200)
        act = ReservationActivity.objects.get(pk=act_id)
        self.assertTrue(act.is_deleted)
        self.assertEqual(act.deleted_by, self.pharm)
        # twice → 400; unknown → 404
        self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}activities/{act_id}/').status_code, 400)
        self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}activities/999999/').status_code, 404)

    def test_system_log_cannot_be_deleted_even_by_admin(self):
        res = self.res()
        act = ReservationActivity.objects.create(reservation=res, activity_type='status_changed',
                                                 message='sys', created_by=self.admin)
        r = self.admin_c.delete(f'{_u(res.id)}activities/{act.id}/')
        self.assertEqual(r.status_code, 403)


# ── Downpayments / print / share ──────────────────────────────────────────────

class ReceiptTests(_Base):

    def _with_money(self):
        res = self.res(customer=self.customer, notes='ملاحظة')
        ReservationDownpayment.objects.create(reservation=res, amount=Decimal('20.50'), received_by=self.pharm)
        ReservationDownpayment.objects.create(reservation=res, amount=Decimal('9.50'), received_by=self.pharm)
        ReservationLine.objects.create(reservation=res, item=self.item2, quantity_requested=3)
        return res

    def test_downpayments_total(self):
        res = self._with_money()
        r = self.pharm_c.get(_u(res.id, 'downpayments'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_paid'], 30.0)
        self.assertEqual(len(r.data['downpayments']), 2)

    def test_print_masks_pii_for_salesperson_and_logs_on_request(self):
        res = self._with_money()
        r = self.sales_c.get(_u(res.id, 'print'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['customer_name'], r.data['customer_phone']), ('—', '—'))
        self.assertEqual(r.data['total_paid'], 30.0)
        self.assertEqual(r.data['extra_lines'][0]['quantity'], 3.0)
        before = res.activities.count()
        r = self.pharm_c.get(_u(res.id, 'print'), {'log': '1'})
        self.assertEqual(r.data['customer_name'], 'عميل R7')
        self.assertEqual(res.activities.count(), before + 1)

    def test_share_whatsapp_lists_all_items(self):
        res = self._with_money()
        r = self.pharm_c.post(_u(res.id, 'share-whatsapp'))
        self.assertEqual(r.status_code, 200)
        text = r.data['message_text']
        self.assertIn(f'رقم الطلب: {res.id}', text)
        self.assertIn('*الأصناف (2 صنف):*', text)
        self.assertIn('العميل: عميل R7', text)
        self.assertTrue(res.activities.filter(message='تم مشاركة الحجز عبر واتساب').exists())

    def test_share_single_item_hides_customer_for_salesperson(self):
        res = self.res(customer=self.customer)
        r = self.sales_c.post(_u(res.id, 'share-whatsapp'))
        self.assertIn('• باراسيتامول R7 × 2.0', r.data['message_text'])
        self.assertNotIn('العميل:', r.data['message_text'])


# ── Dashboard / analytics / customer-history ──────────────────────────────────

class ReportTests(_Base):

    def test_dashboard_counts(self):
        self.res(status='pending', priority='urgent')
        self.res(status='pending')
        self.res(status='confirmed')
        self.res(status='fulfilled')
        self.res(status='pending', branch=self.branch2)   # other branch
        r = self.pharm_c.get(_u('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['pending'], r.data['confirmed'], r.data['urgent'],
                          r.data['fulfilled_this_week']), (2, 1, 1, 1))
        r = self.admin_c.get(_u('dashboard'), {'branch': self.branch2.id})
        self.assertEqual(r.data['pending'], 1)

    def test_analytics_rates(self):
        self.res(status='fulfilled')
        self.res(status='fulfilled', channel='home_delivery')
        self.res(status='cancelled', item=self.item2)
        self.res(status='pending')
        r = self.admin_c.get(_u('analytics'))
        self.assertEqual(r.status_code, 200)
        s = r.data['summary']
        self.assertEqual((s['total'], s['fulfilled'], s['lost'], s['active'], s['fulfillment_rate']),
                         (4, 2, 1, 1, 50.0))
        ch = {c['channel']: c for c in r.data['by_channel']}
        self.assertEqual((ch['cash_sales']['total'], ch['cash_sales']['rate']), (3, 33.3))
        self.assertEqual(r.data['lost_items'], [{'item_name': 'أموكسيسيلين R7', 'count': 1}])

    def test_customer_history(self):
        a = self.res(customer=self.customer)
        b = self.res(customer=self.customer, status='fulfilled')
        r = self.pharm_c.get(_u(a.id, 'customer-history'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([row['id'] for row in r.data], [b.id])
        walk_in = self.res()
        self.assertEqual(self.pharm_c.get(_u(walk_in.id, 'customer-history')).data, [])


# ── Images / lines / merge ────────────────────────────────────────────────────

class BasketTests(_Base):

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)

    def test_images_upload_list_delete(self):
        res = self.res()
        with override_settings(MEDIA_ROOT=self.media):
            r = self.pharm_c.post(_u(res.id, 'images'), {}, format='multipart')
            self.assertEqual(r.status_code, 400)
            f = SimpleUploadedFile('a.png', _png_bytes(), content_type='image/png')
            r = self.pharm_c.post(_u(res.id, 'images'), {'images': [f]}, format='multipart')
            self.assertEqual(r.status_code, 201, r.data)
            img_id = r.data[0]['id']
            self.assertEqual(len(self.pharm_c.get(_u(res.id, 'images')).data), 1)
            r = self.pharm_c.delete(f'{_u(res.id)}images/{img_id}/delete/')
            self.assertEqual(r.status_code, 204)
            self.assertFalse(ReservationImage.objects.exists())
            self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}images/{img_id}/delete/').status_code, 404)

    def test_lines_only_while_pending(self):
        res = self.res()
        r = self.pharm_c.post(_u(res.id, 'lines'), {'item': self.item2.id, 'quantity_requested': 2},
                              format='json')
        self.assertEqual(r.status_code, 201)
        line_id = r.data['id']
        self.assertEqual(len(self.pharm_c.get(_u(res.id, 'lines')).data), 1)
        r = self.pharm_c.post(_u(res.id, 'lines'), {'quantity_requested': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        Reservation.objects.filter(pk=res.pk).update(status='available')
        self.assertEqual(self.pharm_c.post(_u(res.id, 'lines'), {'item': self.item.id},
                                           format='json').status_code, 403)
        self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}lines/{line_id}/delete/').status_code, 403)
        Reservation.objects.filter(pk=res.pk).update(status='pending')
        self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}lines/{line_id}/delete/').status_code, 204)
        self.assertEqual(self.pharm_c.delete(f'{_u(res.id)}lines/{line_id}/delete/').status_code, 404)

    def test_merge_adds_quantity_and_cancels_target(self):
        keep = self.res(customer=self.customer, quantity_requested=Decimal('2'), notes='أ')
        drop = self.res(customer=self.customer, quantity_requested=Decimal('3'), notes='ب')
        r = self.pharm_c.post(_u(keep.id, 'merge'), {'target_id': drop.id}, format='json')
        self.assertEqual(r.status_code, 200)
        keep.refresh_from_db()
        drop.refresh_from_db()
        self.assertEqual(keep.quantity_requested, Decimal('5'))
        self.assertEqual(keep.notes, 'أ\nب')
        self.assertEqual(drop.status, 'cancelled')
        self.assertEqual(drop.status_logs.get().note, f'دُمج في الحجز #{keep.id}')

    def test_merge_guards(self):
        a = self.res(customer=self.customer)
        other_item = self.res(customer=self.customer, item=self.item2)
        done = self.res(customer=self.customer, status='fulfilled')
        post = lambda body: self.pharm_c.post(_u(a.id, 'merge'), body, format='json')  # noqa: E731
        self.assertEqual(post({}).status_code, 400)
        self.assertEqual(post({'target_id': a.id}).status_code, 400)
        self.assertEqual(post({'target_id': done.id}).status_code, 400)
        self.assertEqual(post({'target_id': other_item.id}).status_code, 400)
        self.assertEqual(post({'target_id': 999999}).status_code, 404)


# ── Bulk ──────────────────────────────────────────────────────────────────────

class BulkTests(_Base):

    def test_bulk_change_status_skips_illegal_moves(self):
        a = self.res(status='pending')
        b = self.res(status='fulfilled')
        r = self.pharm_c.post(_u('bulk'), {'action': 'change_status', 'ids': [a.id, b.id],
                                           'status': 'available'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {'updated': 1, 'skipped': 1})
        a.refresh_from_db()
        self.assertEqual(a.status, 'available')
        r = self.pharm_c.post(_u('bulk'), {'action': 'change_status', 'ids': [a.id],
                                           'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bulk_assign_only_open(self):
        a = self.res(status='pending')
        b = self.res(status='cancelled')
        r = self.admin_c.post(_u('bulk'), {'action': 'assign', 'ids': [a.id, b.id],
                                           'assigned_to': self.pharm.id}, format='json')
        self.assertEqual(r.data, {'updated': 1})
        a.refresh_from_db()
        self.assertEqual(a.assigned_to, self.pharm)
        r = self.admin_c.post(_u('bulk'), {'action': 'assign', 'ids': [a.id],
                                           'assigned_to': 999999}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_bulk_export_hides_phone_for_salesperson(self):
        import openpyxl
        res = self.res()
        ReservationLine.objects.create(reservation=res, manual_item_name='يدوي', quantity_requested=1)
        r = self.admin_c.post(_u('bulk'), {'action': 'export', 'ids': [res.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        header = [c.value for c in ws[1]]
        self.assertIn('الهاتف', header)
        self.assertEqual(header[-4:], ['الصنف 1', 'الكمية 1', 'الصنف 2', 'الكمية 2'])
        self.assertEqual([c.value for c in ws[2]][-4:], ['باراسيتامول R7', 2, 'يدوي', 1])
        r = self.sales_c.post(_u('bulk'), {'action': 'export', 'ids': [res.id]}, format='json')
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        self.assertNotIn('الهاتف', [c.value for c in ws[1]])


# ── reservation_activity function view ───────────────────────────────────────

class ActivityLogViewTests(_Base):

    def test_callback_and_expected_date_update_the_reservation(self):
        res = self.res()
        url = f'{URL}{res.pk}/activity/'
        when = timezone.make_aware(datetime.datetime(2026, 12, 3, 15, 0))
        r = self.pharm_c.post(url, {'activity_type': 'call_callback_requested', 'note': 'بكرة',
                                    'callback_datetime': when.isoformat()}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.pharm_c.post(url, {'activity_type': 'item_expected_date',
                                    'expected_date': '2026-12-10'}, format='json')
        self.assertEqual(r.status_code, 201)
        res.refresh_from_db()
        self.assertEqual(res.follow_up_date, datetime.date(2026, 12, 3))
        self.assertEqual(res.expected_arrival_date, datetime.date(2026, 12, 10))
        r = self.pharm_c.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 2)
        self.assertEqual(ActivityLog.objects.filter(reservation=res).count(), 2)

    def test_bad_type_400_and_other_branch_404(self):
        res = self.res()
        r = self.pharm_c.post(f'{URL}{res.pk}/activity/', {'activity_type': 'nope'}, format='json')
        self.assertEqual(r.status_code, 400)
        other = self.res(branch=self.branch2)
        self.assertEqual(self.pharm_c.get(f'{URL}{other.pk}/activity/').status_code, 404)

    def test_admin_logging_notifies_branch(self):
        res = self.res()
        r = self.admin_c.post(f'{URL}{res.pk}/activity/', {'activity_type': 'note_added', 'note': 'x'},
                              format='json')
        self.assertEqual(r.status_code, 201)
