"""
Round 2, R5 step 3 — SQL injection: the Finance GL filters (apps/finance/gl, built after Batch 1).

The GL screens filter PostgreSQL through the ORM, and the drafting engine reads SOFTECH through
`apps/finance/queries/sybase_gl.py`, whose four builders interpolate only `date.isoformat()` and
module constants (the reason given for their bandit B608 suppressions). This pushes the Batch-1 payload set
through every GL query parameter and proves:

  • no filter answers 500, and none reaches SOFTECH;
  • a payload matches nothing (it is text, not SQL) and no table loses or gains a row;
  • the drafting run refuses a payload date before any SOFTECH read;
  • the SOFTECH builders refuse anything that is not a real date.
"""
import datetime

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry
from apps.finance.queries import sybase_gl
from apps.tests.factories import make_user

from .sql_recorder import RecordingSybase

BASE = '/api/finance/gl/'

# The Batch-1 payload set (test_sqli_*.py), plus LIKE / comment / stacked-statement forms.
PAYLOADS = [
    "1' OR '1'='1",
    "'; DROP TABLE finance_glaccount; --",
    "1; SELECT * FROM users_staffprofile",
    "' UNION SELECT username, password FROM auth_user --",
    "1) OR (1=1",
    "%' OR 1=1 --",
    "\\'; WAITFOR DELAY '0:0:5' --",
    "1/**/OR/**/1=1",
]

# (path, the query parameters each payload is put in)
GET_FILTERS = [
    ('groups/', ['q']),
    ('accounts/', ['q', 'group', 'active']),
    ('entries/', ['q', 'status', 'book', 'from', 'to', 'account', 'branch', 'party', 'source']),
    ('reports/trial-balance/', ['from', 'to', 'branch', 'by', 'closing_stock']),
    ('reports/account-statement/', ['code', 'from', 'to', 'party', 'branch']),
    ('reports/statements/', ['from', 'to', 'closing_stock']),
    ('reports/position/', ['as_of']),
    ('reports/branch-pl/', ['from', 'to']),
    ('reports/comparison/', ['years']),
    ('parties/', ['q', 'type', 'status']),
    ('parties/persons/', ['q', 'type']),
    ('maps/', ['kind', 'q']),
    ('rules/', ['q', 'status']),
    ('exceptions/', ['kind', 'source_type', 'status', 'q']),
    ('exceptions/counts/', ['kind']),
    ('exceptions/unmapped-values/', ['kind']),
    ('drafting/runs/', ['limit', 'status']),
]


class GLFilterInjectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)
        cash = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        GLAccount.objects.create(code='1101', name='الخزينة', group=cash, nature='debit',
                                 account_type='asset', statement_line='cash')

    def setUp(self):
        _, _, self.c = make_user('gl_sqli_admin', role='admin', access_all=True)

    def _counts(self):
        return (GLAccount.objects.count(), GLAccountGroup.objects.count(),
                LedgerEntry.objects.count())

    def test_every_filter_takes_payloads_as_text(self):
        before = self._counts()
        with RecordingSybase() as rec:
            for path, params in GET_FILTERS:
                for name in params:
                    for payload in PAYLOADS:
                        with self.subTest(path=path, param=name, payload=payload):
                            r = self.c.get(BASE + path, {name: payload})
                            self.assertIn(r.status_code, (200, 400, 404), r.content[:300])
        self.assertEqual(rec.calls, [], 'a GL filter reached SOFTECH')
        self.assertEqual(self._counts(), before)

    def test_text_search_payload_matches_nothing(self):
        for payload in PAYLOADS:
            r = self.c.get(BASE + 'accounts/', {'q': payload})
            self.assertEqual(r.status_code, 200)
            rows = r.data if isinstance(r.data, list) else r.data.get('results', r.data)
            self.assertFalse(rows, payload)

    def test_drafting_run_refuses_payload_dates_before_softech(self):
        with RecordingSybase() as rec:
            for payload in PAYLOADS:
                for body in ({'date_from': payload, 'date_to': '2026-03-31'},
                             {'date_from': '2026-03-01', 'date_to': payload},
                             {'date_from': '2026-03-01', 'date_to': '2026-03-31',
                              'source_types': [payload]}):
                    with self.subTest(body=body):
                        r = self.c.post(BASE + 'drafting/run/', body, format='json')
                        self.assertIn(r.status_code, (400, 403), r.content[:300])
        self.assertEqual(rec.calls, [])


class SybaseGlBuilderTests(SimpleTestCase):
    """The bandit B608 suppression reason, re-checked (R5 step 7): only real dates reach the SQL text."""

    BUILDERS = (sybase_gl.sql_branchesales, sybase_gl.sql_credit_docs, sybase_gl.sql_cheques,
                sybase_gl.sql_expenses)

    def test_text_is_refused(self):
        d = datetime.date(2026, 3, 1)
        for build in self.BUILDERS:
            for payload in PAYLOADS:
                with self.subTest(build=build.__name__, payload=payload):
                    with self.assertRaises((AttributeError, TypeError)):
                        build(payload, d)
                    with self.assertRaises((AttributeError, TypeError)):
                        build(d, payload)

    def test_only_iso_dates_are_interpolated(self):
        d1, d2 = datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)
        for build in self.BUILDERS:
            sql = build(d1, d2)
            self.assertIn("'2026-03-01'", sql)
            self.assertIn("'2026-04-01'", sql)             # the exclusive upper bound
            self.assertNotIn(';', sql)
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'), build.__name__)
