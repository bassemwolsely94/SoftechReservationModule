"""C23 — saved filters / default views per user on worklist screens (/api/personal/saved-views/).

Required by the audit card: a user sees only their own views and views shared with their role;
invalid filter keys are ignored. Plus: changes are owner-only (404 for anyone else), one default
per screen, sharing goes to the owner's own role only, unknown screens are refused.
"""
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.personal.models import SavedView
from apps.personal.saved_views import SCREENS, clean_filters
from apps.tests.factories import make_anon_client, make_branch, make_pharmacist, make_user

URL = '/api/personal/saved-views/'
SCREEN = 'cash.dead_stock'


class CleanFiltersTests(SimpleTestCase):
    def test_unknown_keys_are_dropped(self):
        out, dropped = clean_filters(SCREEN, {'lane': 'a', 'branch': ['101', '102'], 'evil': 1, 'is_staff': True})
        self.assertEqual(out, {'lane': 'a', 'branch': ['101', '102']})
        self.assertEqual(dropped, ['evil', 'is_staff'])

    def test_values_are_plain_json(self):
        out, dropped = clean_filters(SCREEN, {'lane': {'x': 1}, 'q': 'x' * 500, 'branch': ['1', {'a': 1}, None, 2]})
        self.assertNotIn('lane', out)
        self.assertEqual(len(out['q']), 200)
        self.assertEqual(out['branch'], ['1', 2])
        self.assertEqual(dropped, ['lane'])

    def test_nested_allow_list(self):
        out, dropped = clean_filters('purchasing', {'abc': 'A', 'item_filters': {'supplier_code': ['9'], 'hack': 1}})
        self.assertEqual(out, {'abc': 'A', 'item_filters': {'supplier_code': ['9']}})
        self.assertEqual(dropped, ['item_filters.hack'])

    def test_unknown_screen_keeps_nothing(self):
        self.assertEqual(clean_filters('nope', {'a': 1})[0], {})

    def test_size_cap(self):
        with self.assertRaises(ValueError):
            clean_filters('transits', {k: ['x' * 200] * 300 for k in SCREENS['transits']})


class SavedViewApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.u1, cls.p1, _ = make_pharmacist('sv_owner', branch=cls.branch)
        cls.u2, cls.p2, _ = make_pharmacist('sv_colleague', branch=cls.branch)
        cls.u3, cls.p3, _ = make_user('sv_other_role', role='salesperson', branch=cls.branch)

    def setUp(self):
        self.c1, self.c2, self.c3 = (self._client(u) for u in (self.u1, self.u2, self.u3))

    @staticmethod
    def _client(user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _create(self, client=None, **kw):
        body = {'screen': SCREEN, 'name': 'فرعي', 'filters': {'branch': ['101'], 'x': 1}, **kw}
        return (client or self.c1).post(URL, body, format='json')

    def test_anonymous_refused(self):
        self.assertEqual(make_anon_client().get(URL, {'screen': SCREEN}).status_code, 401)

    def test_create_drops_invalid_keys(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['filters'], {'branch': ['101']})
        self.assertEqual(r.data['dropped'], ['x'])
        self.assertTrue(r.data['mine'])

    def test_unknown_screen_and_blank_name_refused(self):
        self.assertEqual(self.c1.get(URL).status_code, 400)
        self.assertEqual(self._create(screen='nope').status_code, 400)
        self.assertEqual(self._create(name='  ').status_code, 400)

    def test_duplicate_name_refused(self):
        self._create()
        self.assertEqual(self._create().status_code, 400)

    def test_user_sees_only_own_and_role_shared(self):
        self._create(name='خاص')
        self._create(name='مشترك', shared=True)
        self._create(client=self.c3, name='مبيعات', shared=True)

        def names(c):
            return sorted(r['name'] for r in c.get(URL, {'screen': SCREEN}).data['results'])
        self.assertEqual(names(self.c1), ['خاص', 'مشترك'])
        self.assertEqual(names(self.c2), ['مشترك'])          # same role: only the shared one
        self.assertEqual(names(self.c3), ['مبيعات'])          # other role: none of the pharmacist's
        shared = self.c2.get(URL, {'screen': SCREEN}).data['results'][0]
        self.assertFalse(shared['mine'])
        self.assertTrue(shared['owner_name'])

    def test_shared_goes_to_owner_role_only(self):
        self._create(shared=True)
        self.assertEqual(SavedView.objects.get().shared_role, self.p1.role)

    def test_only_owner_changes_or_deletes(self):
        vid = self._create(shared=True).data['id']
        self.assertEqual(self.c2.patch(f'{URL}{vid}/', {'name': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.c2.delete(f'{URL}{vid}/').status_code, 404)
        self.assertEqual(self.c1.patch(f'{URL}{vid}/', {'name': 'جديد', 'filters': {'lane': 'b', 'bad': 1}},
                                       format='json').data['filters'], {'lane': 'b'})
        self.assertEqual(self.c1.delete(f'{URL}{vid}/').status_code, 204)
        self.assertFalse(SavedView.objects.exists())

    def test_one_default_per_screen(self):
        a = self._create(name='أ', is_default=True).data['id']
        b = self._create(name='ب').data['id']
        r = self.c1.patch(f'{URL}{b}/', {'is_default': True}, format='json')
        self.assertTrue(r.data['is_default'])
        self.assertFalse(SavedView.objects.get(pk=a).is_default)
        self.assertEqual(SavedView.objects.filter(staff=self.p1, is_default=True).count(), 1)

    def test_shared_view_is_never_someone_elses_default(self):
        self._create(shared=True, is_default=True)
        row = self.c2.get(URL, {'screen': SCREEN}).data['results'][0]
        self.assertFalse(row['is_default'])
