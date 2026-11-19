"""
apps/tests/test_search_rules_viewsets.py — S4 (wildcards everywhere), task 1.

The list endpoints that used the plain DRF SearchFilter now use WildcardSearchFilter:
`*` / `%` are wildcards (parts in typed order), so a pattern plain SearchFilter cannot match
(`ahm*sam`) finds the row. One test per viewset: a matching row is present, a non-matching
row is absent.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.audit.models import AuditLog
from apps.erp.models import ERPTransaction, LocalCustomer
from apps.erp.views import ERPTransactionViewSet, LocalCustomerViewSet
from apps.payments.models import ExternalPayment
from apps.recommendations.models import FrequentlyBoughtTogether, RecommendationEngineRun
from apps.transfers.models import TransferRequest, TransferRequestItem
from apps.transits.models import InTransitTransfer
from apps.users.models import ERPUser

from .factories import make_admin, make_branch, make_item


def _rows(resp):
    assert resp.status_code == 200, resp.content
    data = resp.data.get('results', resp.data) if hasattr(resp.data, 'get') else resp.data
    return list(data)


class WildcardListSearchTests(TestCase):

    def setUp(self):
        self.user, self.profile, self.client = make_admin('s4_admin')
        self.branch = make_branch()

    def _search(self, url, term):
        return _rows(self.client.get(url, {'search': term, 'page_size': 100}))

    def _search_view(self, viewset, term):
        # apps.erp has no URL include (its router is not wired into config/urls.py), so the
        # viewset is exercised directly.
        request = APIRequestFactory().get('/', {'search': term, 'page_size': 100})
        force_authenticate(request, user=self.user)
        return _rows(viewset.as_view({'get': 'list'})(request))

    def test_audit_logs(self):
        AuditLog.objects.create(action='create', user_name='Ahmed Samir')
        AuditLog.objects.create(action='create', user_name='Other Person')
        rows = self._search('/api/audit/logs/', 'ahm*sam')
        self.assertEqual([r['user_name'] for r in rows], ['Ahmed Samir'])

    def test_percent_is_literal_tier(self):
        AuditLog.objects.create(action='create', user_name='A', note='discount 50%')
        AuditLog.objects.create(action='create', user_name='B', note='discount 70')
        rows = self._search('/api/audit/logs/', '50%')
        self.assertEqual([r['user_name'] for r in rows], ['A'])

    def test_erp_transactions(self):
        for n, ref in enumerate(['INV-2026-77', 'ZZZ-1']):
            ERPTransaction.objects.create(
                transaction_id=f's4-{n}', doccode='115', reference_number=ref,
                transaction_date=timezone.now())
        rows = self._search_view(ERPTransactionViewSet, 'inv*77')
        self.assertEqual([r['reference_number'] for r in rows], ['INV-2026-77'])

    def test_erp_local_customers(self):
        LocalCustomer.objects.create(phcode='S4A', name='Mona Adel')
        LocalCustomer.objects.create(phcode='S4B', name='Someone Else')
        rows = self._search_view(LocalCustomerViewSet, 'mon*del')
        self.assertEqual([r['name'] for r in rows], ['Mona Adel'])

    def test_payments(self):
        for name in ('Karim Nabil', 'Nobody Here'):
            ExternalPayment.objects.create(
                branch=self.branch, customer_name=name, method='cash',
                amount=Decimal('10'), created_by=self.user)
        rows = self._search('/api/payments/', 'kar*nab')
        self.assertEqual([r['customer_name'] for r in rows], ['Karim Nabil'])

    def test_recommendations_fbt(self):
        run = RecommendationEngineRun.objects.create(status='success')
        other = make_item('OTHER', 'S4O02')
        for a in (make_item('PANADOL EXTRA', 'S4P01'), make_item('ASPIRIN', 'S4A03')):
            FrequentlyBoughtTogether.objects.create(run=run, item_a=a, item_b=other)
        rows = self._search('/api/recommendations/fbt/', 'pan*xtra')
        self.assertEqual([r['item_a_name'] for r in rows], ['PANADOL EXTRA'])

    def test_transfers_once_even_with_two_lines(self):
        # two lines (the DB forbids the same item twice on one request): the search joins
        # items, so without .distinct() the request would come back twice.
        items = [make_item('PANADOL', 'S4T01'), make_item('ASPIRIN', 'S4T02')]
        other_branch = make_branch('فرع آخر', 'B77')
        hit = TransferRequest.objects.create(
            requesting_branch=self.branch, supplying_branch=other_branch,
            created_by=self.profile, request_number='TR-000123')
        miss = TransferRequest.objects.create(
            requesting_branch=self.branch, supplying_branch=other_branch,
            created_by=self.profile, request_number='TR-000999')
        for item in items:
            TransferRequestItem.objects.create(request=hit, item=item, quantity=1)
            TransferRequestItem.objects.create(request=miss, item=item, quantity=1)
        rows = self._search('/api/transfers/', 'tr*123')
        self.assertEqual([r['id'] for r in rows], [hit.id])

    def test_transits(self):
        for doc in ('125-4471', '999-1'):
            InTransitTransfer.objects.create(
                erp_doc_number=doc, erp_supplying_branch_code='100',
                erp_receiving_branch_code='140', issue_date='2026-05-10',
                transit_status='in_transit', priority='green',
                days_in_transit=1, item_count=1, doc_value=Decimal('1'),
                items_snapshot=[])
        rows = self._search('/api/transits/', '125*71')
        self.assertEqual([r['erp_doc_number'] for r in rows], ['125-4471'])

    def test_users_staff(self):
        make_admin('pharm_ali')
        make_admin('someone_else')
        rows = self._search('/api/users/staff/', 'pha*ali')
        self.assertEqual(len(rows), 1)
        self.assertIn('pharm_ali', str(rows[0]))

    def test_users_erp_users(self):
        ERPUser.objects.create(username='pharm_ali')
        ERPUser.objects.create(username='zed')
        rows = self._search('/api/users/erp-users/', 'pha*ali')
        self.assertEqual([r['username'] for r in rows], ['pharm_ali'])


class ToManySearchFieldTests(TestCase):
    """S4 final review item 3: a search field that crosses a to-many relation
    (transfers' `items__item__name`, ERP's `lines__item_code`) must give ONE row per parent with
    its best tier — not one row per matching line tier, and not an inflated count."""

    def setUp(self):
        self.user, self.profile, self.client = make_admin('s4_tomany')
        self.branch = make_branch()
        self.other = make_branch('فرع آخر', 'B78')
        self.seq = 0

    def _transfer(self, number, *names):
        tr = TransferRequest.objects.create(
            requesting_branch=self.branch, supplying_branch=self.other,
            created_by=self.profile, request_number=number)
        for name in names:
            self.seq += 1
            TransferRequestItem.objects.create(request=tr, item=make_item(name, f'S4M{self.seq:02d}'), quantity=1)
        return tr

    def test_two_line_transfer_matching_at_two_tiers_is_one_row(self):
        # line 1 = the literal text (tier 0), line 2 = the words in any order only (tier 2)
        tr = self._transfer('TR-S4-1', 'PANADOL EXTRA', 'PANADOL COLD EXTRA')
        self._transfer('TR-S4-2', 'ASPIRIN')
        resp = self.client.get('/api/transfers/', {'search': 'panadol extra', 'page_size': 100})
        rows = _rows(resp)
        self.assertEqual([r['id'] for r in rows], [tr.id])
        if hasattr(resp.data, 'get') and 'count' in resp.data:
            self.assertEqual(resp.data['count'], 1)

    def test_parent_takes_its_best_tier(self):
        any_order = self._transfer('TR-S4-3', 'EXTRA PANADOL')          # any order only
        literal = self._transfer('TR-S4-4', 'ASPIRIN', 'PANADOL EXTRA')  # literal on line 2
        from apps.catalog.wildcard import filter_and_rank
        qs = filter_and_rank(TransferRequest.objects.order_by('id'), 'panadol extra',
                             ['request_number', 'items__item__name'])
        self.assertEqual([(t.id, t._wild_rank) for t in qs], [(literal.id, 0), (any_order.id, 2)])

    def test_erp_transaction_with_lines_at_two_tiers_is_one_row(self):
        hit = ERPTransaction.objects.create(transaction_id='s4-tm-1', doccode='115',
                                            transaction_date=timezone.now())
        miss = ERPTransaction.objects.create(transaction_id='s4-tm-2', doccode='115',
                                             transaction_date=timezone.now())
        for code in ('AB CD', 'CD AB'):                                  # literal + any order
            hit.lines.create(item_code=code, item_name='x', store_code='1')
        miss.lines.create(item_code='ZZ', item_name='x', store_code='1')
        request = APIRequestFactory().get('/', {'search': 'ab cd', 'page_size': 100})
        force_authenticate(request, user=self.user)
        rows = _rows(ERPTransactionViewSet.as_view({'get': 'list'})(request))
        self.assertEqual([r['transaction_id'] for r in rows], ['s4-tm-1'])

    def test_single_valued_fields_keep_the_plain_join_free_path(self):
        from apps.catalog.models import Item
        from apps.catalog.wildcard import crosses_to_many
        self.assertFalse(any(crosses_to_many(Item, f) for f in ('name', 'name_scientific', 'category__name')))
        self.assertTrue(crosses_to_many(TransferRequest, 'items__item__name'))
        self.assertTrue(crosses_to_many(ERPTransaction, 'lines__item_code'))
        from apps.catalog.wildcard import filter_and_rank
        sql = str(filter_and_rank(Item.objects.all(), 'panadol extra', ['name']).query)
        self.assertNotIn(' IN (SELECT', sql)
