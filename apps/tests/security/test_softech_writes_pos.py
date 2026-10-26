"""
SOFTECH write safety — POS writer date literals (Batch 2, P-1).

The POS writer inlines datetimes as  convert(datetime, '<text>')  (jConnect's bound
INSERT path doesn't land rows on this ASE). Before P-1 any text in a {'__dt__': …}
marker or a claim date went in verbatim — including claim.examdate straight from the
POST /api/pos-orders/ body. Only a real date / datetime may reach that literal.
"""
from datetime import date, datetime

from django.test import SimpleTestCase, TestCase

from apps.pos_orders import writer
from apps.tests.factories import make_branch

PAYLOAD = "2026-10-01'); DELETE FROM stktrans5 WHERE ('1'='1"


class PosDateLiteralTests(SimpleTestCase):

    def test_marker_payload_refused(self):
        with self.assertRaises(ValueError):
            writer._raw_value({'__dt__': PAYLOAD})

    def test_claim_date_payload_refused(self):
        for v in (PAYLOAD, {'__dt__': PAYLOAD}, '2026-13-45', 'tomorrow'):
            with self.assertRaises(ValueError, msg=repr(v)):
                writer._claim_dt(v)

    def test_real_dates_render_unchanged(self):
        cases = {
            '2026-10-01': "convert(datetime, '2026-10-01 00:00:00')",
            '2026-10-01 13:45:00': "convert(datetime, '2026-10-01 13:45:00')",
            date(2026, 10, 1): "convert(datetime, '2026-10-01 00:00:00')",
        }
        for v, sql in cases.items():
            self.assertEqual(writer._claim_dt(v).sql, sql, v)
        for v in ('2026-10-01 00:00:00', '2026-10-01 13:45:00.123000', '2026-10-01 13:45:00.0',
                  writer.RESERVATION_PLACEHOLDER_EXPIRY, '1900-01-01 00:00:00'):
            self.assertEqual(writer._raw_value({'__dt__': v}).sql, f"convert(datetime, '{v}')")
        self.assertIsNone(writer._claim_dt(''))
        self.assertIsNone(writer._claim_dt(None))

    def test_datetime_objects_render(self):
        self.assertEqual(writer._claim_dt(datetime(2026, 10, 1, 9, 5, 7)).sql,
                         "convert(datetime, '2026-10-01 09:05:07')")


class PosClaimSerializerTests(TestCase):

    def test_bad_examdate_rejected_at_the_api(self):
        from apps.pos_orders.serializers import OrderSerializer
        br = make_branch()
        s = OrderSerializer(data={
            'branch': br.id, 'channel': 'contract', 'doc_kind': 'sale', 'softech_pic': '130HD9668',
            'claim': {'patientno': '500145123261', 'examdate': PAYLOAD},
            'lines': [{'softech_itemcode': '404', 'qty': 1, 'item_sale_price': 10}],
        })
        self.assertFalse(s.is_valid())
        self.assertIn('claim', s.errors)
