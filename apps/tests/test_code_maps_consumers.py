"""
apps/tests/test_code_maps_consumers.py  (piece 4, Task 3)

Follow-ups, replacement, chronic and customers read channel meanings from the
registry (apps/forecasting/channels.py) instead of their own hard-coded maps.
Labels come from the SOFTECH classif table (SoftechPersonClassif, pt '10').
"""
import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory
from apps.followups.models import FollowUpTask
from apps.forecasting import channels
from apps.sync.models import SoftechPersonClassif
from apps.tests.factories import make_admin, make_branch, make_item

SOFTECH_LABELS = {
    '91': 'عميل نقدى', '90': 'عميل Delivery', '30': 'عميل دائم',
    '10': 'تعاقدات / آجل', '33': 'تعاقد - سداد آجل - خصم يدوي', '11': 'موظفيين شركة الرزيقي',
    '15': 'تأمين صحي',
}


class _ChannelCacheMixin:
    def setUp(self):
        channels.invalidate_cache()
        for code, descr in SOFTECH_LABELS.items():
            SoftechPersonClassif.objects.create(ptcode='10', ptclassifcode=code, ptclassifdescr=descr)
        super().setUp()

    def tearDown(self):
        channels.invalidate_cache()
        super().tearDown()


class FollowUpChannelTests(_ChannelCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.branch = make_branch()
        self.item = make_item('CONCOR 5MG', 'IT501')

    def _task(self, channel):
        return FollowUpTask.objects.create(item=self.item, branch=self.branch, task_type='refill',
                                           status='pending', due_date=timezone.localdate(),
                                           sales_channel=channel)

    def test_followup_label_uses_softech_meaning(self):
        t10 = self._task('10')
        self.assertEqual(t10.sales_channel_label, 'تعاقدات / آجل')
        self.assertFalse(t10.channel_is_favoured)
        self.assertEqual(t10.channel_priority, 3)
        t30 = self._task('30')
        self.assertEqual(t30.sales_channel_label, 'عميل دائم')
        self.assertTrue(t30.channel_is_favoured)
        self.assertEqual(t30.channel_priority, 2)
        t77 = self._task('77')
        self.assertEqual(t77.sales_channel_label, 'غير مصنف (77)')
        self.assertFalse(t77.channel_is_favoured)
        self.assertEqual(t77.channel_priority, 9)

    def test_followup_blank_channel_label_is_dash(self):
        t = self._task('')
        self.assertEqual(t.sales_channel_label, '—')
        self.assertFalse(t.channel_is_favoured)

    def test_priority_sort_order(self):
        # Calls the view's filter step directly: through the HTTP list the global DRF
        # OrderingFilter re-applies the view's default `ordering`, so by_priority is not
        # visible there (pre-existing; reported, not changed in this task).
        from apps.followups.views import FollowUpTaskViewSet
        for code in ('30', '77', '91', '15', '10'):
            self._task(code)
        qs = FollowUpTaskViewSet()._apply_filters(FollowUpTask.objects.all(), {'by_priority': '1'})
        self.assertEqual([t.sales_channel for t in qs], ['91', '30', '10', '15', '77'])

    def test_favoured_only_filter_uses_registry(self):
        for code in ('91', '30', '10', '13'):
            self._task(code)
        _, _, client = make_admin('cm_fav_admin')
        r = client.get('/api/followups/tasks/', {'favoured_only': '1', 'page_size': 50})
        rows = r.data.get('results', r.data) if isinstance(r.data, dict) else r.data
        self.assertEqual(sorted(row['sales_channel'] for row in rows), ['30', '91'])

    def test_filter_meta_channels_from_registry(self):
        self._task('77')
        _, _, client = make_admin('cm_meta_admin')
        r = client.get('/api/followups/tasks/filter-meta/')
        self.assertEqual(r.status_code, 200, r.data)
        by_code = {c['code']: c for c in r.data['channels']}
        self.assertEqual(by_code['10']['label'], 'تعاقدات / آجل')
        self.assertFalse(by_code['10']['favoured'])
        self.assertTrue(by_code['30']['favoured'])
        self.assertEqual(by_code['77']['label'], 'غير مصنف (77)')
        self.assertNotIn('13', by_code)
        codes = [c['code'] for c in r.data['channels']]
        self.assertEqual(codes[-1], '77')

    def test_priority_score_channel_component(self):
        from apps.followups.services import _score_one
        today = timezone.localdate()
        self.assertGreater(_score_one(self._task('30'), today), _score_one(self._task('10'), today))


class ReplacementChannelTests(_ChannelCacheMixin, TestCase):
    def test_replacement_contract_includes_33(self):
        from apps.replacement import config as C
        codes = C.contract_channels()
        self.assertIn('33', codes)
        self.assertEqual(set(codes), {'10', '11', '15', '17', '33'})
        self.assertFalse(hasattr(C, 'CONTRACT_CHANNELS'))
        self.assertFalse(hasattr(C, 'NON_REDEMPTION_CHANNELS'))


class ChronicCustomerTypeTests(_ChannelCacheMixin, TestCase):
    def test_chronic_customer_type(self):
        from apps.chronic.classifier import customer_type
        cust = Customer(name='x')
        self.assertEqual(customer_type(cust, '91'), 'walkin')
        self.assertEqual(customer_type(cust, '90'), 'home_delivery')
        self.assertEqual(customer_type(cust, '11'), 'b2b')
        self.assertEqual(customer_type(cust, '10'), 'b2b')
        self.assertEqual(customer_type(cust, '15'), 'b2b')
        self.assertEqual(customer_type(cust, '30'), 'unclassified')
        self.assertEqual(customer_type(cust, '77'), 'unclassified')
        self.assertEqual(customer_type(cust, None), 'unclassified')
        self.assertEqual(customer_type(cust, ''), 'unclassified')
        self.assertEqual(customer_type(None, None), 'unclassified')

    def test_latest_channel_per_customer(self):
        from apps.chronic.task_generator import _latest_channels
        branch = make_branch()
        a = Customer.objects.create(name='أ')
        b = Customer.objects.create(name='ب')
        Customer.objects.create(name='ج')
        now = timezone.now()
        for n, (cust, ch, days) in enumerate([(a, '10', 9), (a, '91', 1), (b, '90', 3)]):
            PurchaseHistory.objects.create(
                customer=cust, branch=branch, doc_code='115', docnumber=str(n),
                invoice_date=now - dt.timedelta(days=days), sales_channel=ch,
                softech_invoice_id=f'B01-115-{n}')
        self.assertEqual(_latest_channels([a.pk, b.pk]), {a.pk: '91', b.pk: '90'})

    def test_unclassified_is_a_protocol_filter_choice(self):
        from apps.chronic.models import FollowUpProtocol
        self.assertIn(('unclassified', 'غير مصنف'), FollowUpProtocol.CUSTOMER_TYPE_FILTERS)


class CustomerTypeLabelTests(_ChannelCacheMixin, TestCase):
    def test_customer_type_label_blank_and_known(self):
        c = Customer(name='x', softech_ptclassifcode='')
        self.assertEqual(c.customer_type_label, 'عميل')
        self.assertEqual(c.customer_type_color, 'gray')
        c.softech_ptclassifcode = '10'
        self.assertEqual(c.customer_type_label, 'تعاقدات / آجل')
        c.softech_ptclassifcode = '90'
        self.assertEqual(c.customer_type_color, 'blue')
        c.softech_ptclassifcode = '15'
        self.assertEqual(c.customer_type_color, 'green')
        c.softech_ptclassifcode = '77'
        self.assertEqual(c.customer_type_label, 'غير مصنف (77)')
        self.assertEqual(c.customer_type_color, 'amber')
