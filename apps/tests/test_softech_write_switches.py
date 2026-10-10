"""
apps/tests/test_softech_write_switches.py

Per-feature switches for the SOFTECH writes that had none:
  PRICING_SOFTECH_WRITE_ENABLED, REPLICATION_REPAIR_ENABLED,
  LOYALTY_SOFTECH_WRITE_ENABLED, PERSONAL_COMMENT_WRITE_ENABLED.
Default ON (unchanged behaviour). OFF must stop the write BEFORE any SOFTECH
connection is opened — in the view and in the writer itself (scheduled jobs and
management commands call the writers directly).
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .factories import make_branch, make_item, make_user

NO_SOFTECH = mock.patch('config.sybase.get_sybase_connection',
                        side_effect=AssertionError('SOFTECH must not be contacted'))


def _no_conn(module):
    """Patch a module-level imported connector so any call fails the test."""
    return mock.patch(f'{module}.get_sybase_connection',
                      side_effect=AssertionError('SOFTECH must not be contacted'))


class DefaultsTests(TestCase):

    def test_switches_default_on(self):
        from django.conf import settings
        for name in ('PRICING_SOFTECH_WRITE_ENABLED', 'REPLICATION_REPAIR_ENABLED',
                     'LOYALTY_SOFTECH_WRITE_ENABLED', 'PERSONAL_COMMENT_WRITE_ENABLED'):
            self.assertTrue(getattr(settings, name), name)


@override_settings(PRICING_SOFTECH_WRITE_ENABLED=False)
class PricingSwitchTests(TestCase):

    def setUp(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        self.branch = make_branch()
        self.admin, self.profile, self.client_ = make_user('price_admin', role='admin',
                                                           branch=self.branch, access_all=True)
        self.item = make_item(softech_id='PX1')
        self.req = ItemPriceChangeRequest.objects.create(
            item=self.item, requested_by=self.admin, old_values={},
            new_values={'special_discp': '15'}, reason='t',
            status=ItemPriceChangeRequest.STATUS_PENDING)

    def test_approve_refused_and_request_stays_pending(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        with NO_SOFTECH:
            r = self.client_.post(f'/api/pricing-approvals/{self.req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()['error_code'], 'pricing_writes_disabled')
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ItemPriceChangeRequest.STATUS_PENDING)

    def test_executor_refuses_without_connecting(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        from apps.discount_approvals.services import execute_price_change
        with NO_SOFTECH:
            self.assertFalse(execute_price_change(self.req, erp_usercode='1'))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ItemPriceChangeRequest.STATUS_FAILED)
        self.assertIn('PRICING_SOFTECH_WRITE_ENABLED', self.req.erp_error)

    def test_classification_alignment_refused(self):
        from apps.discount_approvals.alignment import apply_classification_changes
        with NO_SOFTECH:
            err, results = apply_classification_changes([{'item_id': self.item.pk, 'origin_code': '1'}], '1')
        self.assertIn('PRICING_SOFTECH_WRITE_ENABLED', err)
        self.assertEqual(results, [])


@override_settings(REPLICATION_REPAIR_ENABLED=False)
class ReplicationSwitchTests(TestCase):

    def setUp(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        self.branch = make_branch()
        self.admin, _, self.client_ = make_user('repl_admin', role='admin',
                                                branch=self.branch, access_all=True)
        self.req = ItemPriceChangeRequest.objects.create(
            item=make_item(softech_id='PX2'), requested_by=self.admin, old_values={},
            new_values={'special_discp': '5'}, reason='t')

    def test_writer_refuses_without_connecting(self):
        from apps.discount_approvals.replication import force_replication
        with NO_SOFTECH:
            out = force_replication('PX2', mode='both')
        self.assertEqual(out['error'], 'replication_repair_disabled')
        self.assertFalse(out['restamped'])

    def test_views_refuse(self):
        with NO_SOFTECH:
            r1 = self.client_.post(f'/api/pricing-approvals/{self.req.pk}/force-replication/', {}, format='json')
            r2 = self.client_.post('/api/pricing-approvals/replication/repair/', {'gap_ids': [1]}, format='json')
        self.assertEqual((r1.status_code, r2.status_code), (503, 503))

    def test_scheduled_auto_repair_skipped(self):
        from apps.discount_approvals.models import ReplicationPolicy
        from apps.sync import tasks
        pol = ReplicationPolicy.get()
        pol.auto_repair_enabled = True
        pol.save()
        scan = mock.Mock(pk=1, items_with_gaps=3, branches_down=0)
        with mock.patch('apps.discount_approvals.replication.scan_recent', return_value=scan), \
             mock.patch('apps.discount_approvals.notify.notify_admins_replication_gaps'), \
             mock.patch('apps.discount_approvals.replication.force_replication') as force:
            with self.assertLogs('elrezeiky.sync', level='INFO') as logs:
                tasks._run_replication_audit()
        force.assert_not_called()
        self.assertTrue(any('auto-repair skipped' in line for line in logs.output), logs.output)


@override_settings(LOYALTY_SOFTECH_WRITE_ENABLED=False)
class LoyaltySwitchTests(TestCase):

    def setUp(self):
        from apps.customers.models import Customer
        self.branch = make_branch()
        self.customer = Customer.objects.create(name='عميل', phone='01000000002', softech_pic='P2')

    def test_purchase_lane_refused_referral_lane_still_works(self):
        _, _, client = make_user('loy_cc', role='call_center', branch=self.branch)
        url = f'/api/loyalty/customers/{self.customer.pk}/adjust/'
        with mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adjust:
            r = client.post(url, {'points': 5, 'reason': 'x', 'adjust_type': 'purchase'}, format='json')
            self.assertEqual(r.status_code, 503)
            adjust.assert_not_called()
        r = client.post(url, {'points': 5, 'reason': 'x', 'adjust_type': 'referral'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_writer_refuses_without_connecting(self):
        from apps.loyalty.pic_bridge import adjust_softech_points
        with _no_conn('apps.loyalty.pic_bridge'):
            with self.assertRaises(RuntimeError):
                adjust_softech_points('P2', 5, reason='x')


@override_settings(PERSONAL_COMMENT_WRITE_ENABLED=False)
class PersonalCommentSwitchTests(TestCase):

    def test_writers_refuse_without_connecting(self):
        from apps.personal.writeback import (
            CommentWriteError, write_cheque_note, write_document_comment,
        )
        with _no_conn('apps.personal.writeback'):
            with self.assertRaises(CommentWriteError) as c1:
                write_document_comment(branchcode='140', doccode='10', docnumber='1',
                                       comment='ok', expected_person_code='5014')
            with self.assertRaises(CommentWriteError) as c2:
                write_cheque_note(branchcode='140', financialdoccode='1', cheqsno='1',
                                  note='ok', expected_person_code='5014')
        self.assertEqual((c1.exception.status, c2.exception.status), (503, 503))
