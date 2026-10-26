"""
SQL injection — invoice OCR code recall (apps/invoices/supplier_items.resolve_codes).
Printed supplier codes come from an uploaded invoice image; they must be bound.
"""
from django.test import SimpleTestCase

from apps.invoices.supplier_items import resolve_codes

from .sql_recorder import RecordingSybase, assert_payload_bound

PAYLOAD = "1' OR '1'='1"


class ResolveCodesTests(SimpleTestCase):

    def _run(self, codes, rows=None):
        import config.sybase
        with RecordingSybase(rows=rows) as rec:
            out = resolve_codes(config.sybase.get_sybase_connection(), '1268', codes)
        return out, rec

    def test_ocr_codes_bound(self):
        _, rec = self._run(['A1', PAYLOAD])
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_long_lists_chunked_under_400(self):
        codes = [f'C{i}' for i in range(900)]
        _, rec = self._run(codes)
        self.assertTrue(all(len(p) <= 400 for _, p in rec.calls))
        self.assertEqual({c for _, p in rec.calls for c in p if c in codes}, set(codes))

    def test_ambiguous_codes_still_dropped(self):
        out, _ = self._run(['A1', 'B2'], rows=[('A1', 'IT1'), ('B2', 'IT2'), ('B2', 'IT3')])
        self.assertEqual(out, {'A1': 'IT1'})
