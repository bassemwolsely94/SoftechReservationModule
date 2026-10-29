"""
Sweep noise — a method the view does not implement is no endpoint (Batch 4, Z-11b; overblock review).

Before: the sweep sent GET and POST to every route. Where the view has no handler for that method
(a GET to a POST-only action, a POST to a read-only report) a strict permission class answered 403
before DRF could answer 405, and the line landed in `role_overblocks` — 161 lines that are no
lockout of anyone.

Now: `routes.handles(path, method)` asks the view Django dispatches the path to, and the sweep
skips methods it does not implement. No app code changes.
"""
from django.test import SimpleTestCase



ID = '987654321'


class HandlesTests(SimpleTestCase):

    def _handles(self, path, method):
        from .routes import handles
        return handles(path, method)

    def test_a_missing_method_is_not_handled(self):
        self.assertFalse(self._handles(f'/api/pricing-approvals/{ID}/approve/', 'GET'))     # function view, POST only
        self.assertFalse(self._handles('/api/pricing-approvals/branch-health/', 'POST'))    # function view, GET only
        self.assertFalse(self._handles(f'/api/vouchers/vouchers/{ID}/cancel/', 'GET'))     # viewset action, POST only
        self.assertFalse(self._handles('/api/pbx/spy/', 'GET'))                             # APIView, POST only

    def test_a_real_method_is_handled(self):
        self.assertTrue(self._handles(f'/api/pricing-approvals/{ID}/approve/', 'POST'))
        self.assertTrue(self._handles('/api/pricing-approvals/branch-health/', 'GET'))
        self.assertTrue(self._handles(f'/api/vouchers/vouchers/{ID}/cancel/', 'POST'))
        self.assertTrue(self._handles('/api/vouchers/vouchers/', 'GET'))
        self.assertTrue(self._handles('/api/vouchers/vouchers/', 'POST'))


class SweepMethodsTests(SimpleTestCase):

    def test_the_sweep_sends_every_method_the_matrix_maps(self):
        from . import sweep
        self.assertEqual(set(getattr(sweep, 'METHODS', ('GET', 'POST'))), {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'})
