"""Task 7: the portal agent queue — claim, heartbeat, report, lease expiry, resolve.

The rule this file guards above all: a supplier order is never placed twice. A basket that might
already have been ordered (it reached the Submit handover) never goes back to `ready` on its own,
and a person can only retry it after Order History showed nothing, or after saying so explicitly.
"""
import io
import shutil
import tempfile
import threading
from datetime import timedelta
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.catalog.models import Item
from apps.rpa.auth import issue_device
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob,
                             PortalLine, PortalRun, RpaScreenshot, SupplierPortal)
from apps.rpa.portal import jobs, queue
from apps.users.models import RoleModuleAccess
from .factories import make_user

ON = dict(WRITER_INSTANCE=True, RPA_SUPPLIER_PORTAL_ENABLED=True)
HEADER = 'HTTP_X_ELR_RPA_AGENT'
IDENTITY = 'ElRezeiky HQ 565'


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (10, 20, 30)).save(buf, format='PNG')
    f = io.BytesIO(buf.getvalue())
    f.name = 'shot.png'
    return f


def _grant(role, *actions):
    for action in actions:
        RoleModuleAccess.objects.update_or_create(role=role, module='rpa', action=action,
                                                  defaults={'is_allowed': True})


class _World:
    def build_world(self, prefix):
        _grant('purchasing', 'view', 'create')
        _grant('supervisor', 'view', 'create', 'edit')
        _, self.buyer, _ = make_user(f'{prefix}_buyer', role='purchasing', access_all=True)
        _, self.other, _ = make_user(f'{prefix}_other', role='purchasing', access_all=True)
        _, self.boss, _ = make_user(f'{prefix}_boss', role='supervisor', access_all=True)
        self.portal, _ = SupplierPortal.objects.get_or_create(
            key='pharma_overseas', defaults={'supplier_code': '565'})
        self.portal.enabled = True
        self.portal.live = False
        self.portal.save()
        self.account = PortalAccount.objects.create(portal=self.portal, label='main',
                                                    identity_text=IDENTITY)
        self.items = [Item.objects.create(softech_id=f'{prefix}{n}', name=f'ITEM {n} 20 TAB',
                                          is_active=True) for n in range(6)]
        self.dev, self.secret = issue_device(staff=self.buyer, label='buyer pc', created_by=self.boss)

    def make_job(self, staff=None, *, live=False, statuses=('ready',), keyless=False, account=None):
        staff = staff or self.buyer
        bl = BuyList.objects.create(source_kind='upload', created_by=staff)
        job = PortalJob.objects.create(portal=self.portal, account=account or self.account, buylist=bl,
                                       status='approved', dry_run=not live, created_by=staff,
                                       approved_by=staff, approved_at=timezone.now())
        baskets = []
        for n, st in enumerate(statuses, start=1):
            b = PortalBasket.objects.create(job=job, seq=n, status=st)
            item = self.items[n % len(self.items)]
            line = BuyListLine.objects.create(buylist=bl, seq=n, item=item, needed_qty=4,
                                              remaining_qty=4, chosen_supplier='565',
                                              source_key=f'q:{bl.pk}:{n}')
            key = '' if keyless else str(52870 + n)
            PortalLine.objects.create(basket=b, buyline=line, item=item, wanted_qty=4,
                                      supplier_key=key, supplier_key_padded=key.zfill(18) if key else '')
            baskets.append(b)
        return job, baskets


@override_settings(**ON)
class QueueTests(_World, TestCase):

    def setUp(self):
        self.build_world('PQ')

    # ── claim ────────────────────────────────────────────────────────────────────────────────

    def test_claim_off_when_switch_off(self):
        self.make_job()
        with override_settings(RPA_SUPPLIER_PORTAL_ENABLED=False):
            self.assertIsNone(queue.claim_next(self.dev))
        with override_settings(WRITER_INSTANCE=False):
            self.assertIsNone(queue.claim_next(self.dev))
        SupplierPortal.objects.filter(pk=self.portal.pk).update(enabled=False)
        self.assertIsNone(queue.claim_next(self.dev))
        self.assertEqual(PortalRun.objects.count(), 0)
        self.assertEqual(PortalBasket.objects.get().status, 'ready')

    def test_claim_only_own_jobs(self):
        self.make_job(staff=self.other)
        self.assertIsNone(queue.claim_next(self.dev))
        _, (mine,) = self.make_job()
        claim = queue.claim_next(self.dev)
        self.assertEqual(claim['plan']['kind'], 'fill')
        self.assertEqual(claim['plan']['basket_id'], mine.pk)
        self.assertEqual(claim['plan']['mode'], 'dry_run')
        mine.refresh_from_db()
        self.assertEqual(mine.status, 'in_progress')
        self.assertEqual(mine.claimed_by_id, self.dev.pk)
        self.assertGreater(mine.lease_until, timezone.now() + timedelta(minutes=9))
        run = PortalRun.objects.get(pk=claim['run_id'])
        self.assertEqual((run.basket_id, run.device_id, run.kind), (mine.pk, self.dev.pk, 'fill'))
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_basket_claimed').exists())

    def test_claim_one_basket_per_device_at_a_time(self):
        self.make_job(statuses=('ready', 'ready'))
        self.assertIsNotNone(queue.claim_next(self.dev))
        self.assertIsNone(queue.claim_next(self.dev))

    def test_claim_skips_inactive_account(self):
        idle = PortalAccount.objects.create(portal=self.portal, label='idle', identity_text='x', active=False)
        self.make_job(account=idle)
        self.assertIsNone(queue.claim_next(self.dev))
        self.make_job(account=idle, keyless=True, statuses=('pending',))
        self.assertIsNone(queue.claim_next(self.dev))

    def test_claim_discovery_before_ready(self):
        self.make_job()
        job, _ = self.make_job(keyless=True, statuses=('pending',))
        claim = queue.claim_next(self.dev)
        self.assertEqual(claim['plan']['kind'], 'discovery')
        run = PortalRun.objects.get(pk=claim['run_id'])
        self.assertEqual((run.discovery_job_id, run.kind), (job.pk, 'discovery'))
        with mock.patch('apps.rpa.portal.skus.record_discovery') as rec:
            queue.report(run, self.dev, {'outcome': 'discovery_ok', 'discovery': [{'buyline_id': 1}]})
        rec.assert_called_once()
        # discovery done: the next claim is the ready basket, not the same search again
        self.assertEqual(queue.claim_next(self.dev)['plan']['kind'], 'fill')

    # ── concurrency lives in ConcurrentClaimTests ───────────────────────────────────────────

    def test_second_device_same_account_waits(self):
        self.make_job(statuses=('ready', 'ready'))
        dev2, _ = issue_device(staff=self.buyer, label='second pc', created_by=self.boss)
        first = queue.claim_next(self.dev)
        self.assertIsNotNone(first)
        # same PortalAccount = same supplier cart: the second robot waits
        self.assertIsNone(queue.claim_next(dev2))
        # also while the first basket waits at Submit
        PortalBasket.objects.filter(pk=first['plan']['basket_id']).update(status='awaiting_submit')
        self.assertIsNone(queue.claim_next(dev2))
        # a queued Order History read on the busy account waits too
        _, (stuck,) = self.make_job(statuses=('needs_person',))
        PortalBasket.objects.filter(pk=stuck.pk).update(needs_person_at=timezone.now())
        stuck.refresh_from_db()
        queue.request_history(stuck)
        self.assertIsNone(queue.claim_next(dev2))
        # work on another account is not held up
        acc2 = PortalAccount.objects.create(portal=self.portal, label='second', identity_text='HQ 2')
        _, (other,) = self.make_job(account=acc2)
        self.assertEqual(queue.claim_next(dev2)['plan']['basket_id'], other.pk)

    # ── lease ────────────────────────────────────────────────────────────────────────────────

    def test_heartbeat_extends_lease_and_refuses_others(self):
        self.make_job()
        claim = queue.claim_next(self.dev)
        run = PortalRun.objects.get(pk=claim['run_id'])
        PortalBasket.objects.filter(pk=run.basket_id).update(lease_until=timezone.now() + timedelta(minutes=1))
        queue.heartbeat(run, self.dev)
        self.assertGreater(PortalBasket.objects.get(pk=run.basket_id).lease_until,
                           timezone.now() + timedelta(minutes=9))
        dev2, _ = issue_device(staff=self.buyer, label='second', created_by=self.boss)
        with self.assertRaises(queue.RunConflict):
            queue.heartbeat(run, dev2)

    def test_lease_expiry_goes_needs_person_not_ready(self):
        self.make_job(statuses=('ready', 'ready'))
        run = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        PortalBasket.objects.filter(pk=run.basket_id).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(queue.expire_leases(), 1)
        b = PortalBasket.objects.get(pk=run.basket_id)
        self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'lease_expired'))
        self.assertIsNone(b.lease_until)
        self.assertIsNotNone(b.needs_person_at)
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_needs_person').exists())
        # never back to the queue: the next claim is the OTHER basket, and this one stays put
        nxt = queue.claim_next(self.dev)
        self.assertNotEqual(nxt['plan']['basket_id'], b.pk)
        self.assertEqual(PortalBasket.objects.get(pk=b.pk).status, 'needs_person')
        self.assertEqual(queue.expire_leases(), 0)
        with self.assertRaises(queue.RunConflict):
            queue.heartbeat(run, self.dev)

    def test_awaiting_submit_lease_expiry_queues_order_history(self):
        self.make_job(live=True)
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        self.assertEqual(run.mode, 'live')
        queue.report(run, self.dev, {'outcome': 'handover', 'steps': [], 'lines': []})
        b = PortalBasket.objects.get(pk=run.basket_id)
        self.assertEqual(b.status, 'awaiting_submit')
        self.assertIsNotNone(b.filled_at)
        PortalBasket.objects.filter(pk=b.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        queue.expire_leases()
        self.assertEqual(PortalBasket.objects.get(pk=b.pk).status, 'needs_person')
        claim = queue.claim_next(self.dev)
        self.assertEqual(claim['plan']['kind'], 'history')
        self.assertEqual(claim['plan']['basket_id'], b.pk)

    # ── report ───────────────────────────────────────────────────────────────────────────────

    def _fill_run(self, **kw):
        self.make_job(**kw)
        return PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])

    def test_cart_not_empty_outcome_needs_person(self):
        run = self._fill_run()
        b = queue.report(run, self.dev, {'outcome': 'cart_not_empty', 'steps': [{'label': 'check_account'}, {'label': 'check_cart_empty'}]})
        self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'cart_not_empty'))
        run.refresh_from_db()
        self.assertEqual(run.outcome, 'cart_not_empty')
        self.assertIsNotNone(run.finished_at)
        # an ordinary needs-person reason that cannot mean an order: retry goes straight back
        b = queue.resolve(b, staff=self.boss, action='retry')
        self.assertEqual(b.status, 'ready')
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_resolved').exists())

    def test_dry_run_ok_calls_record_check(self):
        run = self._fill_run()
        lines = [{'line_id': 1, 'accepted_qty': 4}]
        with mock.patch('apps.rpa.portal.recording.record_check') as rc:
            queue.report(run, self.dev, {'outcome': 'dry_run_ok', 'lines': lines,
                                         'credit': {'credit': '1000', 'limit': '5000'}})
        rc.assert_called_once()
        self.assertEqual(rc.call_args.args[1], lines)
        self.account.refresh_from_db()
        self.assertEqual(self.account.last_credit['credit'], '1000')
        self.assertIn('at', self.account.last_credit)
        self.assertIsNotNone(PortalRun.objects.get(pk=run.pk).finished_at)

    def test_wrong_identity_is_wrong_account(self):
        run = self._fill_run()
        b = queue.report(run, self.dev, {'outcome': 'dry_run_ok', 'account': {'identity_text': 'Other Pharmacy'}})
        self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'wrong_account_late'))

    def test_handover_in_dry_run_needs_person(self):
        run = self._fill_run()
        b = queue.report(run, self.dev, {'outcome': 'handover'})
        self.assertEqual(b.status, 'needs_person')

    def test_submit_seen_marks_submitted_and_records_order(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        queue.report(run, self.dev, {'outcome': 'handover'})
        hist = [{'sku': '52871', 'qty': 4}]
        with mock.patch('apps.rpa.portal.recording.record_order') as ro:
            ro.side_effect = lambda basket, **kw: basket
            b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': '2104322530',
                                             'history_lines': hist})
        self.assertEqual(ro.call_args.kwargs['order_ref'], '2104322530')
        self.assertEqual(ro.call_args.kwargs['history_lines'], hist)
        self.assertEqual(b.status, 'submitted')
        self.assertIsNotNone(b.submitted_seen_at)
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_submit_seen').exists())
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_basket_filled').exists())
        # a submitted basket is never claimed again
        self.assertIsNone(queue.claim_next(self.dev))

    def test_wrong_device_report_409(self):
        run = self._fill_run()
        dev2, secret2 = issue_device(staff=self.buyer, label='second', created_by=self.boss)
        with self.assertRaises(queue.RunConflict):
            queue.report(run, dev2, {'outcome': 'dry_run_ok'})
        api = APIClient()
        api.credentials(**{HEADER: secret2})
        url = f'/api/rpa/agent/portal/runs/{run.pk}/report/'
        self.assertEqual(api.post(url, {'outcome': 'dry_run_ok'}, format='json').status_code, 409)
        self.assertEqual(PortalBasket.objects.get(pk=run.basket_id).status, 'in_progress')
        # the right device closes it; a second report on the closed run is a 409 too
        mine = APIClient()
        mine.credentials(**{HEADER: self.secret})
        self.assertEqual(mine.post(url, {'outcome': 'error'}, format='json').status_code, 200)
        self.assertEqual(mine.post(url, {'outcome': 'error'}, format='json').status_code, 409)

    def test_late_submit_seen_after_lease_expiry_blocks_retry(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        queue.report(run, self.dev, {'outcome': 'handover'})
        PortalBasket.objects.filter(pk=run.basket_id).update(lease_until=timezone.now() - timedelta(seconds=1))
        queue.expire_leases()
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': '777'})
        self.assertEqual(b.status, 'needs_person')
        self.assertIsNotNone(b.submitted_seen_at)
        self.assertIn('777', b.needs_person_reason)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True)

    # ── resolve ──────────────────────────────────────────────────────────────────────────────

    def _live_run(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        self.assertEqual(run.mode, 'live')
        return run

    def test_live_lease_expired_in_progress_needs_history_before_retry(self):
        run = self._live_run()                       # never reported a handover
        PortalBasket.objects.filter(pk=run.basket_id).update(lease_until=timezone.now() - timedelta(seconds=1))
        queue.expire_leases()
        b = PortalBasket.objects.get(pk=run.basket_id)
        self.assertIsNone(b.filled_at)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')
        claim = queue.claim_next(self.dev)
        hrun = PortalRun.objects.get(pk=claim['run_id'])
        self.assertEqual(hrun.kind, 'history')
        # the read starts where the robot may first have reached the cart (with the R9 margin)
        self.assertEqual(claim['plan']['since'], queue.history_since(run.started_at).isoformat())
        queue.report(hrun, self.dev, {'outcome': 'history_none'})
        b = queue.resolve(b, staff=self.boss, action='retry')
        self.assertEqual(b.status, 'ready')
        # cleared: a fresh live run that stops before the cart retries straight away
        run2 = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        b = queue.report(run2, self.dev, {'outcome': 'cart_not_empty', 'steps': [{'label': 'check_cart_empty'}]})
        self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready')

    def test_live_error_after_claim_needs_history_before_retry(self):
        for outcome in ('error', 'timeout', 'unknown_message', 'stopped_by_operator', 'cart_mismatch'):
            run = self._live_run()
            b = queue.report(run, self.dev, {'outcome': outcome})
            self.assertIsNone(b.filled_at)
            with self.assertRaises(queue.QueueError, msg=outcome):
                queue.resolve(b, staff=self.boss, action='retry')
            self.assertTrue(PortalRun.objects.filter(basket=b, kind='history', finished_at__isnull=True).exists())
            b = queue.resolve(b, staff=self.boss, action='retry', confirm_none=True)
            self.assertEqual(b.status, 'ready')
            PortalBasket.objects.filter(pk=b.pk).update(status='cancelled')

    def test_login_timeout_mid_run_needs_history(self):
        # a login page can appear mid-run with the cart full: the operator may log in and Submit
        for identity in (None, 'Some Other Pharmacy'):
            run = self._live_run()
            payload = {'outcome': 'login_required_timeout'}
            if identity:
                payload['account'] = {'identity_text': identity}
            b = queue.report(run, self.dev, payload)
            self.assertEqual(b.needs_person_reason,
                             'wrong_account_late' if identity else 'login_required_timeout')
            with self.assertRaises(queue.QueueError):
                queue.resolve(b, staff=self.boss, action='retry')
            claim = queue.claim_next(self.dev)
            self.assertEqual((claim['plan']['kind'], claim['plan']['basket_id']), ('history', b.pk))
            self.assertEqual(claim['plan']['since'], queue.history_since(run.started_at).isoformat())
            PortalRun.objects.filter(pk=claim['run_id']).update(finished_at=timezone.now(), outcome='error')
            PortalBasket.objects.filter(pk=b.pk).update(status='cancelled')

    def _assert_gated(self, payload, reason):
        run = self._live_run()
        b = queue.report(run, self.dev, payload)
        self.assertEqual(b.needs_person_reason, reason, payload)
        with self.assertRaises(queue.QueueError, msg=repr(payload)):
            queue.resolve(b, staff=self.boss, action='retry')
        self.assertTrue(PortalRun.objects.filter(basket=b, kind='history', finished_at__isnull=True).exists(),
                        payload)
        PortalBasket.objects.filter(pk=b.pk).update(status='cancelled')

    def test_pre_cart_outcome_with_added_line_is_gated(self):
        pre = [{'label': 'check_account', 'ok': True}, {'label': 'check_cart_empty', 'ok': True}]
        cases = [
            ({'outcome': 'cart_not_empty', 'steps': pre + [{'label': 'add_line', 'ok': True}]},
             'cart_not_empty_late'),
            ({'outcome': 'wrong_account', 'steps': pre, 'lines': [{'line_id': 1, 'accepted_qty': 3}]},
             'wrong_account_late'),
            ({'outcome': 'wrong_account', 'steps': pre, 'lines': [{'line_id': 1, 'added_qty': 2}]},
             'wrong_account_late'),
            # R11: even a zero-quantity line is a line - only an empty list is "nothing touched"
            ({'outcome': 'cart_not_empty', 'steps': pre, 'lines': [{'line_id': 1, 'accepted_qty': 0}]},
             'cart_not_empty_late'),
        ]
        for payload, reason in cases:
            self._assert_gated(payload, reason)

    def test_pre_cart_report_fail_safe(self):
        """R11: a pre-cart outcome is believed only on an allow-listed payload; anything else is
        "cart touched" and gated."""
        pre = [{'label': 'check_account'}, {'label': 'check_cart_empty'}]
        cases = [
            {'steps': {'label': 'check_account'}},                       # non-list steps (dict)
            {'steps': 'check_account'},                                  # non-list steps (string)
            {},                                                          # steps missing
            {'steps': None},                                             # steps null
            {'steps': pre + ['check_cart_empty']},                       # a non-dict entry
            {'steps': pre + [{'label': 'cart'}]},                        # an unknown label
            {'steps': [{'label': 'Check_Account'}]},                     # labels match exactly
            {'steps': [{'label': 'check_account '}]},
            {'steps': [{'note': 'no label'}]},                           # no label at all
            {'steps': [{'label': None}]},
            {'steps': pre, 'lines': [{'line_id': 1, 'status': 'added'}]},  # status only
            {'steps': pre, 'lines': [{'line_id': 1, 'accepted_qty': 0.5}]},  # fractional qty
            {'steps': pre, 'lines': 'line 1 added'},                     # lines is a string
            {'steps': pre, 'lines': {'line_id': 1}},                     # lines is a dict
            {'steps': pre, 'lines': [None]},                             # a non-dict line
        ]
        for outcome, reason in (('cart_not_empty', 'cart_not_empty_late'),
                                ('wrong_account', 'wrong_account_late')):
            for case in cases:
                self._assert_gated({'outcome': outcome, **case}, reason)

    def test_pre_cart_allow_listed_report_retries_freely(self):
        for payload in ({'steps': [{'label': 'check_account', 'ok': True},
                                   {'label': 'check_cart_empty', 'ok': False}], 'lines': []},
                        {'steps': [{'label': 'check_account'}]},
                        {'steps': [], 'lines': None}):
            run = self._live_run()
            b = queue.report(run, self.dev, {'outcome': 'cart_not_empty', **payload})
            self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'cart_not_empty'), payload)
            self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready', payload)
            PortalBasket.objects.filter(pk=b.pk).update(status='cancelled')

    def test_driver_reported_wrong_account_late_is_gated(self):
        run = self._live_run()
        b = queue.report(run, self.dev, {'outcome': 'wrong_account_late'})
        self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'wrong_account_late'))
        self.assertEqual(PortalRun.objects.get(pk=run.pk).outcome, 'wrong_account_late')
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')
        self.assertEqual(queue.claim_next(self.dev)['plan']['kind'], 'history')

    def test_history_since_is_local_midnight_before_a_two_hour_margin(self):
        import zoneinfo
        from datetime import datetime
        cairo = zoneinfo.ZoneInfo('Africa/Cairo')
        with override_settings(TIME_ZONE='Africa/Cairo'):
            just_after_midnight = datetime(2026, 11, 17, 0, 30, tzinfo=cairo)
            self.assertEqual(queue.history_since(just_after_midnight), datetime(2026, 11, 16, 0, 0, tzinfo=cairo))
            midday = datetime(2026, 11, 17, 12, 0, tzinfo=cairo)
            self.assertEqual(queue.history_since(midday), datetime(2026, 11, 17, 0, 0, tzinfo=cairo))
            # the same instant given in UTC gives the same answer
            self.assertEqual(queue.history_since(midday.astimezone(zoneinfo.ZoneInfo('UTC'))),
                             datetime(2026, 11, 17, 0, 0, tzinfo=cairo))

    def test_history_read_without_window_is_not_handed_out(self):
        _, (b,) = self.make_job(statuses=('needs_person',))
        PortalBasket.objects.filter(pk=b.pk).update(needs_person_at=timezone.now())
        b.refresh_from_db()
        hrun = queue.request_history(b)
        self.assertIsNone(queue.claim_next(self.dev))
        hrun.refresh_from_db()
        self.assertEqual((hrun.outcome, hrun.device_id), ('error', None))
        self.assertIsNotNone(hrun.finished_at)

    def test_live_pre_cart_outcomes_retry_freely(self):
        for outcome in ('cart_not_empty', 'wrong_account'):
            run = self._live_run()
            b = queue.report(run, self.dev, {'outcome': outcome, 'steps': [{'label': 'check_account'}]})
            self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready', outcome)
            PortalBasket.objects.filter(pk=b.pk).update(status='cancelled')
        # a past-the-cart outcome from the wrong account is NOT pre-cart
        run = self._live_run()
        b = queue.report(run, self.dev, {'outcome': 'cart_mismatch', 'account': {'identity_text': 'other'}})
        self.assertEqual(b.needs_person_reason, 'wrong_account_late')
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')

    def test_submit_seen_wrong_identity_keeps_the_sighting(self):
        run = self._live_run()
        queue.report(run, self.dev, {'outcome': 'handover'})
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': '4242',
                                         'account': {'identity_text': 'Some Other Pharmacy'},
                                         'history_lines': [{'sku': '52871', 'qty': 4}]})
        self.assertEqual(b.status, 'needs_person')
        self.assertIsNotNone(b.submitted_seen_at)
        self.assertIn('4242', b.needs_person_reason)
        self.assertEqual(PortalRun.objects.get(pk=run.pk).outcome, 'submit_seen')
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_submit_seen').exists())
        for kw in ({}, {'confirm_none': True}):
            with self.assertRaises(queue.QueueError):
                queue.resolve(b, staff=self.boss, action='retry', **kw)
        with mock.patch('apps.rpa.portal.recording.record_order') as ro:
            ro.side_effect = lambda basket, **kw: basket
            queue.resolve(b, staff=self.boss, action='link_order', order_ref='4242')
        self.assertEqual(ro.call_args.kwargs['history_lines'], [{'sku': '52871', 'qty': 4}])

    def test_retry_blocked_after_awaiting_submit_until_history_or_confirm(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        queue.report(run, self.dev, {'outcome': 'handover'})
        PortalBasket.objects.filter(pk=run.basket_id).update(lease_until=timezone.now() - timedelta(seconds=1))
        queue.expire_leases()
        b = PortalBasket.objects.get(pk=run.basket_id)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')
        # confirm_none needs rpa.edit
        with self.assertRaises(PermissionDenied):
            queue.resolve(b, staff=self.buyer, action='retry', confirm_none=True)
        # an Order History read that found an order does not unlock it either
        hrun = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        self.assertEqual(hrun.kind, 'history')
        queue.report(hrun, self.dev, {'outcome': 'history_found', 'order_ref': '555',
                                      'history_lines': [{'sku': '52871', 'qty': 4}]})
        with self.assertRaises(queue.QueueError):
            queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='retry')
        # nor does a later read that found nothing: one sighting of an order is enough to block
        queue.request_history(b)
        hrun2 = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        queue.report(hrun2, self.dev, {'outcome': 'history_none'})
        with self.assertRaises(queue.QueueError):
            queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='retry')
        # only a person's explicit "nothing was ordered" does
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='retry',
                          confirm_none=True)
        self.assertEqual((b.status, b.claimed_by_id), ('ready', None))

    def test_retry_after_history_found_nothing(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        queue.report(run, self.dev, {'outcome': 'handover'})
        queue.report(run, self.dev, {'outcome': 'timeout'})
        b = PortalBasket.objects.get(pk=run.basket_id)
        hrun = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        # a read from the wrong account proves nothing
        queue.report(hrun, self.dev, {'outcome': 'history_none', 'account': {'identity_text': 'other'}})
        self.assertEqual(PortalRun.objects.get(pk=hrun.pk).outcome, 'wrong_account')
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')
        queue.request_history(b)
        hrun2 = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        queue.report(hrun2, self.dev, {'outcome': 'history_none', 'account': {'identity_text': IDENTITY}})
        b = queue.resolve(b, staff=self.boss, action='retry')
        self.assertEqual((b.status, b.claimed_by_id), ('ready', None))

    def test_retry_with_confirm_none_is_audited(self):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        run = self._fill_run(live=True)
        queue.report(run, self.dev, {'outcome': 'handover'})
        queue.report(run, self.dev, {'outcome': 'stopped_by_operator'})
        b = PortalBasket.objects.get(pk=run.basket_id)
        self.assertEqual(b.status, 'needs_person')
        b = queue.resolve(b, staff=self.boss, action='retry', confirm_none=True)
        self.assertEqual(b.status, 'ready')
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertTrue(log.new_data['confirm_none'])

    def test_resolve_needs_edit_and_needs_person(self):
        run = self._fill_run()
        b = PortalBasket.objects.get(pk=run.basket_id)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='cancel')     # still in progress
        b = queue.report(run, self.dev, {'outcome': 'timeout'})
        with self.assertRaises(PermissionDenied):
            queue.resolve(b, staff=self.buyer, action='cancel')
        self.assertEqual(queue.resolve(b, staff=self.boss, action='cancel').status, 'cancelled')

    def test_link_order_goes_through_record_order(self):
        run = self._fill_run()
        b = queue.report(run, self.dev, {'outcome': 'unknown_message'})
        with mock.patch('apps.rpa.portal.recording.record_order') as ro:
            ro.side_effect = lambda basket, **kw: basket
            queue.resolve(b, staff=self.boss, action='link_order', order_ref='991')
        self.assertEqual(ro.call_args.kwargs['order_ref'], '991')
        with self.assertRaises(queue.QueueError):
            queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='link_order')

    # ── screenshot ───────────────────────────────────────────────────────────────────────────

    def test_screenshot_attaches_to_portal_run_only(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        run = self._fill_run()
        api = APIClient()
        api.credentials(**{HEADER: self.secret})
        with override_settings(MEDIA_ROOT=media):
            r = api.post(f'/api/rpa/agent/portal/runs/{run.pk}/screenshot/',
                         {'step_index': '2', 'image': _png()})
            self.assertEqual(r.status_code, 201, r.content)
            shot = RpaScreenshot.objects.get(pk=r.json()['id'])
            self.assertEqual((shot.portal_run_id, shot.run_id), (run.pk, None))
            dev2, secret2 = issue_device(staff=self.buyer, label='x', created_by=self.boss)
            other = APIClient()
            other.credentials(**{HEADER: secret2})
            self.assertEqual(other.post(f'/api/rpa/agent/portal/runs/{run.pk}/screenshot/',
                                        {'step_index': '3', 'image': _png()}).status_code, 404)
        # exactly one of run / portal_run
        with self.assertRaises(IntegrityError), transaction.atomic():
            RpaScreenshot.objects.create(step_index=1, image='x.png')

    # ── API ──────────────────────────────────────────────────────────────────────────────────

    def test_agent_api_claim_heartbeat_report(self):
        api = APIClient()
        self.assertEqual(api.post('/api/rpa/agent/portal/claim/').status_code, 401)
        api.credentials(**{HEADER: self.secret})
        self.assertEqual(api.post('/api/rpa/agent/portal/claim/').status_code, 204)
        self.make_job()
        r = api.post('/api/rpa/agent/portal/claim/')
        self.assertEqual(r.status_code, 200)
        rid = r.json()['run_id']
        self.assertEqual(api.post(f'/api/rpa/agent/portal/runs/{rid}/heartbeat/').status_code, 200)
        r = api.post(f'/api/rpa/agent/portal/runs/{rid}/report/', {'outcome': 'cart_not_empty'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'needs_person')
        self.assertEqual(api.post(f'/api/rpa/agent/portal/runs/{rid}/heartbeat/').status_code, 409)

    def test_agent_api_needs_rpa_create(self):
        RoleModuleAccess.objects.filter(role='purchasing', module='rpa', action='create').delete()
        api = APIClient()
        api.credentials(**{HEADER: self.secret})
        self.assertEqual(api.post('/api/rpa/agent/portal/claim/').status_code, 403)


class JobAccountTests(_World, TestCase):
    """R8: a job is never created for an inactive or identity-less account."""

    def setUp(self):
        self.build_world('PJA')
        self.bl = BuyList.objects.create(source_kind='upload', created_by=self.buyer)
        BuyListLine.objects.create(buylist=self.bl, seq=1, item=self.items[0], needed_qty=2,
                                   remaining_qty=2, chosen_supplier='565', source_key='pja:1')

    def test_create_job_refuses_inactive_account(self):
        PortalAccount.objects.filter(pk=self.account.pk).update(active=False)
        self.account.refresh_from_db()
        with self.assertRaises(jobs.JobError):
            jobs.create_job(self.bl, portal=self.portal, account=self.account, staff=self.buyer)

    def test_create_job_refuses_blank_identity(self):
        PortalAccount.objects.filter(pk=self.account.pk).update(identity_text='  ')
        self.account.refresh_from_db()
        with self.assertRaises(jobs.JobError):
            jobs.create_job(self.bl, portal=self.portal, account=self.account, staff=self.buyer)


@override_settings(**ON)
class ConcurrentClaimTests(_World, TransactionTestCase):
    """Two devices claiming at once never get the same basket (real transactions, separate
    connections, under the advisory lock)."""

    def setUp(self):
        self.build_world('PQC')
        self.dev_b, _ = issue_device(staff=self.buyer, label='pc b', created_by=self.boss)

    def test_two_claims_never_same_basket(self):
        # two supplier accounts, so both devices may work at once (one cart each)
        acc2 = PortalAccount.objects.create(portal=self.portal, label='second', identity_text='HQ 2')
        _, (a,) = self.make_job()
        _, (b,) = self.make_job(account=acc2)
        baskets = [a, b]
        results, errors = {}, []
        barrier = threading.Barrier(2)

        def worker(name, device):
            try:
                barrier.wait(5)
                claim = queue.claim_next(device)
                results[name] = claim['plan']['basket_id'] if claim else None
            except Exception as exc:   # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n, d))
                   for n, d in (('a', self.dev), ('b', self.dev_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results.values()), sorted(b.pk for b in baskets))
        self.assertEqual(PortalRun.objects.count(), 2)
