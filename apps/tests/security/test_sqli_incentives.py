"""
SQL injection — incentives (apps/incentives/engine.py): the near-expiry stock report
and the sales/returns readers behind incentive calculation. Every value reaches SOFTECH
as a bound parameter.
"""
from datetime import date

from django.test import SimpleTestCase, TestCase

from apps.incentives import engine
from apps.tests.factories import make_user

from .sql_recorder import RecordingSybase, assert_payload_bound

PAYLOAD = "1' OR '1'='1"


class NearExpiryEngineTests(SimpleTestCase):

    def test_store_and_item_codes_bound(self):
        for kw in ({'store_codes': ['101', PAYLOAD]}, {'item_codes': ['IT001', PAYLOAD]}):
            with RecordingSybase() as rec:
                engine.fetch_near_expiry_stock(90, **kw)
            assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_rowcount_set_and_reset_around_the_select(self):
        with RecordingSybase() as rec:
            engine.fetch_near_expiry_stock(90, limit=50)
        sqls = [s.strip() for s, _ in rec.calls]
        self.assertEqual(sqls[0], 'SET ROWCOUNT 50')
        self.assertEqual(sqls[-1], 'SET ROWCOUNT 0')
        self.assertTrue(any('stkbalexpiry' in s for s in sqls[1:-1]))
        self.assertFalse(any('SET ROWCOUNT' in s for s in sqls[1:-1]))

    def test_quarantine_bound_dates_literal(self):
        with RecordingSybase() as rec:
            engine.fetch_near_expiry_stock(30)
        select, params = next((s, p) for s, p in rec.calls if 'stkbalexpiry' in s)
        self.assertNotIn("'102'", select)
        self.assertIn('102', params)
        self.assertRegex(select, r"itemexpirydate >= '\d{4}-\d{2}-\d{2} 00:00:00'")
        self.assertFalse(any('-' in str(p) for p in params))

    def test_401_item_codes_are_chunked_and_merged_in_order(self):
        codes = [str(5000 + i) for i in range(401)]
        rows = [('5001', date(2027, 1, 2), 5, '0', '101', 'B', 'x'),
                ('5000', date(2027, 1, 1), 5, '0', '101', 'B', 'y')]
        with RecordingSybase(rows=rows) as rec:
            out = engine.fetch_near_expiry_stock(730, item_codes=codes, limit=3)
        selects = [(s, p) for s, p in rec.calls if 'stkbalexpiry' in s]
        self.assertEqual(len(selects), 2)
        self.assertTrue(all(sum(1 for v in p if v in codes) <= 400 for _, p in selects))
        self.assertEqual(len(out), 3)                                  # limit across chunks
        self.assertEqual([r['itemcode'] for r in out][:1], ['5000'])   # most urgent first


class IncentiveReaderTests(SimpleTestCase):

    def test_fetch_rows_binds_person_codes_and_doc_code(self):
        for kw in ({'person_codes': ['1509', PAYLOAD]},):
            for returns in (False, True):
                with RecordingSybase() as rec:
                    engine._fetch_rows('115', date(2026, 10, 1), date(2026, 10, 31),
                                       use_returns_template=returns, **kw)
                assert_payload_bound(self, rec.calls, PAYLOAD)
        with RecordingSybase() as rec:
            engine._fetch_rows(PAYLOAD, date(2026, 10, 1), date(2026, 10, 31))
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_cross_period_returns_binds_person_codes(self):
        with RecordingSybase() as rec:
            engine._fetch_cross_period_returns(date(2026, 10, 31), person_codes=[PAYLOAD])
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_over_400_person_codes_filter_in_python(self):
        codes = [str(2000 + i) for i in range(401)]
        rows = [('d1', '2000', None), ('d2', '9999', None), ('d3', '2400', None)]
        with RecordingSybase(rows=rows) as rec:
            out = engine._fetch_rows('115', date(2026, 10, 1), date(2026, 10, 31), person_codes=codes)
            out2 = engine._fetch_cross_period_returns(date(2026, 10, 31), person_codes=codes)
        self.assertTrue(all(len(p) <= 1 for _, p in rec.calls))          # no IN list sent
        self.assertEqual([r[0] for r in out], ['d1', 'd3'])
        self.assertEqual([r[0] for r in out2], ['d1', 'd3'])

    def test_duplicate_person_codes_never_drop_the_filter(self):
        codes = [str(2000 + i) for i in range(400)] + ['2000']      # 401 entries, 400 unique
        rows = [('d1', '2000', None), ('d2', '9999', None)]
        with RecordingSybase(rows=rows) as rec:
            out = engine._fetch_rows('115', date(2026, 10, 1), date(2026, 10, 31), person_codes=codes)
        self.assertIn('m.usercode IN', rec.calls[0][0])               # filtered in SQL
        self.assertEqual(len(rec.calls[0][1]), 1 + 400)               # doc code + unique codes
        self.assertEqual(len(out), 2)                                 # the double sees all rows

    def test_dates_are_literal_iso_dates(self):
        with RecordingSybase() as rec:
            engine._fetch_rows('115', date(2026, 10, 1), date(2026, 10, 31))
            engine._fetch_cross_period_returns(date(2026, 10, 31))
        self.assertIn("m.docdate >= '2026-10-01 00:00:00'", rec.calls[0][0])
        self.assertIn("CONVERT(DATETIME, '2026-10-31')", rec.calls[0][0])
        self.assertEqual(rec.calls[0][1], ['115'])
        self.assertIn("m.docdate >  '2026-10-31 23:59:59'", rec.calls[1][0])
        self.assertEqual(rec.calls[1][1], [])


class NearExpiryApiTests(TestCase):

    def setUp(self):
        _, _, self.c = make_user('ne_admin', role='admin', access_all=True)

    def test_injection_codes_rejected(self):
        for q in ({'store_codes': "101','x"}, {'item_codes': PAYLOAD}):
            with RecordingSybase() as rec:
                r = self.c.get('/api/incentives/near-expiry-stock/', q)
            self.assertEqual(r.status_code, 400, q)
            self.assertEqual(rec.calls, [])

    def test_too_many_codes_rejected(self):
        q = {'item_codes': ','.join(str(i) for i in range(2001))}
        self.assertEqual(self.c.get('/api/incentives/near-expiry-stock/', q).status_code, 400)

    def test_real_codes_accepted(self):
        with RecordingSybase() as rec:
            r = self.c.get('/api/incentives/near-expiry-stock/',
                           {'store_codes': '101,0130', 'item_codes': 'IT001,12345'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(rec.calls)
