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
        self.assertEqual(customer_type(cust, '12'), 'b2b')
        self.assertEqual(customer_type(cust, '16'), 'b2b')
        self.assertEqual(customer_type(cust, '17'), 'b2b')
        self.assertEqual(customer_type(cust, '99'), 'unclassified')
        self.assertEqual(customer_type(cust, '31'), 'unclassified')
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

    def test_latest_channel_ignores_undated_row(self):
        from apps.chronic.task_generator import _latest_channels
        branch = make_branch()
        a = Customer.objects.create(name='أ')
        PurchaseHistory.objects.create(customer=a, branch=branch, doc_code='115', docnumber='1',
                                       invoice_date=timezone.now() - dt.timedelta(days=5),
                                       sales_channel='90', softech_invoice_id='B01-115-d1')
        PurchaseHistory.objects.create(customer=a, branch=branch, doc_code='115', docnumber='2',
                                       invoice_date=None, sales_channel='10',
                                       softech_invoice_id='B01-115-n2')
        self.assertEqual(_latest_channels([a.pk]), {a.pk: '90'})

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


# ── Task 4: item-category consumers read MedicineTypeMap ─────────────────────────

from apps.catalog.models import Item
from apps.config import item_types
from apps.config.models import MedicineTypeMap


def _mk_item(code, mtype, **kw):
    return Item.objects.create(softech_id=code, name=f'ITEM {code}', pack_price=100,
                               is_stockable=True, medicine_type=mtype, **kw)


class _ItemTypeCacheMixin:
    def setUp(self):
        item_types.invalidate_cache()
        super().setUp()

    def tearDown(self):
        item_types.invalidate_cache()
        super().tearDown()


class PlanningExcludesFollowRegistryTests(_ItemTypeCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        item_types.ensure_defaults()
        self.i10 = _mk_item('P10', '10')
        self.i60 = _mk_item('P60', '60')
        self.i70 = _mk_item('P70', '70')

    def _flag_70(self):
        MedicineTypeMap.objects.filter(code='70').update(excluded_from_planning=True)
        item_types.invalidate_cache()

    def test_isr_items_follow_registry(self):
        from apps.purchasing import isr_softech as S
        st = S.rule_settings({'medicine_type': ''})
        codes = ['P10', 'P60', 'P70']
        self.assertEqual(set(S._items(codes, st)), {'P10', 'P70'})
        self._flag_70()
        self.assertEqual(set(S._items(codes, st)), {'P10'})

    def test_seasonality_follows_registry(self):
        import datetime
        from apps.purchasing import seasonality
        from apps.purchasing.models import ItemMonthlySales, ItemSeasonality
        months = seasonality.history_months(datetime.date.today())
        for it in (self.i10, self.i60, self.i70):
            for m in months:
                ItemMonthlySales.objects.create(item_code=it.softech_id, item=it, month=m,
                                                qty=5, regular_qty=5)
        seasonality.compute_all(datetime.date.today())
        self.assertEqual(set(ItemSeasonality.objects.values_list('item__softech_id', flat=True)),
                         {'P10', 'P70'})
        self._flag_70()
        seasonality.compute_all(datetime.date.today())
        self.assertEqual(set(ItemSeasonality.objects.values_list('item__softech_id', flat=True)),
                         {'P10'})

    def test_insights_excluded_items_follow_registry(self):
        from apps.insights.rules import analytics_excluded_items
        ids = set(analytics_excluded_items().values_list('softech_id', flat=True))
        self.assertIn('P60', ids)
        self.assertNotIn('P70', ids)
        self._flag_70()
        ids = set(analytics_excluded_items().values_list('softech_id', flat=True))
        self.assertEqual({'P60', 'P70'} & ids, {'P60', 'P70'})

    def test_isr_screen_default_is_first_medicine_code(self):
        from apps.purchasing import isr_softech as S
        self.assertEqual(S.screen_defaults()['medicine_type'], '10')
        MedicineTypeMap.objects.filter(code='10').update(is_medicine=False)
        item_types.invalidate_cache()
        self.assertEqual(S.screen_defaults()['medicine_type'], '')


class RateWriterSameSetTests(_ItemTypeCacheMixin, TestCase):
    def test_rate_writer_same_set_as_before(self):
        """Seeded registry: the live rate writer's item filter == the old literal filter."""
        from apps.purchasing.models import ItemMonthlySales
        from apps.purchasing.rate_writer import _real_stock_filter
        import datetime
        for code, t in (('R10', '10'), ('R50', '50'), ('R60', '60')):
            it = _mk_item(code, t)
            ItemMonthlySales.objects.create(item_code=code, item=it, month=datetime.date(2026, 1, 1))
        qs = ItemMonthlySales.objects.all()
        old = set(qs.filter(item__is_stockable=True, item__pack_price__gt=0)
                  .exclude(item__medicine_type='60').values_list('item_code', flat=True))
        new = set(_real_stock_filter(qs).values_list('item_code', flat=True))
        self.assertEqual(new, old)
        self.assertEqual(new, {'R10', 'R50'})


class MedicineOnlyConsumersTests(_ItemTypeCacheMixin, TestCase):
    def test_stock_audit_medicine_set_follows_registry(self):
        item_types.ensure_defaults()
        _mk_item('M10', '10')
        _mk_item('M50', '50')
        self.assertEqual(item_types.medicine_codes(), ['10'])
        MedicineTypeMap.objects.filter(code='50').update(is_medicine=True)
        item_types.invalidate_cache()
        self.assertEqual(item_types.medicine_codes(), ['10', '50'])
        got = set(Item.objects.filter(softech_id__in=['M10', 'M50'],
                                      medicine_type__in=item_types.medicine_codes())
                  .values_list('softech_id', flat=True))
        self.assertEqual(got, {'M10', 'M50'})
