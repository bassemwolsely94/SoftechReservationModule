"""
SQL injection — shortage supplier sourcing (apps/shortage/supplier_sourcing.py), reached
from GET /api/shortage/lists/<pk>/export-supplier-po/<suppcode>/ by any logged-in user.
"""
from unittest import mock
from urllib.parse import quote

from django.test import SimpleTestCase, TestCase

from apps.shortage.supplier_sourcing import build_sourcing
from apps.tests.factories import make_branch, make_user

from .sql_recorder import RecordingSybase, assert_payload_bound

PAYLOAD = "1' OR '1'='1"


class BuildSourcingTests(SimpleTestCase):
    """The live SOFTECH read — since P-33 (d) the fallback when our mirrors are stale."""

    def setUp(self):
        from apps.shortage import supplier_sourcing
        p = mock.patch.object(supplier_sourcing, '_mirrors_fresh', return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def test_restrict_supplier_is_bound_in_every_query(self):
        with RecordingSybase() as rec:
            build_sourcing(['IT001'], restrict_supplier=PAYLOAD)
        assert_payload_bound(self, rec.calls, PAYLOAD)
        selects = [s for s, _ in rec.calls if s.lstrip().upper().startswith('SELECT')]
        self.assertEqual(len(selects), 2)                 # itemssuppliers + history

    def test_item_codes_and_branch_are_bound(self):
        with RecordingSybase() as rec:
            build_sourcing(['IT001', PAYLOAD], restrict_supplier='1268', branch=PAYLOAD)
        assert_payload_bound(self, rec.calls, PAYLOAD)
        for sql, _ in rec.calls:
            self.assertNotIn("'IT001'", sql)

    def test_main_suppliers_are_bound(self):
        with mock.patch('apps.invoices.suppliers.main_personcodes', return_value={'1268', PAYLOAD}):
            with RecordingSybase() as rec:
                build_sourcing(['IT001'])
        assert_payload_bound(self, rec.calls, PAYLOAD)

    def test_params_stay_under_400_per_statement(self):
        codes = [str(10000 + i) for i in range(800)]
        mains = {str(9000 + i) for i in range(12)}
        with mock.patch('apps.invoices.suppliers.main_personcodes', return_value=mains):
            with RecordingSybase() as rec:
                build_sourcing(codes)
        self.assertTrue(all(len(p) <= 400 for _, p in rec.calls), max(len(p) for _, p in rec.calls))
        sent = {c for _, p in rec.calls for c in p if c in codes}
        self.assertEqual(sent, set(codes))


class SupplierPoExportApiTests(TestCase):

    def setUp(self):
        from apps.shortage.models import ShortageList
        _, _, self.c = make_user('sh_admin', role='admin', access_all=True)
        self.sl = ShortageList.objects.create(branch=make_branch(), status='open')

    def test_injection_suppcode_rejected_before_softech(self):
        with RecordingSybase() as rec:
            r = self.c.get(f'/api/shortage/lists/{self.sl.pk}/export-supplier-po/{quote(PAYLOAD)}/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(rec.calls, [])

    def test_real_suppcode_accepted(self):
        with RecordingSybase():
            r = self.c.get(f'/api/shortage/lists/{self.sl.pk}/export-supplier-po/1268/')
        self.assertEqual(r.status_code, 200)
