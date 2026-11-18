"""Task 10: the supplier-portal staff API (/api/rpa/portal/) and the rules it carries.

Views are thin: they call apps/rpa/portal services. The tests here check who may call what
(module rpa, admin-only settings, company-level data, own jobs unless approve), the happy path
from a buy list to approved baskets, and the carried rules: cancelling a basket whose order was
placed needs an explicit, audited confirmation; a recorded basket with a reason still needs a
person; a job whose code discovery stalled says so; the daily Order History check; the pick audit.
"""
import io
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.invoices.models import VendorProfile
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob, PortalLine,
                             PortalRun, SupplierPortal)
from apps.rpa.portal import buylist as bl
from apps.rpa.portal import queue
from apps.supply.models import AvailabilityBatch, AvailabilityLine
from apps.users.models import RoleModuleAccess
from core.middleware.module_access import required

from .factories import make_user

BASE = '/api/rpa/portal/'
PREVIEW = 'apps.supply.execution.preview_order'
BOARD = 'apps.supply.comparison.build_board'


def _preview(lines, **kw):
    rows = [{'item_id': ln['item_id'], 'qty': ln['qty'], 'exceeds_need': False, 'line_value': 10 * ln['qty']}
            for ln in lines]
    return {'lines': rows, 'estimated_value': sum(r['line_value'] for r in rows)}


def _grant(role, *actions, allowed=True):
    for action in actions:
        RoleModuleAccess.objects.update_or_create(role=role, module='rpa', action=action,
                                                  defaults={'is_allowed': allowed})


def _xlsx(rows, name='list.xlsx'):
    wb = Workbook()
    ws = wb.active
    ws.append(['كود الصنف', 'الكمية'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue())


class _World(TestCase):
    @classmethod
    def setUpTestData(cls):
        _grant('purchasing', 'view', 'create')
        _grant('purchasing', 'edit', 'approve', allowed=False)
        _grant('supervisor', 'view', 'create', 'edit', 'approve')
        cls.hq = Branch.objects.filter(kind=Branch.KIND_HQ).first() or Branch.objects.create(
            softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        _, cls.buyer, cls.buyer_c = make_user('pa_buyer', role='purchasing', branch=cls.hq, access_all=True)
        _, cls.buyer2, cls.buyer2_c = make_user('pa_buyer2', role='purchasing', branch=cls.hq, access_all=True)
        _, cls.boss, cls.boss_c = make_user('pa_boss', role='supervisor', branch=cls.hq, access_all=True)
        _, cls.admin, cls.admin_c = make_user('pa_admin', role='admin', branch=cls.hq, access_all=True)
        _, cls.cc, cls.cc_c = make_user('pa_cc', role='call_center', branch=cls.hq, access_all=True)
        cls.portal, _ = SupplierPortal.objects.get_or_create(key='pharma_overseas',
                                                             defaults={'supplier_code': '565'})
        cls.account = PortalAccount.objects.create(portal=cls.portal, label='main', identity_text='HQ 565',
                                                   last_credit={'credit': '1000', 'at': '2026-11-18T08:00:00'})
        cls.vendor = VendorProfile.objects.create(name='Pharma Overseas', softech_personcode='565')
        VendorProfile.objects.create(name='Ibn Sina', softech_personcode='30')
        cls.items = [Item.objects.create(softech_id=f'PA{n}', name=f'ITEM {n}', is_active=True,
                                         pack_price=Decimal('10')) for n in range(6)]

    def _list(self, staff=None, supplier='565', n=2):
        b = BuyList.objects.create(source_kind='upload', created_by=staff or self.buyer)
        for i in range(n):
            BuyListLine.objects.create(buylist=b, seq=i + 1, item=self.items[i], needed_qty=3, remaining_qty=3,
                                       chosen_supplier=supplier, source_key=f'pa:{b.pk}:{i}')
        return b

    def _job(self, staff=None, status='approved', basket_status='ready', keyless=False):
        staff = staff or self.buyer
        b = self._list(staff)
        job = PortalJob.objects.create(portal=self.portal, account=self.account, buylist=b, status=status,
                                       created_by=staff)
        basket = PortalBasket.objects.create(job=job, seq=1, status=basket_status)
        for ln in b.lines.all():
            key = '' if keyless else str(52000 + ln.seq)
            PortalLine.objects.create(basket=basket, buyline=ln, item=ln.item, wanted_qty=ln.remaining_qty,
                                      supplier_key=key, supplier_key_padded=key.zfill(18) if key else '')
        return job, basket


class AccessTests(_World):

    def test_endpoints_require_rpa_module(self):
        job, basket = self._job()
        lst = job.buylist
        calls = [
            ('get', 'buylists/'), ('post', 'buylists/from-pivot/'), ('post', 'buylists/from-isr/'),
            ('post', 'buylists/upload/'), ('get', f'buylists/{lst.pk}/'), ('post', f'buylists/{lst.pk}/pick/'),
            ('post', f'buylists/{lst.pk}/send-other/'), ('get', 'jobs/'), ('post', 'jobs/'),
            ('get', f'jobs/{job.pk}/'), ('post', f'jobs/{job.pk}/approve/'), ('post', f'jobs/{job.pk}/cancel/'),
            ('get', f'discovery/{job.pk}/'), ('post', 'discovery/confirm/'), ('post', 'discovery/none/'),
            ('get', 'baskets/'), ('get', f'baskets/{basket.pk}/'), ('post', f'baskets/{basket.pk}/resolve/'),
            ('post', f'baskets/{basket.pk}/history-check/'), ('get', 'remainders/'), ('get', 'accounts/'),
            ('get', 'portals/'),
        ]
        for method, path in calls:
            r = getattr(self.cc_c, method)(BASE + path, {}, format='json')
            self.assertEqual(r.status_code, 403, f'{method} {path}: {r.status_code}')

    def test_middleware_asks_what_the_views_ask(self):
        self.assertEqual(required('/api/rpa/portal/discovery/confirm/', 'POST'), ('rpa', ('edit',)))
        self.assertEqual(required('/api/rpa/portal/baskets/5/resolve/', 'POST'), ('rpa', ('edit',)))
        self.assertEqual(required('/api/rpa/portal/baskets/5/history-check/', 'POST'), ('rpa', ('edit',)))
        self.assertEqual(required('/api/rpa/portal/jobs/5/approve/', 'POST'), ('rpa', ('create',)))
        self.assertEqual(required('/api/rpa/portal/accounts/5/', 'PATCH'), ('settings', ('edit',)))
        self.assertEqual(required('/api/rpa/portal/portals/pharma_overseas/', 'PATCH'), ('settings', ('edit',)))
        self.assertEqual(required('/api/rpa/portal/accounts/', 'GET'), ('rpa', ('view',)))

    def test_branch_scoped_staff_cannot_read_company_portal_data(self):
        """Portal jobs are company level (HQ): a branch-scoped person holding rpa sees none of it."""
        _grant('pharmacist', 'view', 'create', 'edit', 'approve')
        other = Branch.objects.create(softech_branch_id='170', name='B', kind=Branch.KIND_RETAIL)
        _, _, ph_c = make_user('pa_ph', role='pharmacist', branch=other)
        self._job()
        for path in ('buylists/', 'jobs/', 'baskets/', 'remainders/', 'accounts/'):
            self.assertEqual(ph_c.get(BASE + path).status_code, 403, path)

    def test_non_admin_cannot_change_accounts_or_live(self):
        r = self.boss_c.patch(f'{BASE}accounts/{self.account.pk}/', {'label': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.boss_c.patch(f'{BASE}portals/pharma_overseas/', {'live': True}, format='json')
        self.assertEqual(r.status_code, 403)
        self.portal.refresh_from_db()
        self.assertFalse(self.portal.live)
        # the admin may, and it is audited
        r = self.admin_c.patch(f'{BASE}portals/pharma_overseas/', {'live': True, 'enabled': True,
                                                                  'basket_size': 8}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.portal.refresh_from_db()
        self.assertEqual((self.portal.live, self.portal.enabled, self.portal.basket_size), (True, True, 8))
        log = AuditLog.objects.filter(action='rpa_portal_changed').latest('id')
        self.assertEqual(log.old_data['live'], False)
        self.assertEqual(log.new_data['live'], True)
        r = self.admin_c.patch(f'{BASE}accounts/{self.account.pk}/', {'identity_text': 'HQ 565 new',
                                                                      'active': False}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_account_changed').exists())

    def test_accounts_never_take_a_secret(self):
        for field in ('password', 'cookie', 'token'):
            r = self.admin_c.patch(f'{BASE}accounts/{self.account.pk}/', {field: 'x'}, format='json')
            self.assertEqual(r.status_code, 400, field)
        r = self.admin_c.post(f'{BASE}accounts/', {'portal': 'pharma_overseas', 'label': 'b',
                                                   'identity_text': 'B', 'password': 'p'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.admin_c.post(f'{BASE}accounts/', {'portal': 'pharma_overseas', 'label': 'b',
                                                   'identity_text': 'B'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertNotIn('password', r.json())

    def test_buyer_lists_accounts_with_last_credit(self):
        r = self.buyer_c.get(BASE + 'accounts/')
        self.assertEqual(r.status_code, 200)
        row = next(a for a in r.json() if a['id'] == self.account.pk)
        self.assertEqual(row['last_credit']['credit'], '1000')

    def test_buyer_sees_only_own_jobs_unless_approve(self):
        mine, _ = self._job(self.buyer)
        theirs, theirs_b = self._job(self.buyer2)
        ids = {j['id'] for j in self.buyer_c.get(BASE + 'jobs/').json()}
        self.assertIn(mine.pk, ids)
        self.assertNotIn(theirs.pk, ids)
        self.assertEqual(self.buyer_c.get(f'{BASE}jobs/{theirs.pk}/').status_code, 404)
        self.assertEqual(self.buyer_c.get(f'{BASE}baskets/{theirs_b.pk}/').status_code, 404)
        ids = {j['id'] for j in self.boss_c.get(BASE + 'jobs/').json()}
        self.assertTrue({mine.pk, theirs.pk} <= ids)
        self.assertEqual(self.boss_c.get(f'{BASE}jobs/{theirs.pk}/').status_code, 200)


class FlowTests(_World):

    def test_pick_and_job_flow_happy_path(self):
        with mock.patch(BOARD, return_value={'rows': []}):
            r = self.buyer_c.post(BASE + 'buylists/upload/',
                                  {'file': _xlsx([['PA0', 2.2], ['PA1', 1], ['NOPE', 3], ['PA2', 'abc']])},
                                  format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual({e['item_code'] for e in body['errors']}, {'NOPE', 'PA2'})
        lst_id = body['id']
        with mock.patch(BOARD, return_value={'rows': [{'item_id': self.items[0].pk, 'best': {'supplier': '565'},
                                                       'allocation': [], 'cells': []}]}):
            r = self.buyer_c.get(f'{BASE}buylists/{lst_id}/')
        self.assertEqual(r.status_code, 200)
        lines = r.json()['lines']
        self.assertEqual([ln['needed_qty'] for ln in lines], [3, 1])
        self.assertEqual(lines[0]['ranking'], ['565'])
        for ln in lines:
            r = self.buyer_c.post(f'{BASE}buylists/{lst_id}/pick/', {'line_id': ln['id'], 'supplier': '565'},
                                  format='json')
            self.assertEqual(r.status_code, 200, r.content)
        log = AuditLog.objects.filter(action='rpa_portal_line_picked').latest('id')
        self.assertEqual(log.new_data['chosen_supplier'], '565')
        self.assertIn('chosen_supplier', log.old_data)
        self.assertEqual(log.user_id, self.buyer.pk)

        r = self.buyer_c.post(BASE + 'jobs/', {'buylist_id': lst_id, 'portal': 'pharma_overseas',
                                               'account_id': self.account.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        job_id = r.json()['id']
        self.assertTrue(r.json()['dry_run'])
        with mock.patch(PREVIEW, _preview):
            r = self.buyer_c.post(f'{BASE}jobs/{job_id}/approve/', {'reasons': {}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        job = self.buyer_c.get(f'{BASE}jobs/{job_id}/').json()
        self.assertEqual(job['status'], 'approved')
        self.assertEqual(len(job['baskets']), 1)
        self.assertEqual(job['baskets'][0]['line_count'], 2)

    def test_pick_refused_on_a_closed_list(self):
        lst = self._list()
        lst.status = 'closed'
        lst.save()
        r = self.buyer_c.post(f'{BASE}buylists/{lst.pk}/pick/', {'line_id': lst.lines.first().pk,
                                                                  'supplier': '30'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_pick_service_audits_before_and_after(self):
        lst = self._list(supplier='30')
        line = lst.lines.first()
        bl.pick(line, '565', staff=self.buyer)
        log = AuditLog.objects.filter(action='rpa_portal_line_picked').latest('id')
        self.assertEqual((log.old_data['chosen_supplier'], log.new_data['chosen_supplier']), ('30', '565'))

    def test_send_other_xlsx_is_safe_excel(self):
        lst = self._list(supplier='30', n=1)
        Item.objects.filter(pk=self.items[0].pk).update(name='=HYPERLINK("http://x")')
        r = self.buyer_c.post(f'{BASE}buylists/{lst.pk}/send-other/?format=xlsx', {'supplier': '30'},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))
        ws = load_workbook(io.BytesIO(r.content)).active
        cells = [c.value for row in ws.iter_rows() for c in row]
        self.assertIn('=HYPERLINK("http://x")', cells)
        self.assertTrue(all(c.data_type != 'f' for row in ws.iter_rows() for c in row))

    def test_send_other_text_for_portal_supplier_refused(self):
        lst = self._list(n=1)
        r = self.buyer_c.post(f'{BASE}buylists/{lst.pk}/send-other/', {'supplier': '565'}, format='json')
        self.assertEqual(r.status_code, 400)


class DiscoveryTests(_World):

    def _candidate(self, job, buyline):
        batch = AvailabilityBatch.objects.create(supplier=self.vendor, supplier_name=self.vendor.name,
                                                 source=AvailabilityBatch.SOURCE_PORTAL)
        return AvailabilityLine.objects.create(batch=batch, raw_text='ITEM 0 CAND', supplier_item_code='52001',
                                               match_reason={'buyline_id': buyline.pk, 'job_id': job.pk})

    def test_discovery_confirm_needs_edit(self):
        job, basket = self._job(basket_status='pending', keyless=True)
        line = self._candidate(job, job.buylist.lines.first())
        r = self.buyer_c.post(BASE + 'discovery/confirm/', {'availability_line_id': line.pk}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.buyer_c.post(BASE + 'discovery/none/', {'buyline_id': job.buylist.lines.first().pk},
                              format='json')
        self.assertEqual(r.status_code, 403)
        with mock.patch('apps.rpa.portal.skus.confirm_discovery') as confirm:
            r = self.boss_c.post(BASE + 'discovery/confirm/', {'availability_line_id': line.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        confirm.assert_called_once()

    def test_discovery_view_lists_candidates(self):
        job, _ = self._job(basket_status='pending', keyless=True)
        line = self._candidate(job, job.buylist.lines.first())
        r = self.buyer_c.get(f'{BASE}discovery/{job.pk}/')
        self.assertEqual(r.status_code, 200)
        rows = r.json()['lines']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['candidates'][0]['availability_line_id'], line.pk)
        self.assertFalse(r.json()['needs_person'])

    def test_stalled_discovery_signals_a_person(self):
        job, _ = self._job(basket_status='pending', keyless=True)
        now = timezone.now()
        for _ in range(queue.MAX_FAILED_READS):
            PortalRun.objects.create(kind='discovery', discovery_job=job, started_at=now, finished_at=now,
                                     outcome='timeout')
        self.assertTrue(queue.discovery_state(job)['needs_person'])
        r = self.buyer_c.get(f'{BASE}discovery/{job.pk}/').json()
        self.assertTrue(r['needs_person'])
        self.assertEqual(r['failed_reads'], queue.MAX_FAILED_READS)
        self.assertTrue(self.buyer_c.get(f'{BASE}jobs/{job.pk}/').json()['discovery']['needs_person'])


class ResolveTests(_World):

    def test_resolve_retry_and_link_and_cancel_via_api(self):
        _, basket = self._job(basket_status='needs_person')
        r = self.boss_c.post(f'{BASE}baskets/{basket.pk}/resolve/', {'action': 'retry'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'ready')
        _, b2 = self._job(basket_status='needs_person')
        r = self.boss_c.post(f'{BASE}baskets/{b2.pk}/resolve/', {'action': 'nope'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.boss_c.post(f'{BASE}baskets/{b2.pk}/resolve/', {'action': 'cancel'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        b2.refresh_from_db()
        self.assertEqual(b2.status, 'cancelled')
        _, b3 = self._job(basket_status='needs_person')
        with mock.patch('apps.rpa.portal.recording.record_order', side_effect=lambda b, **kw: b) as rec:
            r = self.boss_c.post(f'{BASE}baskets/{b3.pk}/resolve/',
                                 {'action': 'link_order', 'order_ref': 'SO-77',
                                  'history_lines': [{'sku': '52001', 'qty': 3}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(rec.call_args.kwargs['order_ref'], 'SO-77')
        self.assertEqual(rec.call_args.kwargs['history_lines'], [{'sku': '52001', 'qty': 3}])

    def test_cancel_refused_when_an_order_was_placed(self):
        _, basket = self._job(basket_status='needs_person')
        PortalBasket.objects.filter(pk=basket.pk).update(portal_ref='SO-9', portal_key='pharma_overseas:SO-9',
                                                         needs_person_reason='need_check:SO-9')
        with self.assertRaises(queue.PlacedOrderCancel):
            queue.resolve(basket, staff=self.boss, action='cancel')
        with self.assertRaises(queue.PlacedOrderCancel):      # a confirmation without a reason is not enough
            queue.resolve(basket, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason=' ')
        r = self.boss_c.post(f'{BASE}baskets/{basket.pk}/resolve/', {'action': 'cancel'}, format='json')
        self.assertEqual(r.status_code, 409)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'needs_person')
        r = self.boss_c.post(f'{BASE}baskets/{basket.pk}/resolve/',
                             {'action': 'cancel', 'confirm_placed_order_cancel': True,
                              'reason': 'الطلب أُلغي مع المورد بالتليفون'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'cancelled')
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('id')
        self.assertTrue(log.new_data['confirmed_placed_order_cancel'])
        self.assertEqual(log.new_data['cancelled_portal_ref'], 'SO-9')
        self.assertIn('بالتليفون', log.new_data['reason'])

    def test_recorded_with_reason_still_needs_a_person(self):
        _, basket = self._job(basket_status='recorded')
        _, clean = self._job(basket_status='recorded')
        PortalBasket.objects.filter(pk=basket.pk).update(needs_person_reason='history_found:SO-1')
        basket.refresh_from_db()
        self.assertTrue(queue.needs_person(basket))
        self.assertFalse(queue.needs_person(clean))
        rows = self.boss_c.get(BASE + 'baskets/?needs_person=1').json()
        self.assertEqual([b['id'] for b in rows], [basket.pk])
        self.assertTrue(rows[0]['needs_person'])
        self.assertTrue(self.boss_c.get(f'{BASE}baskets/{basket.pk}/').json()['needs_person'])

    def test_history_check_button_queues_a_read(self):
        _, basket = self._job(basket_status='needs_person')
        r = self.boss_c.post(f'{BASE}baskets/{basket.pk}/history-check/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(PortalRun.objects.filter(basket=basket, kind='history').count(), 1)
        r = self.boss_c.post(f'{BASE}baskets/{basket.pk}/history-check/', {}, format='json')
        self.assertEqual(PortalRun.objects.filter(basket=basket, kind='history').count(), 1)   # idempotent
        _, ready = self._job()
        r = self.boss_c.post(f'{BASE}baskets/{ready.pk}/history-check/', {}, format='json')
        self.assertEqual(r.status_code, 400)


class DailyHistoryCheckTests(_World):

    def test_queues_only_stuck_baskets_that_may_have_ordered(self):
        now = timezone.now()
        _, maybe = self._job(basket_status='needs_person')
        PortalBasket.objects.filter(pk=maybe.pk).update(filled_at=now - timedelta(hours=1),
                                                         needs_person_at=now - timedelta(minutes=30))
        _, never = self._job(basket_status='needs_person')      # no live fill: nothing to read
        _, read = self._job(basket_status='needs_person')       # already read since it got stuck
        PortalBasket.objects.filter(pk=read.pk).update(filled_at=now - timedelta(hours=1),
                                                        needs_person_at=now - timedelta(minutes=30))
        PortalRun.objects.create(basket=read, kind='history', started_at=now - timedelta(minutes=5),
                                 finished_at=now, outcome='history_none')
        _, failed = self._job(basket_status='needs_person')     # the last read failed: read again
        PortalBasket.objects.filter(pk=failed.pk).update(filled_at=now - timedelta(hours=1),
                                                          needs_person_at=now - timedelta(minutes=30))
        PortalRun.objects.create(basket=failed, kind='history', started_at=now - timedelta(minutes=5),
                                 finished_at=now, outcome='timeout')
        self.assertEqual(queue.daily_history_check(), 2)
        queued = set(PortalRun.objects.filter(kind='history', finished_at__isnull=True)
                     .values_list('basket_id', flat=True))
        self.assertEqual(queued, {maybe.pk, failed.pk})
        self.assertEqual(queue.daily_history_check(), 0)             # idempotent

    def test_scheduler_registers_the_daily_check(self):
        from apps.tests.test_scheduler_locks import _registered
        jobs = _registered()
        self.assertIn('rpa_portal_history_check', jobs)
        self.assertIn('rpa_portal_expire_leases', jobs)


class RemaindersTests(_World):

    def test_remainders_list_tried_lines_with_rest(self):
        lst = self._list(n=2)
        first, second = lst.lines.all()
        bl.apply_result(first, supplier_code='565', accepted=1, basket_id=None)
        r = self.buyer_c.get(BASE + 'remainders/')
        self.assertEqual(r.status_code, 200)
        rows = r.json()['rows']
        self.assertEqual([x['id'] for x in rows], [first.pk])
        self.assertIn('565', r.json()['suppliers'])
        self.assertEqual(rows[0]['remaining_qty'], 2)
        self.assertEqual(rows[0]['tried'][0]['supplier'], '565')
