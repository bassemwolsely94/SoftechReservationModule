"""
apps/tests/test_analytics_label_cache.py

The analytics channel / person-type label maps (apps/analytics/views.py) are cached per process. They used to be cached
only when non-empty, so with no classification synced every _channel_label() call re-ran the lookups — an N+1 on
/api/analytics/sales/ by_channel (found by the C19 margin-board budget test). An empty map is now kept for
EMPTY_LABEL_TTL seconds; a map with labels until the sync task resets it.
"""
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.analytics import views as av
from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from .factories import make_admin, make_branch, make_customer, make_item

LABEL_TABLES = ('sync_softechpersonclassif', 'sync_softechpersontype', 'softech_ptclassifcode', 'softech_ptcode')


def _reset():
    av._channel_label_cache = None
    av._person_type_label_cache = None
    av._empty_until.clear()


class LabelCacheTests(TestCase):

    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def test_empty_map_is_cached(self):
        av._get_channel_label_map()
        with self.assertNumQueries(0):
            self.assertEqual(av._channel_label('91'), '91')
            self.assertEqual(av._channel_label('15'), '15')
        av._get_person_type_label_map()
        with self.assertNumQueries(0):
            self.assertEqual(av._person_type_label('10'), '10')

    def test_empty_map_expires_so_late_labels_show(self):
        from apps.sync.models import SoftechPersonClassif
        t = [1000.0]
        with mock.patch('time.monotonic', side_effect=lambda: t[0]):
            self.assertEqual(av._channel_label('91'), '91')
            SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='91', ptclassifdescr='عميل نقدى')
            self.assertEqual(av._channel_label('91'), '91')                      # still the empty map
            t[0] += av.EMPTY_LABEL_TTL
            self.assertEqual(av._channel_label('91'), 'عميل نقدى')               # re-read after the TTL

    def test_map_with_labels_is_kept_until_the_sync_reset(self):
        from apps.sync.models import SoftechPersonClassif
        SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode='91', ptclassifdescr='عميل نقدى')
        t = [1000.0]
        with mock.patch('time.monotonic', side_effect=lambda: t[0]):
            self.assertEqual(av._channel_label('91'), 'عميل نقدى')
            t[0] += av.EMPTY_LABEL_TTL * 10
            with self.assertNumQueries(0):
                self.assertEqual(av._channel_label('91'), 'عميل نقدى')
        SoftechPersonClassif.objects.filter(ptclassifcode='91').update(ptclassifdescr='نقدي')
        av._channel_label_cache = None                                           # what the sync task does
        self.assertEqual(av._channel_label('91'), 'نقدي')


class SalesOverviewLabelBudget(TestCase):
    """/api/analytics/sales/ by_channel: the label lookups run once, however many channels there are."""

    def setUp(self):
        _reset()
        self.addCleanup(_reset)
        self.branch = make_branch()
        self.cust = make_customer()
        _, _, self.client_ = make_admin('label_budget_admin')
        self.n = 0

    def _sales(self, channels):
        for _ in range(channels):
            self.n += 1
            p = PurchaseHistory.objects.create(customer=self.cust, branch=self.branch, doc_code='115',
                                               total_amount=Decimal('10'), softech_invoice_id=f'LB-{self.n}',
                                               invoice_date=timezone.now(), sales_channel=f'C{self.n}')
            PurchaseHistoryLine.objects.create(purchase=p, item=make_item(f'LB {self.n}', f'LB{self.n:03d}'),
                                               quantity=Decimal('1'), unit_price=Decimal('10'),
                                               line_total=Decimal('10'), cost_at_sale=Decimal('6'))

    def _label_queries(self):
        _reset()
        with CaptureQueriesContext(connection) as ctx:
            r = self.client_.get('/api/analytics/sales/')
        self.assertEqual(r.status_code, 200)
        return r, sum(1 for q in ctx.captured_queries if any(t in q['sql'] for t in LABEL_TABLES))

    def test_label_lookups_flat_as_channels_grow(self):
        self._sales(2)
        r1, few = self._label_queries()
        self._sales(20)
        r2, many = self._label_queries()
        self.assertEqual(len(r2.data['by_channel']), 22)
        self.assertEqual(many, few, f'label queries grew with channels: {few} → {many}')
        self.assertLessEqual(many, 6)
