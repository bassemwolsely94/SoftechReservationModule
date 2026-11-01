"""
apps/tests/test_track_trace.py

P-58 (docs/product-review/06_SPEC_P-58): EDA track-and-trace foundation, DORMANT.
  • parse_gs1: fixed + variable AIs, GS separator, ]d2 prefix, bracketed form,
    bad GTIN check digit rejected, expiry day 00 = end of month
  • TRACK_TRACE_ENABLED=False (default): recording does nothing
  • enabled: receive + sell on one pack = 1 PackCode, 2 events; a 2nd receive is flagged
  • the parse diagnostic is admin-only
Nothing here touches SOFTECH.
"""
import datetime

from django.test import SimpleTestCase, TestCase, override_settings

from apps.catalog.gs1 import GS1Error, parse_gs1
from .factories import make_admin, make_branch, make_item, make_pharmacist

GS = '\x1d'
# a valid GTIN-14 (check digit 8)
GTIN = '06221025001238'


class ParserTests(SimpleTestCase):

    def test_fixed_then_variable_with_gs(self):
        raw = f']d201{GTIN}17271130{GS}10LOT42{GS}21SER0001'
        p = parse_gs1(raw)
        self.assertEqual(p['gtin'], GTIN)
        self.assertEqual(p['expiry'], datetime.date(2027, 11, 30))
        self.assertEqual(p['batch'], 'LOT42')
        self.assertEqual(p['serial'], 'SER0001')
        self.assertEqual(p['raw'], raw)

    def test_last_variable_field_needs_no_separator(self):
        p = parse_gs1(f'01{GTIN}21ABC{GS}10B1')
        self.assertEqual((p['serial'], p['batch']), ('ABC', 'B1'))

    def test_bracketed_human_readable_form(self):
        p = parse_gs1(f'(01){GTIN}(17)270600(10)L9(21)S9')
        self.assertEqual(p['expiry'], datetime.date(2027, 6, 30))       # day 00 = end of month
        self.assertEqual((p['batch'], p['serial']), ('L9', 'S9'))

    def test_bad_check_digit_rejected(self):
        with self.assertRaises(GS1Error):
            parse_gs1(f'01{GTIN[:-1]}5' + '21X')

    def test_missing_gtin_rejected(self):
        with self.assertRaises(GS1Error):
            parse_gs1('21SERIAL')

    def test_plain_ean_is_not_gs1(self):
        with self.assertRaises(GS1Error):
            parse_gs1('6221025001234')


class RecordingTests(TestCase):

    def setUp(self):
        from apps.catalog.models import ItemBarcode
        self.item = make_item()
        ItemBarcode.objects.create(item=self.item, barcode=GTIN[1:])      # EAN-13 form
        self.branch = make_branch()
        _, self.staff, _ = make_pharmacist(branch=self.branch)
        self.raw = f'01{GTIN}17271100{GS}10LOT1{GS}21S1'

    def test_disabled_records_nothing(self):
        from apps.trace import service
        from apps.trace.models import PackCode, PackEvent
        self.assertIsNone(service.record(self.raw, 'receive', branch=self.branch, staff=self.staff))
        self.assertEqual((PackCode.objects.count(), PackEvent.objects.count()), (0, 0))

    @override_settings(TRACK_TRACE_ENABLED=True)
    def test_receive_then_sell_one_pack_two_events(self):
        from apps.trace import service
        from apps.trace.models import PackCode, PackEvent
        service.record(self.raw, 'receive', branch=self.branch, staff=self.staff,
                       doc_type='invoice_line', doc_ref='77')
        service.record(self.raw, 'sell', branch=self.branch, staff=self.staff,
                       doc_type='pos_order_line', doc_ref='88')
        pack = PackCode.objects.get()
        self.assertEqual(pack.item, self.item)
        self.assertEqual(pack.status, 'sold')
        self.assertEqual(pack.expiry, datetime.date(2027, 11, 30))
        self.assertEqual(list(PackEvent.objects.order_by('id').values_list('event', flat=True)),
                         ['receive', 'sell'])

    @override_settings(TRACK_TRACE_ENABLED=True)
    def test_second_receive_is_flagged_not_duplicated(self):
        from apps.trace import service
        from apps.trace.models import PackCode
        service.record(self.raw, 'receive', branch=self.branch, staff=self.staff)
        ev = service.record(self.raw, 'receive', branch=self.branch, staff=self.staff)
        self.assertEqual(PackCode.objects.count(), 1)
        self.assertEqual(ev.flag, 'duplicate_receive')


class ParseEndpointTests(TestCase):

    def test_admin_only(self):
        _, _, pharm = make_pharmacist()
        self.assertEqual(pharm.post('/api/trace/parse/', {'raw': '21X'}, format='json').status_code, 403)

    def test_returns_fields_and_matched_item(self):
        from apps.catalog.models import ItemBarcode
        item = make_item()
        ItemBarcode.objects.create(item=item, barcode=GTIN[1:])
        _, _, admin = make_admin('tt_admin')
        d = admin.post('/api/trace/parse/', {'raw': f'01{GTIN}21S1'}, format='json').json()
        self.assertEqual(d['gtin'], GTIN)
        self.assertEqual(d['item_id'], item.pk)
        bad = admin.post('/api/trace/parse/', {'raw': '21X'}, format='json')
        self.assertEqual(bad.status_code, 400)


class ScanHookTests(TestCase):

    def test_disabled_hook_is_404_and_stores_nothing(self):
        from apps.trace.models import PackEvent
        _, _, client = make_pharmacist()
        r = client.post('/api/trace/scan/', {'raw': f'01{GTIN}21S1', 'doc_type': 'pos_order_line',
                                             'doc_ref': '1'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(PackEvent.objects.count(), 0)

    @override_settings(TRACK_TRACE_ENABLED=True)
    def test_enabled_hook_needs_a_real_line(self):
        _, _, client = make_pharmacist()
        r = client.post('/api/trace/scan/', {'raw': f'01{GTIN}21S1', 'doc_type': 'invoice_line',
                                             'doc_ref': '999999'}, format='json')
        self.assertEqual(r.status_code, 400)


    @override_settings(TRACK_TRACE_ENABLED=True)
    def test_scan_needs_the_document_grant(self):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        RoleModuleAccess.objects.filter(role='viewer', module='pos').delete()
        RoleModuleAccess.objects.create(role='viewer', module='pos', action='view', is_allowed=True)
        module_access.clear_cache()
        from .factories import make_user
        _, _, viewer = make_user('tt_viewer', role='viewer')
        r = viewer.post('/api/trace/scan/', {'raw': f'01{GTIN}21S1', 'doc_type': 'pos_order_line',
                                             'doc_ref': '1'}, format='json')
        self.assertEqual(r.status_code, 403)
