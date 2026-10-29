"""
Authorization — vouchers follow the `vouchers` matrix (Batch 4, Z-9d; owner sign-off item).

Before (RBAC log mode = production): any logged-in user could issue a voucher, change its value
(PATCH), cancel or assign it, and run the redemption — eligibility, WhatsApp OTP, verify-OTP
(which issues the redemption document) — and mark a redemption document used; delivery (no
voucher grant) read the voucher list, code lookup and usage report.

Now: reads and the eligibility check = vouchers view; issuing = create, editing / cancelling =
edit, assigning = assign (supervisor, purchasing); redeeming (OTP send / verify) and finishing a
redemption document (mark used, WhatsApp share) = approve or finalize (salesperson, call center,
pharmacist, supervisor). The voucher amounts, codes and redemption logic are unchanged.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

V = '/api/vouchers/vouchers/'
MISSING = '987654321'


class VoucherSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'vouchers'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class VoucherTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path, data=None):
        c = bearer_client(make_user(f'z9d_{role}', role=role)[0])
        with Tripwire():
            return c.get(path) if method == 'get' else getattr(c, method)(path, data or {}, format='json')

    def test_delivery_cannot_list_vouchers(self):
        self.assertEqual(self._call('delivery', 'get', V).status_code, 403)

    def test_salesperson_cannot_issue_a_voucher(self):
        self.assertEqual(self._call('salesperson', 'post', V).status_code, 403)

    def test_viewer_cannot_issue_a_voucher(self):
        self.assertEqual(self._call('viewer', 'post', V).status_code, 403)

    def test_call_center_cannot_cancel_a_voucher(self):
        # already refused today: cancel keeps its own admin check (stricter than the matrix)
        self.assertEqual(self._call('call_center', 'post', f'{V}{MISSING}/cancel/').status_code, 403)

    def test_salesperson_cannot_assign_a_voucher(self):
        self.assertEqual(self._call('salesperson', 'post', f'{V}{MISSING}/assign/').status_code, 403)

    def test_viewer_cannot_redeem_a_voucher(self):
        self.assertEqual(self._call('viewer', 'post', f'{V}{MISSING}/verify-otp/').status_code, 403)

    def test_counter_staff_still_redeem(self):
        self.assertEqual(self._call('salesperson', 'post', f'{V}{MISSING}/verify-otp/').status_code, 404)
        self.assertEqual(self._call('salesperson', 'get', V).status_code, 200)

    def test_supervisor_still_issues_and_purchasing_still_assigns(self):
        self.assertNotEqual(self._call('supervisor', 'post', V).status_code, 403)
        self.assertEqual(self._call('purchasing', 'post', f'{V}{MISSING}/assign/').status_code, 404)
