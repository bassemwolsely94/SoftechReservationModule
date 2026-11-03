"""PIC Analytics — the whitelisted server-side `ordering` of the paged lists (sortable tables batch S0):
overdue customers, missed-call rows, new numbers and labelled numbers. The sort covers ALL rows, not the page."""
from datetime import date as D
from unittest import mock

from django.test import SimpleTestCase

from apps.customers.models import Customer
from apps.pic_analytics.models import PhoneLabel
from apps.pic_analytics.queries.missed import missed_rows
from apps.pic_analytics.queries.pics import pic_rows
from apps.pic_analytics.queries.ordering import parse_ordering, sort_items
from apps.pic_analytics.queries.retention import overdue_list
from apps.tests.test_pic_api import ApiBase, url
from apps.tests.test_pic_queries_calls import CallBase
from apps.tests.test_pic_queries_overview import Base
from apps.tests.test_pic_queries_retention import RetBase


class OrderingHelperTests(SimpleTestCase):

    def test_parse(self):
        self.assertEqual(parse_ordering('', {'net'}), (None, False))
        self.assertEqual(parse_ordering('net', {'net'}), ('net', False))
        self.assertEqual(parse_ordering('-net', {'net'}), ('net', True))
        with self.assertRaises(ValueError):
            parse_ordering('cost', {'net'})
        with self.assertRaises(ValueError):
            parse_ordering('-pk', {'net'})

    def test_empty_last_in_both_directions_and_stable(self):
        rows = [{'i': 0, 'v': 5}, {'i': 1, 'v': None}, {'i': 2, 'v': 5}, {'i': 3, 'v': ''}, {'i': 4, 'v': 9}]
        asc = [r['i'] for r in sort_items(rows, lambda r: r['v'])]
        desc = [r['i'] for r in sort_items(rows, lambda r: r['v'], desc=True)]
        self.assertEqual(asc, [0, 2, 4, 1, 3])             # ties keep the original order
        self.assertEqual(desc, [4, 0, 2, 1, 3])

    def test_text_is_case_insensitive(self):
        self.assertEqual(sort_items(['b', 'A', 'c'], lambda s: s), ['A', 'b', 'c'])


class OverdueOrderingTests(RetBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Customer.objects.create(name='متأخر', softech_pic='O1', softech_id='R-O1', phone='01000000011')
        Customer.objects.create(name='منتظم', softech_pic='O2', softech_id='R-O2', phone='01000000012')
        for d in (D(2026, 9, 1), D(2026, 9, 11), D(2026, 9, 21), D(2026, 10, 8)):
            cls.fact('O1', d, cls.ba, net=500)              # net 2000, last visit 10-08, cycle ~12
        for d in (D(2026, 10, 6), D(2026, 10, 16), D(2026, 10, 26)):
            cls.fact('O2', d, cls.bb, net=50)               # net 150, last visit 10-26, cycle 10

    def pics(self, **kw):
        kw.setdefault('page', 1)
        with mock.patch('apps.pic_analytics.queries.retention.setting', return_value=0.1):     # both overdue
            return [r['pic'] for r in overdue_list(self.flt(), self.mgmt, **kw)['rows']]

    def test_orderings(self):
        self.assertEqual(self.pics(), ['O1', 'O2'])                                   # default: biggest net first
        self.assertEqual(self.pics(ordering='lifetime_net'), ['O2', 'O1'])
        self.assertEqual(self.pics(ordering='-lifetime_net'), ['O1', 'O2'])
        self.assertEqual(self.pics(ordering='last_visit'), ['O1', 'O2'])
        self.assertEqual(self.pics(ordering='-last_visit'), ['O2', 'O1'])
        self.assertEqual(self.pics(ordering='-cycle_days'), ['O1', 'O2'])
        self.assertEqual(self.pics(ordering='days_overdue'), ['O2', 'O1'])            # O2 visited more recently
        self.assertEqual(self.pics(ordering='name'), ['O1', 'O2'])
        self.assertEqual(self.pics(ordering='-name'), ['O2', 'O1'])

    def test_sorts_all_rows_before_paging(self):
        self.assertEqual(self.pics(page=1, page_size=1, ordering='lifetime_net'), ['O2'])
        self.assertEqual(self.pics(page=2, page_size=1, ordering='lifetime_net'), ['O1'])

    def test_bad_ordering_refused(self):
        with self.assertRaises(ValueError):
            overdue_list(self.flt(), self.mgmt, 1, ordering='phone')


class MissedOrderingTests(CallBase):

    def setUp(self):
        # lifetime net to 2026-10-31: N1 350, R1 100, RE 45; the last call has no known number
        self.call(D(2026, 10, 5), 'N1', 'inbound', 'abandoned', key='1000000001', hh=9)
        self.call(D(2026, 10, 7), 'R1', 'inbound', 'abandoned', key='1000000002', hh=9)
        self.call(D(2026, 10, 9), 'RE', 'inbound', 'abandoned', key='1000000003', hh=9)
        self.call(D(2026, 10, 11), '', 'inbound', 'abandoned', key='1000000004', hh=9)

    def rows(self, **kw):
        return missed_rows(self.flt(), self.mgmt, False, 1, **kw)['rows']

    def names(self, **kw):
        return [r['customer_name'] or '-' for r in self.rows(**kw)]

    def test_default_is_lifetime_net_desc(self):
        self.assertEqual(self.names(), ['جديد', 'عائد', 'مُعاد', '-'])

    def test_orderings(self):
        self.assertEqual(self.names(ordering='lifetime_net'), ['مُعاد', 'عائد', 'جديد', '-'])    # empty last
        self.assertEqual(self.names(ordering='-lifetime_net'), ['جديد', 'عائد', 'مُعاد', '-'])
        self.assertEqual(self.names(ordering='call_at'), ['جديد', 'عائد', 'مُعاد', '-'])
        self.assertEqual(self.names(ordering='-call_at'), ['-', 'مُعاد', 'عائد', 'جديد'])
        self.assertEqual(self.names(ordering='-last_purchase'), ['جديد', 'مُعاد', 'عائد', '-'])   # 10-20, 10-12, 10-10
        self.assertEqual(self.names(ordering='last_purchase'), ['عائد', 'مُعاد', 'جديد', '-'])
        self.assertEqual(self.names(ordering='customer_name')[-1], '-')                           # blank name last
        segs = [r['segment'] for r in self.rows(ordering='segment') if r['segment']]
        self.assertEqual(segs, sorted(segs))

    def test_sorts_all_rows_before_paging(self):
        row = missed_rows(self.flt(), self.mgmt, False, 2, 1, ordering='call_at')['rows'][0]
        self.assertEqual(row['customer_name'], 'عائد')

    def test_bad_ordering_refused(self):
        with self.assertRaises(ValueError):
            missed_rows(self.flt(), self.mgmt, False, 1, ordering='customer_number')


class OrderingApiTests(ApiBase):

    def test_missed_rows_ordering_and_400(self):
        self.call(D(2026, 10, 8), 'N1', 'inbound', 'abandoned', key='1000000001')
        asc = self.admin_c.get(url('calls/missed/rows/', '&ordering=call_at')).json()['rows']
        desc = self.admin_c.get(url('calls/missed/rows/', '&ordering=-call_at')).json()['rows']
        self.assertEqual(len(asc), 2)
        self.assertEqual([r['call_id'] for r in asc], [r['call_id'] for r in reversed(desc)])
        self.assertEqual(self.admin_c.get(url('calls/missed/rows/', '&ordering=pic')).status_code, 400)

    def test_overdue_ok_and_400(self):
        self.assertEqual(self.admin_c.get(url('retention/overdue/', '&ordering=-lifetime_net')).status_code, 200)
        self.assertEqual(self.admin_c.get(url('retention/overdue/', '&ordering=phone')).status_code, 400)

    def test_numbers_ordering_across_pages(self):
        self.call(D(2026, 10, 8), '', 'inbound', 'abandoned', key='1000000010')       # ...010 now has 2 inbound, ...020 has 1
        rows = self.admin_c.get(url('numbers/', '&ordering=-calls_in')).json()['rows']
        self.assertEqual([r['calls_in'] for r in rows], [2, 1])
        first = self.admin_c.get(url('numbers/', '&ordering=calls_in&page=1&page_size=1')).json()
        second = self.admin_c.get(url('numbers/', '&ordering=calls_in&page=2&page_size=1')).json()
        self.assertEqual((first['count'], first['rows'][0]['calls_in'], second['rows'][0]['calls_in']), (2, 1, 2))
        self.assertTrue(all('number_id' in r and 'phone_key' not in r for r in rows))
        self.assertEqual(self.admin_c.get(url('numbers/', '&ordering=number')).status_code, 400)   # masked: not sortable

    def test_labels_ordering(self):
        PhoneLabel.objects.create(phone_key='1000000010', label='supplier', note='ب')
        PhoneLabel.objects.create(phone_key='1000000020', label='staff', note='أ')
        got = self.admin_c.get(url('numbers/labels/', '&ordering=note')).json()
        self.assertEqual([r['note'] for r in got['rows']], ['أ', 'ب'])
        got = self.admin_c.get(url('numbers/labels/', '&ordering=-note&page=1&page_size=1')).json()
        self.assertEqual((got['count'], got['rows'][0]['note']), (2, 'ب'))
        self.assertEqual(self.admin_c.get(url('numbers/labels/', '&ordering=phone_key')).status_code, 400)


class PicListOrderingTests(Base):
    """The PIC list keeps its own `order` param; S0 added invoices / units / basket_net / gp to its whitelist."""

    def first(self, access, order):
        return [r['pic'] for r in pic_rows(self.flt(), access, order, 1)['rows']]

    def test_new_columns(self):
        self.assertEqual(self.first(self.mgmt, '-invoices')[0], 'N1')
        self.assertEqual(self.first(self.mgmt, '-basket_net'), ['N1', 'R1', 'RE'])     # 175, 80, 40
        self.assertEqual(self.first(self.mgmt, 'basket_net'), ['RE', 'R1', 'N1'])
        self.assertEqual(self.first(self.mgmt, 'gp')[0], 'RE')                           # gp 20 < 30 < 140

    def test_branch_manager_cannot_sort_by_profit(self):
        self.assertEqual(self.first(self.mgr, 'gp'), self.first(self.mgr, '-net'))      # silently the default order
