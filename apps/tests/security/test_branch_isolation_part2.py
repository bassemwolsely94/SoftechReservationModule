"""
Batch 5 part 2 — the same cross-branch isolation contract as test_branch_isolation.py, for the
branch-level modules left open after part 1: shortage lists, stock count sessions, stock batches,
expiry disposals and operational tasks.

A record lives in branch A; a branch-B user whose role the matrix DOES grant on the module must not
see it in a list (also not via ?branch=A), open it (404) or act on it (404, row unchanged), while
the same calls from branch A still work.
"""
import datetime
from decimal import Decimal

from django.test import override_settings

from apps.tests.factories import make_user

from .fixtures import bearer_client
from .test_branch_isolation import _IsolationBase, _ids


class ShortageListIsolation(_IsolationBase):
    list_url = '/api/shortage/lists/'
    detail_url = '/api/shortage/lists/{pk}/'
    movable = False            # no generic PATCH on a list (Batch 4, Z-10b)
    extra_grants = {'shortage': ['view', 'create', 'edit', 'approve', 'delete']}
    actions = (
        ('POST', '/api/shortage/lists/{pk}/add-item/', {'raw_name': 'ISO ITEM 10mg'}),
        ('POST', '/api/shortage/lists/{pk}/submit/', {}),
        ('POST', '/api/shortage/lists/{pk}/resolve/', {}),
        ('GET', '/api/shortage/lists/{pk}/export/', None),
        ('GET', '/api/shortage/lists/{pk}/export-excel/', None),
        ('DELETE', '/api/shortage/lists/{pk}/', None),
    )

    def make_record(self, branch):
        from apps.shortage.models import ShortageList
        return ShortageList.objects.create(branch=branch, title='ISO-CANARY')

    def test_create_for_foreign_branch_refused(self):
        r = self.b.post(self.list_url, {'branch': self.branch_a.pk, 'title': 'x'}, format='json')
        self.assertEqual(r.status_code, 403, r.content[:300])
        r = self.b.post(self.list_url, {'branch': self.branch_b.pk, 'title': 'own'}, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])

    def test_aggregate_hides_other_branch(self):
        self.record.items.create(raw_name='ISO-AGG-CANARY', quantity_needed=3)
        for params in ({}, {'branch_ids': str(self.branch_a.pk)}):
            r = self.b.get('/api/shortage/lists/aggregate/', {'status': '', **params})
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertNotIn('ISO-AGG-CANARY', r.content.decode('utf-8'))
        r = self.a.get('/api/shortage/lists/aggregate/', {'status': ''})
        self.assertIn('ISO-AGG-CANARY', r.content.decode('utf-8'))

    def test_ocr_on_foreign_list_is_404(self):
        r = self.b.post(f'/api/shortage/lists/{self.record.pk}/ocr/', {}, format='multipart')
        self.assertEqual(r.status_code, 404, r.content[:300])
        r = self.b.post('/api/shortage/lists/987654321/ocr/', {}, format='multipart')
        self.assertEqual(r.status_code, 404, r.content[:300])


class StockCountSessionIsolation(_IsolationBase):
    list_url = '/api/stockcount/sessions/'
    detail_url = '/api/stockcount/sessions/{pk}/'
    movable = False            # sessions are never edited in place
    extra_grants = {'stockcount': ['view', 'create', 'edit', 'finalize', 'delete', 'export']}
    actions = (
        ('GET', '/api/stockcount/sessions/{pk}/snapshots/', None),
        ('GET', '/api/stockcount/sessions/{pk}/variance-report/', None),
        ('POST', '/api/stockcount/sessions/{pk}/close/', {}),
        ('DELETE', '/api/stockcount/sessions/{pk}/', None),
    )

    def make_record(self, branch):
        from apps.stockcount.models import StockCountSession
        return StockCountSession.objects.create(name='ISO-CANARY', branch_code=branch.softech_branch_id)

    def test_create_for_foreign_branch_refused(self):
        body = {'name': 'x', 'mode': 'full', 'branch_code': self.branch_a.softech_branch_id}
        r = self.b.post(self.list_url, body, format='json')
        self.assertEqual(r.status_code, 403, r.content[:300])

    def test_list_filter_cannot_widen(self):
        r = self.b.get(self.list_url, {'branch_code': self.branch_a.softech_branch_id})
        self.assertNotIn(self.record.pk, _ids(r))


class StockBatchIsolation(_IsolationBase):
    list_url = '/api/batches/'
    detail_url = '/api/batches/{pk}/'
    movable = False            # read-only viewset; batches move through quarantine only
    extra_grants = {'catalog': ['view', 'edit', 'approve'], 'approvals': ['create', 'approve']}
    def test_quarantine_foreign_batch_is_404(self):
        # (own-branch positive control needs the batch_quarantine approval workflow seeded —
        # out of scope here; the scope itself is get_object() on the scoped queryset)
        r = self.b.post(f'/api/batches/{self.record.pk}/quarantine/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 404, r.content[:300])
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_quarantined)

    def make_record(self, branch):
        from apps.batches.models import StockBatch
        from apps.tests.factories import make_item
        item = make_item(softech_id=f'IS{branch.softech_branch_id}', name='ISO-CANARY')
        return StockBatch.objects.create(
            item=item, branch=branch, batch_number='ISO-1',
            expiry_date=datetime.date.today() + datetime.timedelta(days=40),
            original_qty=Decimal('5'), current_qty=Decimal('5'))

    def test_alerts_and_near_expiry_hide_other_branch(self):
        r = self.b.get('/api/batches/near-expiry/', {'days': 90})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn('ISO-CANARY', r.content.decode('utf-8'))
        r = self.b.get('/api/batches/near-expiry/', {'days': 90, 'branch': self.branch_a.pk})
        self.assertNotIn('ISO-CANARY', r.content.decode('utf-8'))
        r = self.b.get('/api/batches/fefo/', {'item': self.record.item_id, 'branch': self.branch_a.pk})
        self.assertNotIn('ISO-1', r.content.decode('utf-8'))


class ExpiryDisposalIsolation(_IsolationBase):
    list_url = '/api/batches/stock-expiry/disposal/'
    detail_url = None          # no detail route — the status action is the only per-row call
    extra_grants = {'catalog': ['view', 'edit', 'approve']}

    def setUp(self):
        from core.middleware import module_access
        module_access.clear_cache()
        self.record = self.make_record(self.branch_a)
        self.a = bearer_client(self.user_a)
        self.b = bearer_client(self.user_b)

    def make_record(self, branch):
        from apps.batches.models import ExpiryDisposalRecord
        return ExpiryDisposalRecord.objects.create(
            item_code='999001', branch_code=branch.softech_branch_id, decision='return_supplier')

    def _rows(self, resp):
        data = resp.json()
        rows = data.get('items', []) if isinstance(data, dict) else data
        return {r.get('id') for r in rows if isinstance(r, dict)}

    def test_list_hides_other_branch(self):
        for params in ({}, {'branch': self.branch_a.softech_branch_id}):
            r = self.b.get(self.list_url, params)
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertNotIn(self.record.pk, self._rows(r))
        self.assertIn(self.record.pk, self._rows(self.a.get(self.list_url)))

    def test_own_branch_still_sees_it(self):
        self.assertIn(self.record.pk, self._rows(self.a.get(self.list_url)))

    def test_detail_is_404_for_other_branch(self):
        r = self.b.post(f'{self.list_url}{self.record.pk}/status/', {'status': 'cancelled'},
                        format='json')
        self.assertEqual(r.status_code, 404, r.content[:300])
        self.record.refresh_from_db()
        self.assertNotEqual(self.record.status, 'cancelled')

    def test_unknown_id_is_404_not_500(self):
        r = self.a.post(f'{self.list_url}987654321/status/', {'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_actions_refused_without_side_effects(self):
        pass

    def test_edit_cannot_move_record_to_a_foreign_branch(self):
        pass

    def test_create_for_foreign_branch_refused(self):
        r = self.b.post(self.list_url, {'item_code': '999002', 'branch_code': self.branch_a.softech_branch_id,
                                         'decision': 'return_supplier'}, format='json')
        self.assertEqual(r.status_code, 403, r.content[:300])


class TaskIsolation(_IsolationBase):
    list_url = '/api/tasks/'
    detail_url = '/api/tasks/{pk}/'
    actions = (
        ('POST', '/api/tasks/{pk}/complete/', {}),
        ('GET', '/api/tasks/{pk}/assignments/', None),
        ('GET', '/api/tasks/{pk}/items/', None),
        ('POST', '/api/tasks/{pk}/items/', {'title': 'x'}),
        ('GET', '/api/tasks/{pk}/messages/', None),
        ('POST', '/api/tasks/{pk}/messages/', {'body': 'x'}),
        ('GET', '/api/tasks/{pk}/attachments/', None),
        ('GET', '/api/tasks/{pk}/audit/', None),
    )

    def make_record(self, branch):
        from apps.tasks.models import OperationalTask
        return OperationalTask.objects.create(title='ISO-CANARY', branch=branch,
                                              created_by=self.user_a.staff_profile)

    def test_dashboard_hides_other_branch(self):
        r = self.b.get('/api/tasks/dashboard/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn('ISO-CANARY', r.content.decode('utf-8'))
        r = self.b.get('/api/tasks/dashboard/', {'branch': self.branch_a.pk})
        self.assertNotIn('ISO-CANARY', r.content.decode('utf-8'))

    def test_assignee_in_other_branch_still_sees_it(self):
        """A task assigned to someone in another branch is theirs to work on."""
        self.record.assigned_to = self.user_b.staff_profile
        self.record.save(update_fields=['assigned_to'])
        self.assertIn(self.record.pk, _ids(self.b.get(self.list_url)))
        self.assertEqual(self.b.get(self.detail_url.format(pk=self.record.pk)).status_code, 200)

    def test_all_branch_task_visible_to_everyone(self):
        """branch = NULL is a «جميع الفروع» task — it is meant for every branch."""
        from apps.tasks.models import OperationalTask
        t = OperationalTask.objects.create(title='ISO-ALL', branch=None,
                                           created_by=self.user_a.staff_profile)
        self.assertIn(t.pk, _ids(self.b.get(self.list_url)))

    def test_supervisor_sees_every_branch(self):
        sup = make_user('iso_task_sup', role='supervisor', branch=self.branch_b)[0]
        self.assertIn(self.record.pk, _ids(bearer_client(sup).get(self.list_url)))


@override_settings(RBAC_ENFORCEMENT='enforce', POS_OFFERS_EXECUTION_ENABLED=True)
class OffersOnForeignOrderTests(_IsolationBase):
    """offers/apply-to-order looked the POS order up by bare pk — the one way around the part-1
    POS scoping. It must 404 for another branch's order, and evaluate may not price for one."""
    list_url = '/api/pos-orders/'      # the base list/detail checks re-run on POS orders
    detail_url = '/api/pos-orders/{pk}/'
    movable = False
    extra_grants = {'pos': ['view', 'create', 'edit']}

    def make_record(self, branch):
        from apps.pos_orders.models import SoftechSalesOrder
        return SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode=branch.softech_branch_id, store_code='101',
            channel='cash', doc_kind='sale', customer_name='ISO-CANARY')

    def test_apply_to_foreign_order_is_404(self):
        before = self.snapshot()
        r = self.b.post('/api/offers/apply-to-order/', {'order': self.record.pk}, format='json')
        self.assertEqual(r.status_code, 404, r.content[:300])
        self.assertEqual(self.snapshot(), before)
        own = self.a.post('/api/offers/apply-to-order/', {'order': self.record.pk, 'commit': False},
                          format='json')
        self.assertNotIn(own.status_code, (403, 404), own.content[:300])

    def test_evaluate_for_foreign_branch_refused(self):
        body = {'basket': [{'softech_id': 'X1', 'qty': 1, 'unit_price': 10}]}
        r = self.b.post('/api/offers/evaluate/', {**body, 'branch': self.branch_a.pk}, format='json')
        self.assertEqual(r.status_code, 403, r.content[:300])
        r = self.b.post('/api/offers/evaluate/', {**body, 'branch': self.branch_b.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])


@override_settings(RBAC_ENFORCEMENT='enforce')
class AnalyticsBranchScopeTests(_IsolationBase):
    """Analytics view is granted to branch roles (pharmacist, viewer). They see their own
    branches' numbers only — never another branch's via ?branches= — and the cross-branch
    P&L / capital boards stay with the all-branch roles (owner decision B-1)."""
    list_url = '/api/analytics/sales/'    # switches the base fixtures on; base tests overridden
    detail_url = '/api/analytics/sales/'
    extra_grants = {'analytics': ['view']}

    def make_record(self, branch):
        from django.utils import timezone
        from apps.customers.models import PurchaseHistory
        from apps.tests.factories import make_customer
        self.cust = make_customer(name='ISO ANALYTICS CANARY', phone='01099988877')
        self.cust.preferred_branch = branch
        self.cust.save(update_fields=['preferred_branch'])
        PurchaseHistory.objects.create(customer=self.cust, branch=self.branch_b, doc_code='115',
                                       total_amount=Decimal('10'), softech_invoice_id='ISO-B1',
                                       invoice_date=timezone.now())
        return PurchaseHistory.objects.create(customer=self.cust, branch=branch, doc_code='115',
                                              total_amount=Decimal('777'), softech_invoice_id='ISO-A1',
                                              invoice_date=timezone.now())

    def _branch_ids(self, resp):
        return {r['branch_id'] for r in resp.json().get('by_branch', [])}

    # the generic list/detail/action checks don't fit an aggregate endpoint
    def test_list_hides_other_branch(self):
        for url in ('/api/analytics/sales/', '/api/analytics/performance/'):
            for params in ({}, {'branches': str(self.branch_a.pk)}, {'branch': self.branch_a.pk}):
                with self.subTest(url=url, params=params):
                    r = self.b.get(url, params)
                    self.assertEqual(r.status_code, 200, r.content[:300])
                    self.assertNotIn(self.branch_a.pk, self._branch_ids(r))

    def test_own_branch_still_sees_it(self):
        r = self.a.get('/api/analytics/sales/')
        self.assertEqual(self._branch_ids(r), {self.branch_a.pk})

    def test_detail_is_404_for_other_branch(self):
        pass

    def test_unknown_id_is_404_not_500(self):
        pass

    def test_actions_refused_without_side_effects(self):
        pass

    def test_edit_cannot_move_record_to_a_foreign_branch(self):
        pass

    def test_cross_branch_boards_are_all_branch_only(self):
        for url in ('/api/analytics/branch-contribution/', '/api/analytics/inventory-investment/'):
            with self.subTest(url=url):
                self.assertEqual(self.b.get(url).status_code, 403)
        sup = make_user('iso_an_sup', role='supervisor', branch=self.branch_b)[0]
        sup_c = bearer_client(sup)
        for url in ('/api/analytics/branch-contribution/', '/api/analytics/inventory-investment/'):
            with self.subTest(url=url, who='supervisor'):
                self.assertEqual(sup_c.get(url).status_code, 200)

    def test_filter_options_list_own_branches_only(self):
        r = self.b.get('/api/analytics/filter-options/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        ids = {b['id'] for b in r.json()['branches']}
        self.assertEqual(ids, {str(self.branch_b.pk)})

    def test_customer_search_follows_b2(self):
        """Name search finds only own-branch customers; a full phone finds anyone, masked."""
        r = self.b.get('/api/analytics/customer-search/', {'q': 'ISO ANALYTICS'})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.json(), [])
        r = self.b.get('/api/analytics/customer-search/', {'q': '01099988877'})
        rows = r.json()
        self.assertEqual([row['id'] for row in rows], [self.cust.pk])
        self.assertNotIn('01099988877', r.content.decode('utf-8'))
        r = self.a.get('/api/analytics/customer-search/', {'q': 'ISO ANALYTICS'})
        self.assertIn('01099988877', r.content.decode('utf-8'))

    def test_sales_targets_own_branch_only(self):
        from apps.incentives.models import SalesTarget
        today = datetime.date.today()
        mk = dict(period_start=today, period_end=today, target_value=Decimal('1000'))
        a = SalesTarget.objects.create(scope_type='branch', branch=self.branch_a, **mk)
        b = SalesTarget.objects.create(scope_type='branch', branch=self.branch_b, **mk)
        chain = SalesTarget.objects.create(scope_type='chain', branch=None, **mk)
        r = self.b.get('/api/incentives/targets/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(_ids(r), {b.pk})
        self.assertEqual(self.b.get(f'/api/incentives/targets/{a.pk}/').status_code, 404)
        sup = make_user('iso_tgt_sup', role='supervisor', branch=self.branch_b)[0]
        self.assertEqual(_ids(bearer_client(sup).get('/api/incentives/targets/')), {a.pk, b.pk, chain.pk})

    def test_churn_hides_other_branch_customers(self):
        import datetime as dt
        from django.utils import timezone
        from apps.customers.models import PurchaseHistory
        from apps.tests.factories import make_customer
        gone = make_customer(name='ISO CHURN CANARY', phone='01011122233')
        PurchaseHistory.objects.create(customer=gone, branch=self.branch_a, doc_code='115',
                                       total_amount=Decimal('500'), softech_invoice_id='ISO-OLD',
                                       invoice_date=timezone.now() - dt.timedelta(days=200))
        self.assertIn('ISO CHURN CANARY', self.a.get('/api/analytics/churn/').content.decode('utf-8'))
        for params in ({}, {'branches': str(self.branch_a.pk)}):
            r = self.b.get('/api/analytics/churn/', params)
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertNotIn('ISO CHURN CANARY', r.content.decode('utf-8'))


class SupplyCaseIsolation(_IsolationBase):
    """The read-only `viewer` role holds purchasing view, so it reaches the supply control tower:
    its branch's cases and the network-level ones, never another branch's."""
    role = 'viewer'
    list_url = '/api/supply/cases/'
    detail_url = '/api/supply/cases/{pk}/'
    movable = False            # read-only viewset
    extra_grants = {'purchasing': ['view']}

    def make_record(self, branch):
        from apps.supply.models import SupplyCase
        from apps.tests.factories import make_item
        item = make_item(softech_id=f'SC{branch.softech_branch_id}', name='ISO-CANARY')
        return SupplyCase.objects.create(item=item, branch=branch, status=SupplyCase.STATUS_DETECTED)

    def test_network_case_visible(self):
        from apps.supply.models import SupplyCase
        net = SupplyCase.objects.create(item=self.record.item, branch=None,
                                        status=SupplyCase.STATUS_DETECTED)
        self.assertIn(net.pk, _ids(self.b.get(self.list_url)))

    def test_summary_and_closed_filter_cannot_widen(self):
        self.assertEqual(self.b.get('/api/supply/cases/summary/', {'branch': self.branch_a.pk}).status_code, 403)
        self.assertEqual(self.b.get('/api/supply/cases/summary/').status_code, 200)
        r = self.b.get(self.list_url, {'include_closed': '1'})
        self.assertNotIn(self.record.pk, _ids(r))
        # (export reads the same get_queryset as the list)


class TaskScheduleIsolation(_IsolationBase):
    list_url = '/api/tasks/schedules/'
    detail_url = '/api/tasks/schedules/{pk}/'
    actions = (
        ('PATCH', '/api/tasks/schedules/{pk}/', {'name': 'x'}),
        ('DELETE', '/api/tasks/schedules/{pk}/', None),
    )

    def make_record(self, branch):
        from apps.tasks.models import TaskSchedule
        return TaskSchedule.objects.create(name='ISO-CANARY', title_template='ISO', branch=branch)

    def test_all_branch_schedule_readable_not_writable(self):
        from apps.tasks.models import TaskSchedule
        s = TaskSchedule.objects.create(name='ISO-ALL', title_template='ISO', branch=None)
        self.assertIn(s.pk, _ids(self.b.get(self.list_url)))
        self.assertEqual(self.b.patch(f'{self.list_url}{s.pk}/', {'name': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.b.post(f'{self.list_url}{s.pk}/run/', {}, format='json').status_code, 404)
