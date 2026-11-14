"""
apps/tests/security/test_role_literal_guard.py

Permission roles come from one registry (apps/users/roles.py). This guard fails when code adds a
new hard-coded role list or a new `role == '<key>'` check; the ones that already exist are listed
in baselines/role_literals_py.txt and baselines/role_literals_js.txt (ratchet: only shrinks).
A new role is one line in apps/users/roles.py; who may do what belongs in the RBAC matrix
(core.permissions.matrix_permission). No database.
"""
import ast
import textwrap

from django.test import SimpleTestCase

from . import role_literals
from .baseline import assert_matches_baseline, load_baseline


def _tree(src):
    return ast.parse(textwrap.dedent(src))


class PythonRoleLiteralUnitTests(SimpleTestCase):

    def test_tuple_of_role_keys_flagged(self):
        t = _tree('''
            def f(role):
                return role in ('admin', 'supervisor')
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'), {'t.py::f::admin,supervisor x1'})

    def test_list_set_and_module_level_flagged_with_sorted_keys(self):
        t = _tree('''
            ROLES = ['viewer', 'admin']
            class A:
                ok = frozenset({'pharmacist', 'delivery'})
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'),
                         {'t.py::<module>::admin,viewer x1', 't.py::A::delivery,pharmacist x1'})

    def test_admin_compare_not_flagged(self):
        t = _tree('''
            def f(user):
                return user.role == 'admin'
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'), set())

    def test_single_role_compare_flagged(self):
        t = _tree('''
            def f(role):
                return role == 'viewer'
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'), {'t.py::f::viewer x1'})

    def test_reversed_compare_and_role_keyword_flagged(self):
        t = _tree('''
            def f(p):
                return 'delivery' != p.role
            def g():
                return StaffProfile.objects.filter(role='pharmacist')
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'),
                         {'t.py::f::delivery x1', 't.py::g::pharmacist x1'})

    def test_non_role_strings_not_flagged(self):
        t = _tree('''
            ROLES = ['a', 'b']
            MIXED = ('admin', 'orders')
            def f(module):
                return module == 'delivery'
            def g():
                return qs.filter(channel='delivery')
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'), set())

    def test_new_literal_is_not_in_the_baseline(self):
        """The ratchet would fail on a freshly added role list."""
        t = _tree('''
            def brand_new_gate(user):
                return user.role in ('pharmacist', 'salesperson')
        ''')
        found = role_literals.py_role_literal_sites(t, 'apps/brand_new/views.py')
        self.assertEqual(found, {'apps/brand_new/views.py::brand_new_gate::pharmacist,salesperson x1'})
        self.assertFalse(found & load_baseline('role_literals_py'))


    def test_duplicate_literal_in_one_function_is_counted(self):
        t = _tree('''
            def f(role):
                a = role in ('admin', 'supervisor')
                b = role in ('supervisor', 'admin')
                return a, b
        ''')
        self.assertEqual(role_literals.py_role_literal_sites(t, 't.py'), {'t.py::f::admin,supervisor x2'})


class JsRoleLiteralUnitTests(SimpleTestCase):

    def test_array_of_role_keys_flagged(self):
        src = "const x = { roles: ['admin', \"pharmacist\"] }"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.jsx'), {'a.jsx::admin,pharmacist x1'})

    def test_multiline_array_flagged(self):
        src = "const R = [\n  'supervisor',\n  'call_center',\n]"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.js'), {'a.js::call_center,supervisor x1'})

    def test_admin_compare_not_flagged(self):
        src = "if (x === 'admin') {}\nif (user.role === 'admin') {}"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.jsx'), set())

    def test_single_role_compare_flagged(self):
        src = "if (user?.role === 'viewer' || 'delivery' !== myRole) {}"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.jsx'),
                         {'a.jsx::viewer x1', 'a.jsx::delivery x1'})

    def test_duplicate_array_is_counted(self):
        src = "const a = ['admin', 'viewer']; const b = ['viewer', 'admin']"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.js'), {'a.js::admin,viewer x2'})

    def test_non_role_arrays_not_flagged(self):
        src = "const a = ['a', 'b']; const m = ['admin', 'orders']; if (tab === 'delivery') {}"
        self.assertEqual(role_literals.js_role_literal_sites(src, 'a.jsx'), set())

    def test_new_literal_is_not_in_the_baseline(self):
        src = "export const GATE = ['pharmacist', 'salesperson']"
        found = role_literals.js_role_literal_sites(src, 'frontend/src/brand_new/Gate.jsx')
        self.assertEqual(found, {'frontend/src/brand_new/Gate.jsx::pharmacist,salesperson x1'})
        self.assertFalse(found & load_baseline('role_literals_js'))


class RoleLiteralRepoTests(SimpleTestCase):

    def test_scan_skips_the_registry_and_tests(self):
        paths = {e.split('::')[0] for e in role_literals.repo_py_sites() | role_literals.repo_js_sites()}
        self.assertNotIn('apps/users/roles.py', paths)
        self.assertFalse([p for p in paths if p.startswith('apps/tests/') or '.test.' in p
                          or 'node_modules' in p])

    def test_python_role_literals_match_baseline(self):
        assert_matches_baseline(self, 'role_literals_py', role_literals.repo_py_sites())

    def test_js_role_literals_match_baseline(self):
        assert_matches_baseline(self, 'role_literals_js', role_literals.repo_js_sites())
