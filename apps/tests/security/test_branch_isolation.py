"""
Batch 5 — cross-branch isolation for the own-branch-only domains (owner decision 3: orders
(POS / reservations), payments, cheques, finance and deliveries stay limited to the user's own
branch(es)).

A record lives in branch A. A user of branch B — whose role the matrix DOES grant on the module,
so only the branch check can stop them — must not:
  • see it in the list (also not via ?branch=A),
  • open it by id (404: no disclosure that it exists),
  • run any action on it (refused, row unchanged, nothing reaches SOFTECH or the network).
The same request from a user of branch A works (no overblock), so the test proves scoping, not
a blanket lock-out. Real HTTP stack, Bearer JWT, RBAC enforcing.
"""
import datetime
from decimal import Decimal

from django.db import transaction
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire


def _ids(resp):
    data = resp.json()
    rows = data.get('results', data) if isinstance(data, dict) else data
    return {r.get('id') for r in rows if isinstance(r, dict)}


@override_settings(RBAC_ENFORCEMENT='enforce')
class _IsolationBase(TestCase):
    role = 'pharmacist'
    extra_grants = {}          # {module: [actions]} added for `role` on top of the code matrix
    list_url = None
    detail_url = None          # format with pk
    actions = ()               # ((method, url-with-{pk}, body), ...)
    movable = True             # PATCH {'branch': other} must be refused

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        for module, acts in cls.extra_grants.items():
            for a in acts:
                RoleModuleAccess.objects.update_or_create(
                    role=cls.role, module=module, action=a, defaults={'is_allowed': True})
        module_access.clear_cache()
        cls.branch_a = make_branch('Iso A', softech_id='ISA')
        cls.branch_b = make_branch('Iso B', softech_id='ISB')
        cls.user_a = make_user(f'iso_{cls.__name__}_a', role=cls.role, branch=cls.branch_a)[0]
        cls.user_b = make_user(f'iso_{cls.__name__}_b', role=cls.role, branch=cls.branch_b)[0]

    def setUp(self):
        if self.list_url is None:
            self.skipTest('base class')
        module_access.clear_cache()
        self.record = self.make_record(self.branch_a)
        self.a = bearer_client(self.user_a)
        self.b = bearer_client(self.user_b)

    def make_record(self, branch):
        raise NotImplementedError

    def snapshot(self):
        self.record.refresh_from_db()
        return model_to_dict(self.record)

    def _skip_base(self):
        if self.list_url is None:
            self.skipTest('base class')

    def test_list_hides_other_branch(self):
        self._skip_base()
        r = self.b.get(self.list_url)
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn(self.record.pk, _ids(r))
        r = self.b.get(self.list_url, {'branch': self.branch_a.pk})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn(self.record.pk, _ids(r))

    def test_own_branch_still_sees_it(self):
        self._skip_base()
        self.assertIn(self.record.pk, _ids(self.a.get(self.list_url)))
        self.assertEqual(self.a.get(self.detail_url.format(pk=self.record.pk)).status_code, 200)

    def test_detail_is_404_for_other_branch(self):
        self._skip_base()
        r = self.b.get(self.detail_url.format(pk=self.record.pk))
        self.assertEqual(r.status_code, 404, r.content[:300])

    def test_unknown_id_is_404_not_500(self):
        self._skip_base()
        self.assertEqual(self.a.get(self.detail_url.format(pk=987654321)).status_code, 404)

    def _send(self, client, method, url, body):
        return getattr(client, method.lower())(url.format(pk=self.record.pk), body, format='json')

    def test_actions_refused_without_side_effects(self):
        self._skip_base()
        before = self.snapshot()
        for method, url, body in self.actions:
            with self.subTest(method=method, url=url):
                # positive control: the record's own branch gets past permission + branch checks
                # (rolled back; nothing leaves the process)
                with transaction.atomic(), Tripwire():
                    own = self._send(self.a, method, url, body)
                    transaction.set_rollback(True)
                self.assertNotIn(own.status_code, (403, 404), own.content[:300])
                self.record.refresh_from_db()
                with Tripwire() as tw:
                    r = self._send(self.b, method, url, body)
                self.assertEqual(r.status_code, 404, r.content[:300])
                self.assertEqual(tw.softech_calls, [])
                self.assertEqual(tw.outside_count(), 0)
                self.assertEqual(self.snapshot(), before)

    def test_edit_cannot_move_record_to_a_foreign_branch(self):
        self._skip_base()
        if not self.movable:
            self.skipTest('branch not editable here')
        before = self.snapshot()
        r = self.a.patch(self.detail_url.format(pk=self.record.pk), {'branch': self.branch_b.pk},
                         format='json')
        self.assertIn(r.status_code, (400, 403), r.content[:300])
        self.assertEqual(self.snapshot(), before)


class PosOrderIsolation(_IsolationBase):
    list_url = '/api/pos-orders/'
    detail_url = '/api/pos-orders/{pk}/'
    movable = False
    extra_grants = {'pos': ['edit', 'delete', 'approve', 'finalize']}
    actions = (
        ('PATCH', '/api/pos-orders/{pk}/', {'customer_name': 'x'}),
        ('DELETE', '/api/pos-orders/{pk}/', None),
        ('POST', '/api/pos-orders/{pk}/ready/', {}),
        ('POST', '/api/pos-orders/{pk}/push/', {}),
        ('POST', '/api/pos-orders/{pk}/cancel/', {}),
        ('POST', '/api/pos-orders/{pk}/share-whatsapp/', {}),
        ('POST', '/api/pos-orders/{pk}/prescription/', {}),
    )

    def make_record(self, branch):
        from apps.pos_orders.models import SoftechSalesOrder
        return SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode=branch.softech_branch_id, store_code='101',
            channel='cash', doc_kind='sale', customer_name='ISO-CANARY')


class PaymentIsolation(_IsolationBase):
    list_url = '/api/payments/'
    detail_url = '/api/payments/{pk}/'
    extra_grants = {'finance': ['edit', 'approve', 'delete']}
    actions = (
        ('PATCH', '/api/payments/{pk}/', {'notes': 'x'}),
        ('DELETE', '/api/payments/{pk}/', None),
        ('POST', '/api/payments/{pk}/confirm/', {}),
        ('POST', '/api/payments/{pk}/reconcile/', {}),
        ('POST', '/api/payments/{pk}/dispute/', {'reason': 'x'}),
        ('POST', '/api/payments/{pk}/screenshot/', {}),
    )

    def make_record(self, branch):
        from apps.payments.models import ExternalPayment
        return ExternalPayment.objects.create(branch=branch, method=ExternalPayment._meta.get_field(
            'method').choices[0][0], amount=Decimal('150.00'))


class ChequePlanIsolation(_IsolationBase):
    list_url = '/api/cheques/plans/'
    detail_url = '/api/cheques/plans/{pk}/'
    extra_grants = {'cheques': ['edit', 'approve', 'delete', 'create']}
    actions = (
        ('PATCH', '/api/cheques/plans/{pk}/', {'title': 'x'}),
        ('DELETE', '/api/cheques/plans/{pk}/', None),
        ('POST', '/api/cheques/plans/{pk}/activate/', {}),
        ('POST', '/api/cheques/plans/{pk}/cancel/', {}),
    )

    def make_record(self, branch):
        from apps.cheques.models import ChequePlan
        return ChequePlan.objects.create(branch=branch, title='ISO', payee_name='ISO-CANARY',
                                         total_amount=Decimal('1000.00'),
                                         first_due_date=datetime.date(2026, 12, 1))


class DeliveryOrderIsolation(_IsolationBase):
    list_url = '/api/delivery/'
    detail_url = '/api/delivery/{pk}/'
    extra_grants = {'delivery': ['assign', 'delete']}
    actions = tuple(
        ('POST', f'/api/delivery/{{pk}}/{a}/', {}) for a in (
            'assign', 'accept', 'dispatch', 'complete', 'partial', 'unavailable', 'fail',
            'cancel', 'return', 'close', 'collect-cash', 'backfill', 'csat')
    ) + (
        ('PATCH', '/api/delivery/{pk}/', {'customer_name': 'x'}),
        ('GET', '/api/delivery/{pk}/items/', None),
        ('GET', '/api/delivery/{pk}/whatsapp/', None),
        ('GET', '/api/delivery/{pk}/tracking-link/', None),
    )

    def make_record(self, branch):
        from apps.delivery.models import DeliveryOrder
        return DeliveryOrder.objects.create(branch=branch, customer_name='ISO-CANARY')


class ReservationIsolation(_IsolationBase):
    list_url = '/api/reservations/'
    detail_url = '/api/reservations/{pk}/'
    actions = (
        ('PATCH', '/api/reservations/{pk}/', {'contact_name': 'x'}),
        ('GET', '/api/reservations/{pk}/activity/', None),
    )

    def make_record(self, branch):
        from apps.reservations.models import Reservation
        return Reservation.objects.create(branch=branch, contact_phone='01000000000',
                                          contact_name='ISO-CANARY')


@override_settings(RBAC_ENFORCEMENT='enforce')
class ForgedBranchOnCreate(TestCase):
    """A user may not create a record in a branch outside their own (body `branch` forged)."""

    CASES = (
        ('pharmacist', {'finance': ['create']}, '/api/payments/', 'payments.ExternalPayment',
         lambda b: {'branch': b.pk, 'method': 'cash', 'amount': '10.00'}),
        ('pharmacist', {}, '/api/pos-orders/', 'pos_orders.SoftechSalesOrder',
         lambda b: {'branch': b.pk, 'softech_branchcode': b.softech_branch_id, 'store_code': '101',
                    'channel': 'cash', 'doc_kind': 'sale', 'customer_name': 'FORGED'}),
        ('pharmacist', {'cheques': ['create']}, '/api/cheques/plans/', 'cheques.ChequePlan',
         lambda b: {'branch': b.pk, 'title': 'FORGED', 'payee_name': 'FORGED', 'total_amount': '100.00',
                    'cheque_count': 1, 'first_due_date': '2026-12-01'}),
        ('pharmacist', {}, '/api/delivery/', 'delivery.DeliveryOrder',
         lambda b: {'branch': b.pk, 'customer_name': 'FORGED'}),
        ('pharmacist', {}, '/api/reservations/', 'reservations.Reservation',
         lambda b: {'branch': b.pk, 'contact_phone': '01000000001', 'contact_name': 'FORGED',
                    'manual_item_name': 'FORGED ITEM'}),
    )

    def test_create_in_other_branch_is_refused(self):
        from django.apps import apps
        seed_code_matrix()
        a = make_branch('Iso A', softech_id='ISA')
        b = make_branch('Iso B', softech_id='ISB')
        for role, grants, url, label, body in self.CASES:
            for module, acts in grants.items():
                for act in acts:
                    RoleModuleAccess.objects.update_or_create(
                        role=role, module=module, action=act, defaults={'is_allowed': True})
            module_access.clear_cache()
            user = make_user(f'forge_{role}', role=role, branch=b)[0]
            Model = apps.get_model(label)
            before = Model.objects.count()
            with self.subTest(url=url):
                # positive control: the same body for the user's own branch is accepted
                with transaction.atomic(), Tripwire():
                    ok = bearer_client(user).post(url, body(b), format='json')
                    transaction.set_rollback(True)
                self.assertIn(ok.status_code, (200, 201), ok.content[:300])
                with Tripwire() as tw:
                    r = bearer_client(user).post(url, body(a), format='json')
                self.assertEqual(r.status_code, 403, r.content[:300])
                self.assertEqual(Model.objects.count(), before)
                self.assertEqual(tw.softech_calls, [])


class BranchlessUserSeesNothing(TestCase):
    """Fail-closed: a branch role whose profile lost its branch sees no orders/reservations."""

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_branchless_pharmacist(self):
        from apps.reservations.models import Reservation
        seed_code_matrix()
        a = make_branch('Iso A', softech_id='ISA')
        Reservation.objects.create(branch=a, contact_phone='01000000000', contact_name='x')
        user, profile, _ = make_user('iso_orphan', role='pharmacist', branch=a)
        profile.branch = None
        profile.save()
        r = bearer_client(user).get('/api/reservations/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(_ids(r), set())


@override_settings(RBAC_ENFORCEMENT='enforce')
class OwnerBranchDecisions(TestCase):
    """Owner decisions B-1 / B-3 (2026-10-30) — finance and the supervisor / quality-manager scope."""

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.a = make_branch('Iso A', softech_id='ISA')
        cls.b = make_branch('Iso B', softech_id='ISB')

    def test_branch_pharmacist_does_not_see_company_finance(self):
        from apps.finance.models import FinancialPeriod, FinancialSnapshot
        period = FinancialPeriod.objects.create(
            period_type='month', year=2026, month=9, label='2026-09',
            period_start=datetime.date(2026, 9, 1), period_end=datetime.date(2026, 9, 30))
        FinancialSnapshot.objects.create(period=period, branch=None, net_revenue=Decimal('999999'))
        FinancialSnapshot.objects.create(period=period, branch=self.a, net_revenue=Decimal('5555'))
        user = make_user('pend_fin', role='pharmacist', branch=self.b)[0]
        r = bearer_client(user).get('/api/finance/dashboard/', {'period_id': period.pk})
        self.assertIn(r.status_code, (200, 403, 404))
        if r.status_code == 200:
            self.assertNotIn('999999', r.content.decode())
            self.assertNotIn('5555', r.content.decode())

    def test_quality_manager_sees_company_finance(self):
        from apps.finance.models import FinancialPeriod, FinancialSnapshot
        period = FinancialPeriod.objects.create(
            period_type='month', year=2026, month=8, label='2026-08',
            period_start=datetime.date(2026, 8, 1), period_end=datetime.date(2026, 8, 31))
        FinancialSnapshot.objects.create(period=period, branch=None, net_revenue=Decimal('777777'))
        user = make_user('b1_qm', role='quality_manager', branch=self.b)[0]
        r = bearer_client(user).get('/api/finance/dashboard/', {'period_id': period.pk})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertIn('777777', r.content.decode())

    def test_branch_pharmacist_sees_own_branch_finance_only(self):
        from apps.finance.models import FinancialPeriod, FinancialSnapshot
        period = FinancialPeriod.objects.create(
            period_type='month', year=2026, month=7, label='2026-07',
            period_start=datetime.date(2026, 7, 1), period_end=datetime.date(2026, 7, 31))
        FinancialSnapshot.objects.create(period=period, branch=self.b, net_revenue=Decimal('4242'))
        FinancialSnapshot.objects.create(period=period, branch=self.a, net_revenue=Decimal('5555'))
        user = make_user('b1_pharm', role='pharmacist', branch=self.b)[0]
        body = bearer_client(user).get('/api/finance/dashboard/', {'period_id': period.pk}).content.decode()
        self.assertIn('4242', body)
        self.assertNotIn('5555', body)
        snaps = bearer_client(user).get('/api/finance/snapshots/', {'period_id': period.pk}).content.decode()
        self.assertNotIn('5555', snaps)

    def test_supplier_reconciliation_is_company_only(self):
        pharm = make_user('b1_recon_pharm', role='pharmacist', branch=self.b)[0]
        qm = make_user('b1_recon_qm', role='quality_manager', branch=self.b)[0]
        self.assertEqual(bearer_client(pharm).get('/api/finance/reconciliation/dashboard/').status_code, 403)
        self.assertNotEqual(bearer_client(qm).get('/api/finance/reconciliation/dashboard/').status_code, 403)

    def test_supervisor_and_quality_manager_work_every_branch(self):
        """Owner decision B-3 (2026-10-30): supervisor and quality_manager are all-branch roles —
        but a restricted branch still wins."""
        from apps.delivery.models import DeliveryOrder
        o = DeliveryOrder.objects.create(branch=self.a, customer_name='ISO-CANARY')
        for role in ('supervisor', 'quality_manager'):
            with self.subTest(role=role):
                user, profile, _ = make_user(f'b3_{role}', role=role, branch=self.b)
                self.assertEqual(bearer_client(user).get(f'/api/delivery/{o.pk}/').status_code, 200)
                profile.restricted_branches.add(self.a)
                self.assertEqual(bearer_client(user).get(f'/api/delivery/{o.pk}/').status_code, 404)


@override_settings(RBAC_ENFORCEMENT='enforce')
class AllowedAndRestrictedBranchesOverHttp(TestCase):
    """The grant lists change what the API returns, not only what the helper says."""

    def test_allowed_branch_opens_and_restricted_branch_closes(self):
        from apps.pos_orders.models import SoftechSalesOrder
        seed_code_matrix()
        a = make_branch('Iso A', softech_id='ISA')
        b = make_branch('Iso B', softech_id='ISB')
        order = SoftechSalesOrder.objects.create(branch=a, softech_branchcode='ISA', store_code='101',
                                                 channel='cash', doc_kind='sale')
        user, profile, _ = make_user('iso_grants', role='pharmacist', branch=b)
        url = f'/api/pos-orders/{order.pk}/'
        self.assertEqual(bearer_client(user).get(url).status_code, 404)
        profile.allowed_branches.add(a)
        self.assertEqual(bearer_client(user).get(url).status_code, 200)
        profile.restricted_branches.add(a)
        self.assertEqual(bearer_client(user).get(url).status_code, 404)

    def test_restricted_branch_hidden_from_all_branch_role(self):
        from apps.pos_orders.models import SoftechSalesOrder
        seed_code_matrix()
        a = make_branch('Iso A', softech_id='ISA')
        order = SoftechSalesOrder.objects.create(branch=a, softech_branchcode='ISA', store_code='101',
                                                 channel='cash', doc_kind='sale')
        user, profile, _ = make_user('iso_cc', role='call_center', branch=None)
        client = bearer_client(user)
        self.assertIn(order.pk, _ids(client.get('/api/pos-orders/')))
        profile.restricted_branches.add(a)
        self.assertNotIn(order.pk, _ids(client.get('/api/pos-orders/')))
        self.assertEqual(client.get(f'/api/pos-orders/{order.pk}/').status_code, 404)


@override_settings(RBAC_ENFORCEMENT='enforce')
class RiderKeepsAssignedOrders(TestCase):
    def test_rider_sees_assigned_order_from_another_branch(self):
        from apps.delivery.models import DeliveryDriver, DeliveryOrder
        seed_code_matrix()
        a = make_branch('Iso A', softech_id='ISA')
        b = make_branch('Iso B', softech_id='ISB')
        user, profile, _ = make_user('iso_rider', role='delivery', branch=b)
        driver = DeliveryDriver.objects.create(staff_profile=profile, full_name='Rider', mobile='01099990000', branch=b)
        mine = DeliveryOrder.objects.create(branch=a, customer_name='MINE', assigned_driver=driver)
        other = DeliveryOrder.objects.create(branch=a, customer_name='OTHER')
        client = bearer_client(user)
        self.assertEqual(client.get(f'/api/delivery/{mine.pk}/').status_code, 200)
        self.assertEqual(client.get(f'/api/delivery/{other.pk}/').status_code, 404)
