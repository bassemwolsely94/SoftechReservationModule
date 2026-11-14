"""Branch.kind is the single liveness authority: pending kind, display_order, helpers."""
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from apps.branches.models import Branch, _reset_hq_code_cache, hq_code


def mk(code, kind, **kw):
    return Branch.objects.create(softech_branch_id=code, name=f'B{code}', kind=kind, **kw)


class BranchKindTests(TestCase):
    def setUp(self):
        # test-transaction rollback fires no signals, so drop the process cache by hand
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        Branch.objects.all().delete()

    def test_live_is_hq_and_retail_only(self):
        for i, k in enumerate(['hq', 'retail', 'call_center', 'closed', 'pending']):
            mk(f'T{i}' if k != 'hq' else 'T100', k)
        live = set(Branch.objects.live().values_list('kind', flat=True))
        self.assertEqual(live, {'hq', 'retail'})
        self.assertEqual(set(Branch.objects.operational()), set(Branch.objects.live()))
        self.assertEqual(Branch.objects.closed().count(), 1)
        self.assertEqual(Branch.objects.pending().count(), 1)

    def test_pending_excluded_from_live_and_retail(self):
        p = mk('P1', Branch.KIND_PENDING)
        self.assertNotIn(p, Branch.objects.live())
        self.assertNotIn(p, Branch.objects.retail())
        self.assertFalse(p.is_live)
        self.assertTrue(mk('R1', 'retail').is_live)

    def test_ordered_ties_break_by_code(self):
        mk('150', 'retail', display_order=5)
        mk('140', 'retail', display_order=5)
        mk('130', 'retail', display_order=1)
        self.assertEqual(
            [b.softech_branch_id for b in Branch.objects.ordered()], ['130', '140', '150'])

    def test_hq_code_returns_single_hq(self):
        mk('100', 'hq')
        self.assertEqual(hq_code(), '100')

    def test_hq_code_cache_follows_changes(self):
        h = mk('100', 'hq')
        self.assertEqual(hq_code(), '100')
        h.delete()
        mk('999', 'hq')
        self.assertEqual(hq_code(), '999')

    def test_hq_code_raises_when_two_hq(self):
        mk('100', 'hq')
        mk('101', 'hq')
        with self.assertRaises(ImproperlyConfigured):
            hq_code()

    def test_hq_code_raises_when_none(self):
        with self.assertRaises(ImproperlyConfigured):
            hq_code()

    def test_migration_closes_b01(self):
        import importlib
        from django.apps import apps as dj_apps
        mod = importlib.import_module('apps.branches.migrations.0014_close_test_branch_b01')
        b = mk('B01', 'retail', pos_enabled=True)
        mod.close_b01(dj_apps, None)
        b.refresh_from_db()
        self.assertEqual(b.kind, 'closed')
        self.assertFalse(b.is_operational)
        self.assertFalse(b.pos_enabled)
