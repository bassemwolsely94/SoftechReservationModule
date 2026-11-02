"""
Batch 5 — the one branch-scope helper (core/branch_scope.py), owner decision 3:

  • allowed_branches is the real extra-branch list (UserBranchAccess folds into it);
  • a restricted branch always wins — over access_all_branches and the all-branch roles;
  • fail-closed: a branch role with no branch sees nothing; an inactive profile sees nothing.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.branches.models import Branch
from apps.tests.factories import make_branch, make_user
from core import branch_scope


class BranchScopeHelperTests(TestCase):
    def setUp(self):
        self.a = make_branch(name='Scope A', softech_id='SA1')
        self.b = make_branch(name='Scope B', softech_id='SB1')
        self.c = make_branch(name='Scope C', softech_id='SC1')

    def ids(self, profile):
        return branch_scope.branch_ids(profile.user)

    def test_branch_role_sees_home_branch_only(self):
        _, p, _ = make_user('bs_pharm', role='pharmacist', branch=self.a)
        self.assertEqual(self.ids(p), {self.a.id})

    def test_allowed_branches_add_to_home(self):
        _, p, _ = make_user('bs_pharm2', role='pharmacist', branch=self.a)
        p.allowed_branches.add(self.b)
        self.assertEqual(self.ids(p), {self.a.id, self.b.id})

    def test_branch_role_without_branch_sees_nothing(self):
        _, p, _ = make_user('bs_orphan', role='salesperson', branch=self.a)
        p.branch = None
        p.save()
        self.assertEqual(self.ids(p), set())

    def test_all_branch_roles_are_unrestricted(self):
        for role in ('call_center', 'purchasing', 'supervisor', 'quality_manager'):   # B-3
            with self.subTest(role=role):
                _, p, _ = make_user(f'bs_{role}', role=role, branch=self.a)
                self.assertIsNone(self.ids(p))

    def test_branch_roles_are_scoped(self):
        for role in ('pharmacist', 'salesperson', 'viewer', 'delivery'):
            with self.subTest(role=role):
                _, p, _ = make_user(f'bs_b_{role}', role=role, branch=self.a)
                self.assertEqual(self.ids(p), {self.a.id})

    def test_restricted_beats_all_access(self):
        _, p, _ = make_user('bs_all', role='pharmacist', branch=self.a, access_all=True)
        p.restricted_branches.add(self.b)
        ids = self.ids(p)
        self.assertIsNotNone(ids)
        self.assertNotIn(self.b.id, ids)
        self.assertTrue({self.a.id, self.c.id} <= ids)

    def test_restricted_beats_home_and_allowed(self):
        _, p, _ = make_user('bs_rest', role='pharmacist', branch=self.a)
        p.allowed_branches.add(self.b)
        p.restricted_branches.add(self.a, self.b)
        self.assertEqual(self.ids(p), set())

    def test_restricted_beats_admin_role(self):
        _, p, _ = make_user('bs_admin', role='admin', branch=self.a, access_all=True)
        p.restricted_branches.add(self.c)
        self.assertNotIn(self.c.id, self.ids(p))

    def test_inactive_profile_sees_nothing(self):
        _, p, _ = make_user('bs_off', role='supervisor', branch=self.a, access_all=True)
        p.is_active = False
        p.save()
        self.assertEqual(self.ids(p), set())

    def test_anonymous_and_profileless_users_see_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(branch_scope.branch_ids(AnonymousUser()), set())
        u = get_user_model().objects.create_user('bs_noprofile', password='x' * 12)
        self.assertEqual(branch_scope.branch_ids(u), set())

    def test_superuser_without_profile_is_unrestricted(self):
        u = get_user_model().objects.create_superuser('bs_root', password='x' * 12)
        self.assertIsNone(branch_scope.branch_ids(u))

    def test_scope_filters_queryset_fail_closed(self):
        _, p, _ = make_user('bs_q', role='pharmacist', branch=self.a)
        qs = branch_scope.scope(Branch.objects.all(), p.user, field='id')
        self.assertEqual(set(qs.values_list('id', flat=True)), {self.a.id})
        p.branch = None
        p.save()
        self.assertFalse(branch_scope.scope(Branch.objects.all(), p.user, field='id').exists())

    def test_code_scope_and_allows_code(self):
        """Batch 5 part 2: stock count / expiry rows carry the SOFTECH code, not a Branch FK."""
        _, p, _ = make_user('bs_code', role='pharmacist', branch=self.a)
        qs = branch_scope.scope_code(Branch.objects.all(), p.user, field='softech_branch_id')
        self.assertEqual(set(qs.values_list('id', flat=True)), {self.a.id})
        self.assertTrue(branch_scope.allows_code(p.user, 'SA1'))
        self.assertFalse(branch_scope.allows_code(p.user, 'SB1'))
        self.assertFalse(branch_scope.allows_code(p.user, ''))
        self.assertFalse(branch_scope.allows_code(p.user, None))
        self.assertEqual(branch_scope.branch_codes(p.user), {'SA1'})
        _, sup, _ = make_user('bs_code_sup', role='supervisor', branch=self.a)
        self.assertIsNone(branch_scope.branch_codes(sup.user))
        self.assertTrue(branch_scope.allows_code(sup.user, 'SB1'))
        self.assertTrue(branch_scope.allows_code(sup.user, 'UNKNOWN'))
        all_qs = branch_scope.scope_code(Branch.objects.all(), sup.user, field='softech_branch_id')
        self.assertEqual(all_qs.count(), Branch.objects.count())

    def test_narrow_client_filters(self):
        """A client ?branch= filter can only narrow, never widen."""
        _, p, _ = make_user('bs_narrow', role='pharmacist', branch=self.a)
        self.assertEqual(branch_scope.narrow_ids(p.user, None), {self.a.id})
        self.assertEqual(branch_scope.narrow_ids(p.user, [self.b.id]), set())
        self.assertEqual(branch_scope.narrow_ids(p.user, [self.a.id, self.b.id, 'x']), {self.a.id})
        self.assertEqual(branch_scope.narrow_codes(p.user, ['SB1']), set())
        self.assertEqual(branch_scope.narrow_codes(p.user, []), {'SA1'})
        _, sup, _ = make_user('bs_narrow_sup', role='supervisor', branch=self.a)
        self.assertIsNone(branch_scope.narrow_ids(sup.user, None))
        self.assertEqual(branch_scope.narrow_ids(sup.user, [str(self.b.id)]), {self.b.id})
        from rest_framework.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            branch_scope.require_code(p.user, 'SB1')
        with self.assertRaises(PermissionDenied):
            branch_scope.require(p.user, self.b.id)
        branch_scope.require(p.user, str(self.a.id))

    def test_allows(self):
        _, p, _ = make_user('bs_allow', role='pharmacist', branch=self.a)
        self.assertTrue(branch_scope.allows(p.user, self.a.id))
        self.assertFalse(branch_scope.allows(p.user, self.b.id))
        self.assertFalse(branch_scope.allows(p.user, None))

    def test_userbranchaccess_folds_into_allowed_branches(self):
        import importlib
        from django.apps import apps as django_apps
        from apps.users.models import UserBranchAccess
        fold = importlib.import_module(
            'apps.users.migrations.0033_fold_userbranchaccess_into_allowed_branches').fold
        _, p, _ = make_user('bs_fold', role='pharmacist', branch=self.a)
        UserBranchAccess.objects.create(staff=p, branch=self.c)
        p.allowed_branches.add(self.b)
        fold(django_apps, None)
        fold(django_apps, None)  # idempotent
        self.assertEqual(set(p.allowed_branches.values_list('id', flat=True)), {self.b.id, self.c.id})
        self.assertEqual(self.ids(p), {self.a.id, self.b.id, self.c.id})

    def test_profile_property_uses_the_helper(self):
        _, p, _ = make_user('bs_prop', role='pharmacist', branch=self.a)
        p.allowed_branches.add(self.b)
        p.restricted_branches.add(self.a)
        self.assertEqual(p.accessible_branch_ids, {self.b.id})


class ScopedViewsKeepTheScopeTests(TestCase):
    """A view that mixes in BranchScopedMixin but defines its own get_queryset() overrides the
    mixin's — it must call branch_scope itself (2026-10-30: cheque plans and payments did not)."""

    # method → calls that keep the scope (any of them, as real calls — comments don't count)
    KEEPERS = {
        'get_queryset': {'scope', 'get_or_404', 'get_queryset'},          # super().get_queryset()
        'perform_create': {'check_branch_value', 'perform_create'},
        'perform_update': {'check_branch_value', 'perform_update'},
    }

    @staticmethod
    def _called_names(func):
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', ''))
        return names

    def test_overridden_methods_still_scope(self):
        from django.urls import get_resolver
        from apps.tests.security.routes import _walk, view_id
        bad = set()
        for _, cb in _walk(get_resolver().url_patterns):
            _, cls = view_id(cb)
            if cls is None or not issubclass(cls, branch_scope.BranchScopedMixin):
                continue
            for klass in cls.__mro__:
                if klass is branch_scope.BranchScopedMixin:
                    break
                for meth, keepers in self.KEEPERS.items():
                    own = klass.__dict__.get(meth)
                    if own and not (self._called_names(own) & keepers):
                        bad.add(f'{klass.__module__}.{klass.__name__}.{meth}')
        self.assertEqual(sorted(bad), [])
