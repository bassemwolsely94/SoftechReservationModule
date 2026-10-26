"""
SQL injection — purchase-expiry audit (apps/batches/expiry_audit.py). The request's
branch codes reach a SOFTECH SELECT through _stock_in_arrivals.
"""
from django.test import SimpleTestCase, TestCase

from apps.batches import expiry_audit
from apps.tests.factories import make_user

from .sql_recorder import RecordingSybase, assert_payload_bound

PAYLOAD = "1' OR '1'='1"


class StockInArrivalsTests(SimpleTestCase):

    def test_branch_and_item_codes_bound(self):
        for branches, items in (([PAYLOAD], ['IT001']), (['130'], ['IT001', PAYLOAD])):
            with RecordingSybase() as rec:
                expiry_audit._stock_in_arrivals(branches, items)
            assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_doccodes_bound_too(self):
        with RecordingSybase() as rec:
            expiry_audit._stock_in_arrivals(['130'], ['IT001'])
        sql, params = rec.calls[0]
        self.assertNotIn("'10'", sql)
        for d in expiry_audit.ARRIVAL_DOCCODES:
            self.assertIn(d, params)

    def test_params_stay_under_400_and_all_items_sent(self):
        items = [str(10000 + i) for i in range(900)]
        branches = [str(100 + i) for i in range(20)]
        with RecordingSybase() as rec:
            expiry_audit._stock_in_arrivals(branches, items)
        self.assertTrue(all(len(p) <= 400 for _, p in rec.calls))
        self.assertEqual({c for _, p in rec.calls for c in p if c in items}, set(items))

    def test_empty_inputs_send_nothing(self):
        with RecordingSybase() as rec:
            self.assertEqual(expiry_audit._stock_in_arrivals([], ['1']), {})
            self.assertEqual(expiry_audit._stock_in_arrivals(['130'], []), {})
        self.assertEqual(rec.calls, [])


class ExpiryCandidatesApiTests(TestCase):

    def setUp(self):
        _, _, self.c = make_user('ex_admin', role='admin', access_all=True)

    def test_injection_branch_rejected_before_softech(self):
        with RecordingSybase() as rec:
            r = self.c.post('/api/batches/purchase-expiry/candidates/',
                            {'from': '2026-11', 'to': '2027-01', 'branches': ['130', PAYLOAD], 'min_qty': -1}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(rec.calls, [])

    def test_real_branches_accepted(self):
        with RecordingSybase():
            r = self.c.post('/api/batches/purchase-expiry/candidates/',
                            {'from': '2026-11', 'to': '2027-01', 'branches': '130,170'}, format='json')
        self.assertNotEqual(r.status_code, 400, r.content)
