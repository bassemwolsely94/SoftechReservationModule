"""
C32 — weekly HQ exception digest (apps/insights/hq_exceptions.py): one adapter per engine (EGP + link +
owner), one row per item × branch across engines at the higher value, ranking, the once-a-week digest,
the company-level gate and the scheduler registration.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.insights import hq_exceptions as HX
from apps.tests.factories import make_admin, make_branch, make_user

SUNDAY = dt.date(2026, 11, 22)
URL = '/api/insights/exceptions/'


def _line(item, branch, value, state='closes_this_month', record=None, supplier='565'):
    return {'item_code': item, 'item_name': f'صنف {item}', 'branch_code': branch, 'value': value, 'state': state,
            'record': record, 'supplier_code': supplier, 'supplier_name': 'مورد', 'closes': '2026-11-30'}


def _calendar(*lines):
    return mock.patch('apps.batches.return_calendar.calendar', return_value={'lines': list(lines)})


def _item(code, name='صنف'):
    from apps.catalog.models import Item
    return Item.objects.create(softech_id=code, name=name, cost_price=Decimal('10'))


def _dead_snapshot(*lines):
    from apps.purchasing.models import DeadStockLine, DeadStockSnapshot, DemandCalculationRun
    run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
    snap = DeadStockSnapshot.objects.create(run=run, as_of=SUNDAY)
    for n, (item, branch, lane, value) in enumerate(lines):
        DeadStockLine.objects.create(snapshot=snap, item=item, branch_code=branch, lane=lane, location='branches_only',
                                     qty=Decimal('1'), value=Decimal(value), rank=n)
    return snap


def _finding(code, branch, value, status='open', item=None):
    from apps.stock_audit.models import StockAuditFinding
    return StockAuditFinding.objects.create(rule_code='R1', dedup_key=f'{code}-{branch}-{value}-{status}',
                                            severity='warning', status=status, branchcode=branch, itemcode=code,
                                            item=item, value_egp=Decimal(value), message_ar='فرق رصيد',
                                            last_seen=timezone.now())


def _receipt(code, branch, value, status='open'):
    from apps.procurement.models import ReceiptCheck
    return ReceiptCheck.objects.create(branch_code=branch, supplier_code='565', doc_number=f'{code}{value}',
                                       doc_date=SUNDAY - dt.timedelta(days=3), item_code=code, qty=Decimal('2'),
                                       value=Decimal(value), flag='overstocked', status=status)


def _recon(status='open', invoice_value='0', payment_amount=None):
    from apps.finance.recon_models import APInvoice, Payment, ReconException, ReconParty
    party = ReconParty.objects.create(party_type='supplier', softech_personcode=f'P{ReconParty.objects.count()}',
                                      name='مورد')
    inv = APInvoice.objects.create(party=party, branchcode='130', doccode='10', docnumber=ReconParty.objects.count(),
                                   docdate=dt.date(2026, 8, 15), doc_value=Decimal(invoice_value),
                                   doc_value_pay=Decimal('0'), party_type='supplier', source_hash='synced')
    pay = None
    if payment_amount is not None:
        pay = Payment.objects.create(party=party, branchcode='130', cheqsno=party.pk, direction='out',
                                     party_type='supplier', voucher_date=dt.date(2026, 9, 18),
                                     amount=Decimal(payment_amount), note='', is_unallocated=True)
    return ReconException.objects.create(party=party, invoice=inv, payment=pay, exception_type='duplicate_payment',
                                         status=status)


class AdapterTests(TestCase):
    """Each adapter: EGP, link, owner and since — and only open items."""

    def _check(self, items, source):
        self.assertTrue(items)
        for i in items:
            self.assertEqual(i['source'], source)
            self.assertGreater(i['egp'], 0)
            self.assertEqual(i['link'], HX.LINKS[source])
            self.assertTrue(i['owner_role'])
            self.assertTrue(i['since'])

    def test_returns_closing_or_missed_only_and_summed_per_item_branch(self):
        with _calendar(_line('A', '130', 100.0), _line('A', '130', 50.0, state='missed'),
                       _line('B', '130', 999.0, state='open'),
                       _line('C', '130', 70.0, record={'status': 'done'})):
            got = HX.returns_items(today=SUNDAY)
        self._check(got, 'returns')
        self.assertEqual([(i['item_code'], i['egp']) for i in got], [('A', 150.0)])
        self.assertEqual(got[0]['owner_role'], HX.OWNER_PURCHASING)

    def test_dead_move_and_return_lanes_without_decisions(self):
        from apps.purchasing.models import DeadStockDecision
        a, b, c, d = _item('DA'), _item('DB'), _item('DC'), _item('DD')
        _dead_snapshot((a, '130', 'move', '500'), (b, '130', 'return', '300'), (c, '130', 'stop', '900'),
                       (d, '130', 'move', '800'))
        DeadStockDecision.objects.create(item=d, branch_code='130', reason='أخرى', until=SUNDAY + dt.timedelta(days=30))
        got = HX.dead_items(today=SUNDAY)
        self._check([dict(i, since=i['since'] or 'x') for i in got], 'dead')
        self.assertEqual([(i['item_code'], i['egp']) for i in got], [('DA', 500.0), ('DB', 300.0)])

    def test_dead_without_a_snapshot_is_empty(self):
        self.assertEqual(HX.dead_items(today=SUNDAY), [])

    def test_audit_open_and_escalated_findings(self):
        _finding('S1', '130', '400')
        _finding('S2', '140', '250', status='escalated')
        _finding('S3', '130', '900', status='dismissed')
        got = HX.audit_items(today=SUNDAY)
        self._check(got, 'audit')
        self.assertEqual([(i['item_code'], i['egp']) for i in got], [('S1', 400.0), ('S2', 250.0)])
        self.assertEqual(got[0]['owner_role'], HX.OWNER_QUALITY)

    def test_recon_money_named_on_the_flag(self):
        _recon(invoice_value='1000', payment_amount='300')        # the payment it names
        _recon(status='investigating', invoice_value='700')        # no payment → the invoice
        _recon(status='resolved', invoice_value='5000')
        got = HX.recon_items(today=SUNDAY)
        self._check(got, 'recon')
        self.assertEqual([i['egp'] for i in got], [700.0, 300.0])
        self.assertEqual(got[0]['owner_role'], HX.OWNER_FINANCE)

    def test_receipts_open_and_return_requested(self):
        _item('RC', 'مشترى')
        _receipt('RC', '130', '600')
        _receipt('RD', '130', '200', status='return_requested')
        _receipt('RE', '130', '900', status='accepted')
        got = HX.receipt_items(today=SUNDAY)
        self._check(got, 'receipts')
        self.assertEqual([(i['item_code'], i['egp']) for i in got], [('RC', 600.0), ('RD', 200.0)])
        self.assertIn('مشترى', got[0]['title'])


class RankingTests(TestCase):

    def test_same_item_branch_in_two_engines_appears_once_at_the_higher_value(self):
        a = _item('X1')
        _dead_snapshot((a, '130', 'move', '400'))
        _receipt('X1', '130', '650')
        _receipt('X1', '140', '100')                              # another branch: a separate row
        with _calendar():
            data = HX.build(today=SUNDAY)
        keys = [r['key'] for r in data['items']]
        self.assertEqual(len(keys), len(set(keys)))
        top = data['items'][0]
        self.assertEqual((top['item_code'], top['branch_code'], top['egp'], top['source']), ('X1', '130', 650.0, 'receipts'))
        self.assertEqual([s['source'] for s in top['sources']], ['receipts', 'dead'])
        self.assertEqual([s['link'] for s in top['sources']], [HX.LINKS['receipts'], HX.LINKS['dead']])
        self.assertEqual(len(data['items']), 2)

    def test_ranked_by_egp_and_capped_at_ten(self):
        for n in range(12):
            _finding(f'F{n}', '130', str(100 + n))
        with _calendar():
            data = HX.build(today=SUNDAY)
        self.assertEqual([r['egp'] for r in data['items']], [float(111 - n) for n in range(10)])
        self.assertEqual([r['rank'] for r in data['items']], list(range(1, 11)))
        self.assertEqual(data['totals']['audit']['count'], 12)

    def test_a_failing_engine_is_reported_and_the_others_still_rank(self):
        _finding('OK', '130', '50')
        with mock.patch.object(HX, 'returns_items', side_effect=RuntimeError('boom')):
            data = HX.build(today=SUNDAY)
        self.assertEqual(data['errors'], ['returns'])
        self.assertEqual([r['item_code'] for r in data['items']], ['OK'])

    def test_rank_pure(self):
        items = [{'key': 'k1', 'source': 'dead', 'egp': 10.0, 'link': 'l1', 'owner_role': 'o'},
                 {'key': 'k1', 'source': 'audit', 'egp': 30.0, 'link': 'l2', 'owner_role': 'o'},
                 {'key': 'k2', 'source': 'recon', 'egp': 20.0, 'link': 'l3', 'owner_role': 'o'}]
        got = HX.rank(items)
        self.assertEqual([(r['key'], r['egp'], r['source']) for r in got], [('k1', 30.0, 'audit'), ('k2', 20.0, 'recon')])
        self.assertEqual([s['source'] for s in got[0]['sources']], ['audit', 'dead'])


class DigestTests(TestCase):

    def setUp(self):
        _finding('DG', '130', '1234')

    def _send(self, today):
        with _calendar():
            return HX.send_weekly(today=today)

    def test_week_starts_on_sunday(self):
        self.assertEqual(HX.week_start(SUNDAY), SUNDAY)
        self.assertEqual(HX.week_start(SUNDAY + dt.timedelta(days=1)), SUNDAY)     # Monday (a new ISO week)
        self.assertEqual(HX.week_start(SUNDAY + dt.timedelta(days=6)), SUNDAY)     # Saturday
        self.assertEqual(HX.week_start(SUNDAY + dt.timedelta(days=7)), SUNDAY + dt.timedelta(days=7))

    def test_once_per_week_to_the_registry_roles(self):
        from apps.notifications.models import Notification
        _, admin, _ = make_admin('hx_admin')
        make_user('hx_pharm', role='pharmacist')               # not an HQ digest role
        self.assertEqual(self._send(SUNDAY), 1)
        self.assertEqual(self._send(SUNDAY + dt.timedelta(days=1)), 0)    # Monday re-run: same Sunday week
        self.assertEqual(self._send(SUNDAY + dt.timedelta(days=7)), 1)    # next week
        n = Notification.objects.filter(notification_type='hq_exception_digest').first()
        self.assertEqual(n.recipient_id, admin.pk)
        self.assertIn('1,234', n.body)
        self.assertEqual(Notification.objects.filter(notification_type='hq_exception_digest').count(), 2)

    def test_setting_list_wins_but_branch_bound_users_never_receive_it(self):
        from apps.config.models import SystemSetting
        make_admin('hx_admin2')
        _, buyer, _ = make_user('hx_buyer', role='purchasing')
        _, pharm, _ = make_user('hx_pharm2', role='pharmacist')
        SystemSetting.objects.update_or_create(key='hq_exception_digest_recipients',
                                               defaults={'label': 'r', 'value': f'[{buyer.pk}, {pharm.pk}]',
                                                         'value_type': 'json'})
        self.assertEqual([p.pk for p in HX.digest_recipients()], [buyer.pk])

    def test_nothing_open_sends_nothing(self):
        from apps.stock_audit.models import StockAuditFinding
        StockAuditFinding.objects.all().delete()
        make_admin('hx_admin3')
        self.assertEqual(self._send(SUNDAY), 0)


class PermissionTests(TestCase):

    def setUp(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        cache.clear()
        self.addCleanup(cache.clear)
        p = mock.patch('apps.batches.return_calendar.calendar', return_value={'lines': []})
        p.start()
        self.addCleanup(p.stop)

    def test_all_branch_roles_read_the_list(self):
        _finding('PM', '130', '77')
        for role in ('admin', 'purchasing', 'supervisor', 'quality_manager'):
            _, _, client = make_user(f'hx_{role}', role=role, access_all=(role == 'admin'))
            r = client.get(URL)
            self.assertEqual(r.status_code, 200, role)
            self.assertEqual(r.json()['items'][0]['link'], HX.LINKS['audit'])

    def test_branch_bound_roles_are_refused_even_with_the_grant(self):
        branch = make_branch('فرع', '130')
        for role in ('pharmacist', 'viewer', 'salesperson', 'delivery'):
            _, _, client = make_user(f'hx_{role}', role=role, branch=branch)
            self.assertEqual(client.get(URL).status_code, 403, role)

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL).status_code, (401, 403))


class SchedulerTests(SimpleTestCase):

    def test_weekly_job_registered_and_classified(self):
        from apps.sync import tasks
        from apps.tests.test_scheduler_locks import SCHEDULER_JOB_GUARDS
        self.assertTrue(callable(tasks._run_hq_exception_digest))
        self.assertEqual(SCHEDULER_JOB_GUARDS['hq_exception_digest'][1], 'apps.insights.hq_exceptions.send_weekly')
