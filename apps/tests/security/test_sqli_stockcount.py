"""
SQL injection — stock count (apps/stockcount). Every value a user types into a
stock-count session must reach SOFTECH as a bound parameter, never as SQL text.
"""
from django.test import SimpleTestCase, TestCase

from apps.stockcount import engine
from apps.tests.factories import make_branch, make_user

from .sql_recorder import RecordingSybase, assert_payload_bound

PAYLOAD = "1' OR '1'='1"


class StockCountEngineTests(SimpleTestCase):

    def test_transaction_items_binds_branch(self):
        with RecordingSybase() as rec:
            engine.fetch_transaction_items(PAYLOAD, ['10'], '2026-10-01', '2026-10-02')
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_transaction_items_binds_user_code(self):
        with RecordingSybase() as rec:
            engine.fetch_transaction_items('130', ['10'], '2026-10-01', '2026-10-02', user_code=PAYLOAD)
        assert_payload_bound(self, rec.calls, PAYLOAD)
        self.assertIn('stktransm', rec.calls[0][0])        # the user join is still there

    def test_transaction_items_binds_doccodes(self):
        with RecordingSybase() as rec:
            engine.fetch_transaction_items('130', [PAYLOAD], '2026-10-01', '2026-10-02')
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_non_date_never_reaches_sql(self):
        for df, dt in ((PAYLOAD, '2026-10-02'), ('2026-10-01', PAYLOAD)):
            with RecordingSybase() as rec:
                with self.assertRaises(ValueError):
                    engine.fetch_transaction_items('130', ['10'], df, dt)
            self.assertEqual(rec.calls, [])

    def test_dates_are_literal_iso_dates(self):
        """Date ranges stay literals (ASE 12.5 plans bound date ranges badly — see
        procurement purchases_query: 14.7 s bound vs 1.6 s literal), built only from
        real dates so nothing else can get in."""
        from datetime import date
        for df in ('2026-10-01', date(2026, 10, 1)):
            with RecordingSybase() as rec:
                engine.fetch_transaction_items('130', ['10', '25'], df, '2026-10-02')
            sql, params = rec.calls[0]
            self.assertIn("st.docdate >= '2026-10-01 00:00:00'", sql)
            self.assertIn("CONVERT(DATETIME, '2026-10-02')", sql)
            self.assertEqual(params, ['10', '25', '130'])

    def test_full_stock_binds_category_including_arabic(self):
        for cat in (PAYLOAD, 'مضادات حيوية'):
            with RecordingSybase() as rec:
                engine.fetch_full_stock('130', category_filter=cat)
            assert_payload_bound(self, rec.calls, cat)

    def test_full_stock_without_category_sends_no_category_clause(self):
        with RecordingSybase() as rec:
            engine.fetch_full_stock('130')
        self.assertNotIn('itemclassifcode = ?', rec.calls[0][0])

    def test_stock_balance_and_filtered_bind_item_codes(self):
        for fn in (engine.fetch_stock_balance, engine.fetch_filtered_stock):
            with RecordingSybase() as rec:
                fn('130', ['IT001', PAYLOAD])
            assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_item_lists_are_chunked_at_400(self):
        codes = [str(1000 + i) for i in range(401)]
        for fn in (engine.fetch_stock_balance, engine.fetch_filtered_stock):
            with RecordingSybase() as rec:
                fn('130', codes)
            self.assertEqual(len(rec.calls), 2, fn.__name__)
            self.assertTrue(all(len(p) <= 402 for _, p in rec.calls))   # 400 codes + branch
            sent = [c for _, p in rec.calls for c in p if c in codes]
            self.assertEqual(sorted(sent), sorted(codes))

    def test_empty_lists_send_nothing(self):
        with RecordingSybase() as rec:
            self.assertEqual(engine.fetch_stock_balance('130', []), {})
            self.assertEqual(engine.fetch_filtered_stock('130', []), [])
            self.assertEqual(engine.fetch_transaction_items('130', [], '2026-10-01', '2026-10-02'), [])
        self.assertEqual(rec.calls, [])


class StockCountApiTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, _, self.client_ = make_user('sc_admin', role='admin', access_all=True)

    def _create(self, **over):
        body = {'name': 'جرد', 'mode': 'transaction', 'branch_code': '130',
                'date_from': '2026-10-01', 'date_to': '2026-10-02', 'doccodes': ['10', '120']}
        body.update(over)
        return self.client_.post('/api/stockcount/sessions/', body, format='json')

    def test_real_shaped_session_is_accepted(self):
        r = self._create(item_codes_filter=['IT001', '12345'])
        self.assertEqual(r.status_code, 201, r.content)

    def test_bad_doccode_rejected(self):
        self.assertEqual(self._create(doccodes=["10') --"]).status_code, 400)

    def test_bad_branch_code_rejected(self):
        self.assertEqual(self._create(branch_code="130' OR 1=1 --").status_code, 400)

    def test_bad_item_code_rejected(self):
        self.assertEqual(self._create(item_codes_filter=["1' OR '1'='1"]).status_code, 400)

    def test_user_code_payload_reaches_softech_bound(self):
        r = self._create(user_code_filter=PAYLOAD)
        self.assertEqual(r.status_code, 201, r.content)
        with RecordingSybase() as rec:
            self.client_.post(f"/api/stockcount/sessions/{r.json()['id']}/preview-items/", {},
                              format='json')
        assert_payload_bound(self, rec.calls, PAYLOAD)
