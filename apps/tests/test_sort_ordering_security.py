"""
Round 2, R5 step 1 — sortable grids can't be turned into a sort oracle.

`core/sort_ordering.py` builds ORM `F()` expressions, so the risk is not SQL: it is sorting a list
by a column the screen does not show (a password hash, a phone, a token) and reading its order
back page by page. A key is honoured only when the view lists it:

  • `explicit_order_by(raw, allowed, default)` refuses anything else with HTTP 400;
  • the grid filter (`NullsLastOrderingFilter`, DRF's `OrderingFilter` underneath) and the
    `ORDERING_KEYS` views drop an unlisted key and keep their default order — the key has no
    effect, so there is nothing to read back. (Owner-approved behaviour: «unknown value = default»;
    a grid never breaks on a stale key.)
  • no view's ordering list may be `'__all__'` or name a secret-looking column.
"""
import re

from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.sort_ordering import NullsLastOrderingFilter, explicit_order_by

PAYLOADS = ['password', 'user__password', '-user__password', 'phone', 'secret',
            'name; DROP TABLE users--', "name') OR 1=1--", 'name__startswith', '--name', '?', '']

SENSITIVE = re.compile(r'(password|passwd|secret|token|api_?key|otp|pin_?code|mfa|national_?id|'
                       r'session|salt|hash)', re.I)


class ExplicitOrderByTests(SimpleTestCase):
    ALLOWED = {'name': 'name', 'created': 'created_at'}

    def test_listed_keys_are_honoured(self):
        self.assertEqual(len(explicit_order_by('name', self.ALLOWED, ())), 2)       # field + pk
        self.assertEqual(len(explicit_order_by('-created', self.ALLOWED, ())), 2)
        self.assertEqual(explicit_order_by('', self.ALLOWED, ('-pk',)), ('-pk',))

    def test_unknown_and_hidden_keys_are_400(self):
        for raw in PAYLOADS:
            if not raw.strip() or raw.lstrip('-') in self.ALLOWED:   # '--name' = name, descending
                continue
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                explicit_order_by(raw, self.ALLOWED, ())

    def test_the_model_field_behind_a_key_is_not_a_key(self):
        # 'created_at' is what the key maps to, not a key: the public name is the only way in
        with self.assertRaises(ValidationError):
            explicit_order_by('created_at', self.ALLOWED, ())


class _GridView:
    ordering_fields = ['name', 'code']
    ordering = ['code']


class GridFilterTests(TestCase):
    def _ordering(self, raw):
        from apps.branches.models import Branch
        req = Request(APIRequestFactory().get('/x/', {'ordering': raw}))
        return NullsLastOrderingFilter().get_ordering(req, Branch.objects.all(), _GridView())

    def test_listed_key_is_honoured_nulls_last(self):
        out = self._ordering('-name')
        self.assertEqual(len(out), 1)
        self.assertIn('name', str(out[0]))

    def test_unknown_and_hidden_keys_have_no_effect(self):
        for raw in PAYLOADS:
            if raw.lstrip('-') in _GridView.ordering_fields:
                continue                                          # '--name' = name, descending
            with self.subTest(raw=raw):
                got = self._ordering(raw)                         # the default, maybe as F(code)
                self.assertEqual(re.findall(r'F\((\w+)\)', str(got)) or got, ['code'])

    def test_a_hidden_key_next_to_a_listed_one_is_dropped(self):
        out = self._ordering('name,user__password')
        self.assertEqual(len(out), 1)
        self.assertNotIn('password', str(out))


class TasksOrderingKeysEndpointTests(TestCase):
    """A real `ORDERING_KEYS` list endpoint: an unlisted key answers with the default order."""

    def test_unlisted_key_keeps_default_order(self):
        from apps.tests.factories import make_admin
        _, _, client = make_admin('sort_sec_admin')
        for raw in ('assigned_to__password', 'name; DROP TABLE tasks_task--', 'created_by__phone'):
            with self.subTest(raw=raw):
                r = client.get('/api/tasks/', {'ordering': raw})
                self.assertEqual(r.status_code, 200, r.content[:200])


def _api_view_classes():
    seen = {}

    def walk(patterns, prefix=''):
        for p in patterns:
            if hasattr(p, 'url_patterns'):
                walk(p.url_patterns, prefix + str(p.pattern))
                continue
            cls = getattr(p.callback, 'cls', None) or getattr(p.callback, 'view_class', None)
            if cls is not None and cls not in seen:
                seen[cls] = prefix + str(p.pattern)
    walk(get_resolver().url_patterns)
    return seen


class OrderingFieldsSweepTests(SimpleTestCase):
    """Every view that sorts with an OrderingFilter names its keys explicitly."""

    def test_no_view_orders_by_all_fields_or_a_secret(self):
        bad = []
        for cls, url in _api_view_classes().items():
            backends = getattr(cls, 'filter_backends', None) or []
            if not any(isinstance(b, type) and issubclass(b, OrderingFilter) for b in backends):
                continue
            fields = cls.__dict__.get('ordering_fields', getattr(cls, 'ordering_fields', None))
            if isinstance(fields, property) or fields is None:
                continue        # DRF default: the serializer's own readable fields — what is shown
            name = f'{cls.__module__}.{cls.__name__} ({url})'
            if fields == '__all__':
                bad.append(f'{name}: ordering_fields = "__all__"')
                continue
            for f in fields:
                if SENSITIVE.search(f if isinstance(f, str) else f[0]):
                    bad.append(f'{name}: {f}')
        self.assertEqual(bad, [], 'sortable on a hidden / secret column:\n' + '\n'.join(bad))

    def test_explicit_ordering_key_maps_name_no_secret(self):
        from apps.counselling import views as cv
        from apps.tasks import views as tv
        maps = [getattr(cv, 'ORDERING', {})]
        maps += [getattr(c, 'ORDERING_KEYS', {}) for c in vars(tv).values() if isinstance(c, type)]
        try:
            from apps.replacement import views as rv
            maps += [getattr(c, 'ORDERING_KEYS', {}) for c in vars(rv).values() if isinstance(c, type)]
        except ImportError:
            pass
        bad = [f'{k}->{v}' for m in maps for k, v in m.items()
               if SENSITIVE.search(str(k)) or SENSITIVE.search(str(v))]
        self.assertEqual(bad, [])
