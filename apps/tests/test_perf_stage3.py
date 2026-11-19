"""
apps/tests/test_perf_stage3.py

Performance Stage 3 (docs/superpowers/plans/2026-11-19-perf-stage3-polled-screens.md): the polled
screens and the slow summaries answer exactly as before, with a query count that does not grow
with the data. "Before" is the frozen pre-change code in apps/tests/perf_reference/.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

NOW = timezone.now().replace(microsecond=0)


def _at(minutes_ago):
    return NOW - datetime.timedelta(minutes=minutes_ago)


def _count_queries(fn, *args, **kwargs):
    return len(_queries(fn, *args, **kwargs))


def _queries(fn, *args, **kwargs):
    with CaptureQueriesContext(connection) as ctx:
        fn(*args, **kwargs)
    return [q['sql'] for q in ctx.captured_queries]


def _shape(sqls):
    """Query texts with literals removed, for a readable diff when a count grows."""
    import re
    return sorted(re.sub(r"'[^']*'|\b\d+\b", '?', q)[:160] for q in sqls)


# ── 1. GET /api/sync/freshness/ ────────────────────────────────────────────────────────────────

class FreshnessSameAnswerTests(TestCase):
    """New get_freshness == the pre-change get_freshness on the same data, in ≤ 8 queries."""

    def _seed(self, n=1):
        from apps.sync.models import SyncLog, SyncRun
        from apps.batches.models import StockExpirySyncRun
        from apps.procurement.models import ProcurementEngineRun
        from apps.pbx.models import CdrSyncRun
        from apps.finance.models import FinanceSyncRun

        for i in range(n):
            ok = SyncRun.objects.create(status='success')
            bad = SyncRun.objects.create(status='failed')
            SyncRun.objects.filter(pk=ok.pk).update(started_at=_at(30 + i))
            SyncRun.objects.filter(pk=bad.pk).update(started_at=_at(5 + i))
            for t, m in (('stkbal', 12), ('stktrans', 14), ('items', 200), ('itembarcodes', 190),
                         ('localcustomers', 75), ('users', 400)):
                SyncLog.objects.filter(pk=SyncLog.objects.create(sync_run=ok, table_name=t).pk) \
                    .update(created_at=_at(m + i))
            # a later attempt that failed — counts as an attempt, never a success
            for t in ('stkbal', 'items'):
                SyncLog.objects.filter(pk=SyncLog.objects.create(sync_run=bad, table_name=t).pk) \
                    .update(created_at=_at(3 + i))

            # expiry: newest run failed, an older partial counts as success
            p = StockExpirySyncRun.objects.create(status='partial')
            StockExpirySyncRun.objects.filter(pk=p.pk).update(started_at=_at(600 + i), finished_at=_at(590 + i))
            f = StockExpirySyncRun.objects.create(status='failed')
            StockExpirySyncRun.objects.filter(pk=f.pk).update(started_at=_at(60 + i), finished_at=None)
            # purchases: newest is a success without finished_at (falls back to started_at)
            s = ProcurementEngineRun.objects.create(status='success')
            ProcurementEngineRun.objects.filter(pk=s.pk).update(started_at=_at(100 + i), finished_at=None)
            # calls: only a running row (no success at all)
            r = CdrSyncRun.objects.create(status='running')
            CdrSyncRun.objects.filter(pk=r.pk).update(started_at=_at(4 + i))
            # finance: the expense run brought rows, the journal run did not
            fe = FinanceSyncRun.objects.create(status='success', records_synced={'expense_records': 5})
            FinanceSyncRun.objects.filter(pk=fe.pk).update(started_at=_at(300 + i), finished_at=_at(295 + i))
            fj = FinanceSyncRun.objects.create(status='success', records_synced={'journal_entries': 0})
            FinanceSyncRun.objects.filter(pk=fj.pk).update(started_at=_at(200 + i), finished_at=_at(199 + i))

    def _both(self):
        from apps.sync.freshness import get_freshness
        from apps.tests.perf_reference.freshness_before import get_freshness as before
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            return get_freshness(), before()

    def test_same_answer_with_data(self):
        self._seed()
        new, old = self._both()
        self.assertEqual(new, old)
        # sanity: the seed actually exercised the interesting branches
        d = new['domains']
        self.assertTrue(d['stock']['last_run_failed'])
        self.assertNotEqual(d['stock']['last_success_at'], d['stock']['last_attempt_at'])
        self.assertTrue(d['expiry']['last_run_failed'])
        self.assertIsNotNone(d['expiry']['last_success_at'])
        self.assertIsNone(d['calls']['last_success_at'])
        self.assertIsNotNone(d['finance_expenses']['last_success_at'])
        self.assertIsNone(d['finance_journal']['last_success_at'])

    def test_same_answer_empty(self):
        new, old = self._both()
        self.assertEqual(new, old)

    def test_same_answer_for_a_subset(self):
        from apps.sync.freshness import get_freshness
        from apps.tests.perf_reference.freshness_before import get_freshness as before
        self._seed()
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            for wanted in (['stock'], ['sales', 'expiry'], ['calls', 'nope'], ['finance_journal']):
                self.assertEqual(get_freshness(wanted), before(wanted), wanted)

    def test_query_count_is_small_and_flat(self):
        from apps.sync.freshness import get_freshness
        self._seed(1)
        small = _count_queries(get_freshness)
        self._seed(3)
        self.assertEqual(_count_queries(get_freshness), small)
        self.assertLessEqual(small, 8)


# ── 2. GET /api/dashboard/summary/ ─────────────────────────────────────────────────────────────

class DashboardSummarySameAnswerTests(TestCase):
    """New dashboard_summary == the pre-change view on the same data, for a chain-wide admin and a
    branch pharmacist, in a query count that does not grow with the data."""

    @classmethod
    def setUpTestData(cls):
        from apps.tests.factories import make_admin, make_branch, make_branch2, make_pharmacist
        cls.b1, cls.b2 = make_branch(), make_branch2()
        cls.admin = make_admin('perf_dash_admin')
        cls.pharm = make_pharmacist('perf_dash_pharm', branch=cls.b1)

    def _seed(self, n=1):
        from apps.customers.models import Customer, PurchaseHistory
        from apps.followups.models import FollowUpTask
        from apps.reservations.models import Reservation
        from apps.transfers.models import TransferRequest
        from apps.tests.factories import make_item
        today = datetime.date.today()
        staff = self.admin[1]
        base = Reservation.objects.count()
        item = make_item(softech_id=f'PD{base:04d}')
        k = 0
        for _ in range(n):
            for branch in (self.b1, self.b2):
                for status in ('pending', 'available', 'contacted', 'confirmed', 'fulfilled', 'cancelled'):
                    for priority in ('normal', 'urgent', 'chronic'):
                        k += 1
                        r = Reservation.objects.create(
                            item=item, branch=branch, quantity_requested=1, contact_name='عميل',
                            contact_phone='01033333333', created_by=staff, status=status, priority=priority,
                            follow_up_date=today if k % 2 else today + datetime.timedelta(days=3))
                        if k % 3 == 0:
                            Reservation.objects.filter(pk=r.pk).update(
                                updated_at=timezone.now() - datetime.timedelta(days=10))
            cust = Customer.objects.create(name=f'عميل {base}-{k}', phone=f'0101{base:03d}{k:04d}',
                                           churn_segment='high')
            Customer.objects.create(name=f'عميل ح {base}-{k}', phone=f'0102{base:03d}{k:04d}',
                                    churn_segment='critical')
            Customer.objects.create(name=f'حساب {base}-{k}', phone=f'0103{base:03d}{k:04d}',
                                    is_account_placeholder=True)
            for i, (doc, branch, days) in enumerate((('115', self.b1, 1), ('115', self.b2, 2),
                                                      ('30', self.b1, 1), ('115', self.b1, 30))):
                PurchaseHistory.objects.create(
                    customer=cust, branch=branch, softech_invoice_id=f'pd{base}-{k}-{i}', doc_code=doc,
                    total_amount=Decimal('100.25') * (i + 1),
                    invoice_date=timezone.now() - datetime.timedelta(days=days))
            for status, due in (('pending', today), ('pending', today - datetime.timedelta(days=2)),
                                ('called', today - datetime.timedelta(days=1)), ('missed', today)):
                FollowUpTask.objects.create(customer=cust, due_date=due, status=status)
            for status, supplier in (('pending', self.b2), ('sent_to_erp', self.b1), ('approved', self.b1)):
                TransferRequest.objects.create(requesting_branch=self.b2 if supplier == self.b1 else self.b1,
                                               supplying_branch=supplier, created_by=staff, status=status)

    def _call(self, view, user, query=''):
        from rest_framework.test import APIRequestFactory, force_authenticate
        req = APIRequestFactory().get('/api/dashboard/summary/' + query)
        force_authenticate(req, user=user)
        data = view(req).data
        data.pop('generated_at')
        return data

    def _assert_same(self):
        from apps.dashboard.views import dashboard_summary
        from apps.tests.perf_reference.dashboard_before import dashboard_summary as before
        answers = {}
        for user, query in ((self.admin[0], ''), (self.admin[0], f'?branch={self.b2.id}'),
                            (self.pharm[0], ''), (self.pharm[0], f'?branch={self.b2.id}')):
            new, old = self._call(dashboard_summary, user, query), self._call(before, user, query)
            self.assertEqual(new, old, (user.username, query))
            answers[(user.username, query)] = new
        return answers

    def test_same_answer_with_data(self):
        self._seed()
        answers = self._assert_same()
        self.assertGreater(answers[(self.admin[0].username, '')]['reservations']['active_total'], 0)

    def test_same_answer_empty(self):
        self._assert_same()

    def test_query_count_is_small_and_flat(self):
        from apps.dashboard.views import dashboard_summary
        self._seed(1)
        self._call(dashboard_summary, self.admin[0])        # warm the user's profile cache
        small = _queries(self._call, dashboard_summary, self.admin[0])
        self._seed(3)
        big = _queries(self._call, dashboard_summary, self.admin[0])
        self.assertEqual(_shape(big), _shape(small))
        self.assertLessEqual(len(small), 12)


# ── 3. GET /api/batches/stock-expiry/summary/ ──────────────────────────────────────────────────

class StockExpirySummarySameAnswerTests(TestCase):
    """New stock_expiry_summary == the pre-change one on the same mirror, in 2 queries at any size."""

    def _seed(self, n=1):
        from apps.batches.models import StockExpiryBalance
        from apps.batches.store_roles import CLOSED, COSMETICS, LIVE, RETURN, WRITE_OFF
        from apps.tests.factories import make_item
        today = datetime.date.today()
        start = StockExpiryBalance.objects.count()
        offsets = (-40, -1, 0, 10, 29, 30, 60, 89, 90, 150, 179, 180, 400)
        for i in range(n):
            for j, cost in enumerate((Decimal('12.50'), Decimal('3.333'), Decimal('7'), Decimal('0'))):
                code = f'S{(start + i * 10 + j) % 99999:05d}'
                item = make_item(name=f'صنف {code}', softech_id=code)
                type(item).objects.filter(pk=item.pk).update(cost_price=cost)
                for k, (role, branch, store) in enumerate((
                        (LIVE, 'B01', '1'), (LIVE, 'B02', '1'), (RETURN, 'B01', '102'),
                        (WRITE_OFF, 'B02', '103'), (COSMETICS, 'B01', '105'), (CLOSED, 'B01', '110'),
                        ('', 'B02', '9'))):
                    for off in offsets[(j + k) % 4::3]:
                        StockExpiryBalance.objects.create(
                            branch_code=branch, store_code=store, item_code=code, store_role=role,
                            batch_no=f'{i}-{k}-{off}', expiry_date=today + datetime.timedelta(days=off),
                            qty=Decimal('1.25') * (k + 1) + Decimal(off % 7))
            # an item the catalog does not know
            StockExpiryBalance.objects.create(branch_code='B01', store_code='1', item_code=f'X{i:05d}',
                                              store_role=LIVE, expiry_date=today, qty=Decimal('2'))

    def _assert_same(self):
        from apps.batches.stock_expiry import stock_expiry_summary
        from apps.tests.perf_reference.stock_expiry_before import stock_expiry_summary as before
        for kwargs in ({}, {'include_quarantine': True}, {'branch_codes': ['B02']},
                       {'store_codes': ['1', '102']}, {'branch_codes': ['B01'], 'include_quarantine': True}):
            self.assertEqual(stock_expiry_summary(**kwargs), before(**kwargs), kwargs)

    def test_same_answer_with_data(self):
        from apps.batches.stock_expiry import stock_expiry_summary
        self._seed()
        self._assert_same()
        got = stock_expiry_summary(include_quarantine=True)
        self.assertGreater(got['lt_30']['value'], 0)
        self.assertGreater(got['expired']['items'], 0)

    def test_same_answer_empty(self):
        self._assert_same()

    def test_query_count_is_flat(self):
        from apps.batches.stock_expiry import stock_expiry_summary
        self._seed(1)
        small = _count_queries(stock_expiry_summary, include_quarantine=True)
        self._seed(3)
        self.assertEqual(_count_queries(stock_expiry_summary, include_quarantine=True), small)
        self.assertLessEqual(small, 2)


# ── 4a. GET /api/incentives/targets/ ───────────────────────────────────────────────────────────

class IncentiveTargetsBatchTests(TestCase):
    """The targets list computes every attainment in one batch; each one equals the per-target
    attainment() (the pre-change path), and the query count does not grow with the targets."""

    @classmethod
    def setUpTestData(cls):
        from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
        from apps.forecasting.models import BeautyClassRule, ChannelBucketMap as C
        from apps.tests.factories import make_admin, make_branch, make_branch2, make_customer, make_item
        cls.b1, cls.b2 = make_branch(), make_branch2()
        cls.admin = make_admin('perf_tgt_admin')
        for ch, bucket, sub, cust, profit in (('90', C.BUCKET_CASH, '', True, True),
                                              ('91', C.BUCKET_CASH, 'delivery', True, True),
                                              ('92', C.BUCKET_CASH, 'regular', False, True),
                                              ('15', C.BUCKET_CREDIT, '', True, False),
                                              ('20', C.BUCKET_INSURANCE, '', False, True),
                                              ('99', C.BUCKET_EXCLUDE, '', False, False)):
            C.objects.create(person_type='10', channel=ch, bucket=bucket, subtype=sub,
                             counts_customer=cust, include_in_profit=profit)
        BeautyClassRule.objects.create(medicine_type='BB')
        beauty, drug = make_item('كريم', 'PB001'), make_item('دواء', 'PB002')
        type(beauty).objects.filter(pk=beauty.pk).update(medicine_type='BB')
        cust = make_customer()
        today = datetime.date.today()
        cls.start = today.replace(day=1)
        cls.end = (cls.start + datetime.timedelta(days=40)).replace(day=1) - datetime.timedelta(days=1)
        n = 0
        for branch in (cls.b1, cls.b2):
            for ch in ('90', '91', '92', '15', '20', '99'):
                for doc in ('115', '115', '30'):
                    n += 1
                    ph = PurchaseHistory.objects.create(
                        customer=cust, branch=branch, softech_invoice_id=f'pt{n}', doc_code=doc,
                        sales_channel=ch, softech_phcode=f'P{n % 5}' if n % 4 else '',
                        softech_user='U1' if n % 2 else 'U2', total_amount=Decimal('10.10') * n,
                        invoice_date=timezone.make_aware(datetime.datetime.combine(cls.start, datetime.time(13))))
                    for item, q in ((beauty, '2'), (drug, '1.5')):
                        PurchaseHistoryLine.objects.create(
                            purchase=ph, item=item, quantity=Decimal(q), unit_price=Decimal('7.25'),
                            line_total=Decimal('7.25') * Decimal(q) * n, cost_at_sale=Decimal('3.125'))

    def _targets(self, copies=1, branch_only=False):
        from apps.incentives.models import SalesTarget as T
        made = []
        metrics = sorted(T.KPI_RESOLVER_METRICS) + [T.METRIC_REVENUE, T.METRIC_ORDERS]
        for _ in range(copies):
            for metric in metrics:
                scopes = ((T.SCOPE_BRANCH, self.b1, ''), (T.SCOPE_BRANCH, self.b2, ''),
                          (T.SCOPE_CHAIN, None, ''), (T.SCOPE_SALESPERSON, None, 'U1'))
                for scope, branch, user in scopes[:2] if branch_only else scopes:
                    made.append(T.objects.create(scope_type=scope, branch=branch, softech_user=user,
                                                 metric=metric, period_start=self.start,
                                                 period_end=self.end, target_value=Decimal('500')))
            # an older period, so a second (metric, period) group exists
            made.append(T.objects.create(scope_type=T.SCOPE_BRANCH, branch=self.b1, metric='cash',
                                         period_start=self.start - datetime.timedelta(days=31),
                                         period_end=self.start - datetime.timedelta(days=1),
                                         target_value=Decimal('100')))
        return made

    def test_batch_equals_one_by_one(self):
        from apps.incentives.models import SalesTarget
        targets = self._targets()
        batch = SalesTarget.batch_actuals(targets)
        one_by_one = {t.id: t.actual_value() for t in targets}
        self.assertEqual(batch, one_by_one)
        self.assertTrue(any(v for v in batch.values()), 'the seed must produce non-zero actuals')

    def test_list_response_equals_per_target_serialization(self):
        from apps.incentives.models import SalesTarget
        from apps.incentives.serializers import SalesTargetSerializer
        self._targets()
        res = self.admin[2].get('/api/incentives/targets/')
        self.assertEqual(res.status_code, 200)
        rows = res.data['results'] if isinstance(res.data, dict) else res.data
        expected = {t.id: SalesTargetSerializer(t).data for t in SalesTarget.objects.all()}
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            self.assertEqual(dict(row), dict(expected[row['id']]), row['metric'])

    def test_branch_targets_query_count_is_flat(self):
        """Branch targets (what the office runs) cost the same whatever their number. Measured on
        batch_actuals itself: the list endpoint pages, so a bigger list is a different page."""
        from apps.incentives.models import SalesTarget
        small = _queries(SalesTarget.batch_actuals, self._targets(1, branch_only=True))
        big = _queries(SalesTarget.batch_actuals, self._targets(3, branch_only=True))
        self.assertEqual(_shape(big), _shape(small))


# ── 4b. POST /api/audit/screen-view/ ───────────────────────────────────────────────────────────

class ScreenViewTrackingCostTests(TestCase):
    """The tracking POST every screen sends on open stays a handful of queries, however much
    history the table holds."""

    @classmethod
    def setUpTestData(cls):
        from apps.tests.factories import make_pharmacist
        cls.user, cls.profile, cls.client_ = make_pharmacist('perf_sv_pharm')

    def _post(self, route='/reservations'):
        with CaptureQueriesContext(connection) as ctx:
            res = self.client_.post('/api/audit/screen-view/', {'route': route}, format='json')
        self.assertEqual(res.status_code, 204)
        return ctx.captured_queries

    def test_records_once_per_dedup_window(self):
        from apps.audit.models import ScreenView
        self._post(); self._post()
        self.assertEqual(ScreenView.objects.filter(staff=self.profile, route='/reservations').count(), 1)

    def test_query_count_is_small_and_flat(self):
        from apps.audit.models import ScreenView
        first = self._post('/a')
        ScreenView.objects.bulk_create([ScreenView(staff=self.profile, role='pharmacist', route=f'/r{i}')
                                        for i in range(300)])
        later = self._post('/b')
        self.assertEqual(len(later), len(first), [q['sql'][:120] for q in later])
        self.assertLessEqual(len(later), 4)
