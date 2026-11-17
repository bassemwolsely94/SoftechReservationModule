"""ETA production code-usage mirror: paging, failures, matching, report, endpoint. A fake reader; never real HTTP."""
from unittest import mock

from django.test import TestCase

from apps.catalog.models import Item, ItemBarcode
from apps.tax_invoicing import eta_codes
from apps.tax_invoicing.models import EtaCodeUsage, TaxItemProfile
from apps.tests.test_tax_invoicing import Fixture, api


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.content = status, body, b'x'
        self.text = ''
        self.headers = {}

    def json(self):
        return self._body


class FakeReader:
    def __init__(self, pages, fail_at=None):
        self.pages, self.fail_at, self.calls = pages, fail_at, []

    def enabled(self):
        return True

    def why_not(self):
        return ''

    def get(self, path, params=None):
        n = params['Pn']
        self.calls.append(n)
        if self.fail_at == n:
            raise eta_codes.EtaUncertain('down')
        if self.pages is None:
            return Resp(404, {})
        return Resp(200, self.pages[n - 1] if n <= len(self.pages) else {'result': []})


def row(code, status='Approved', **kw):
    return {'itemCode': code, 'status': status, 'activeFrom': '2024-05-01T00:00:00', 'activeTo': None, **kw}


class FetchTests(Fixture, TestCase):
    def setUp(self):
        self.build('c1')

    def run_fetch(self, reader, **kw):
        with mock.patch.object(eta_codes, 'EtaReader', return_value=reader):
            return eta_codes.fetch('production', **{'page_size': 2, **kw})

    def test_same_code_approved_then_rejected_is_held(self):
        out = self.run_fetch(FakeReader([[row('EG-100200300-A1'), row('X1')],
                                         [row('EG-100200300-A1', 'Rejected', activeFrom='2023-01-01'), row('X2')]]))
        self.assertTrue(out['complete'])
        u = EtaCodeUsage.objects.get(item_code='EG-100200300-A1')
        self.assertEqual(u.status, 'Approved')

    def test_newer_rejected_beside_older_approved_still_held(self):
        self.run_fetch(FakeReader([[row('EG-100200300-A1', 'Rejected', activeFrom='2025-06-01',
                                        codeUsageRequestID=9),
                                    row('EG-100200300-A1', 'Approved', activeFrom='2024-01-01',
                                        codeUsageRequestID=5)]]))
        u = EtaCodeUsage.objects.get(item_code='EG-100200300-A1')
        self.assertEqual((u.status, u.request_id), ('Approved', '5'))

    def test_partial_fetch_does_not_downgrade_stored_approved(self):
        self.run_fetch(FakeReader([[row('EG-100200300-A1'), row('X1')]]))
        self.run_fetch(FakeReader([[row('EG-100200300-A1', 'Rejected'), row('X1')]], fail_at=2))
        self.assertEqual(EtaCodeUsage.objects.get(item_code='EG-100200300-A1').status, 'Approved')

    def test_parent_item_code_is_kept_as_the_brick(self):
        self.run_fetch(FakeReader([[row('EG-100200300-A1', parentItemCode='10000673', codeTypeName='EGS')]]))
        self.assertEqual(EtaCodeUsage.objects.get(item_code='EG-100200300-A1').gpc, '10000673')

    def test_total_pages_stops_clamped_paging(self):
        full = {'result': [row('A'), row('B')], 'metadata': {'totalPages': 1}}
        r = FakeReader([full] * 50)    # ETA clamps an out-of-range Pn to the last page
        out = self.run_fetch(r)
        self.assertTrue(out['complete'])
        self.assertEqual(r.calls, [1])

    def test_short_page_ends_the_fetch(self):
        r = FakeReader([[row('A'), row('B')], [row('C')]])
        out = self.run_fetch(r)
        self.assertEqual((out['complete'], r.calls), (True, [1, 2]))

    def test_max_pages_is_incomplete_with_error(self):
        out = self.run_fetch(FakeReader([[row('A'), row('B')], [row('C'), row('D')]]), max_pages=2)
        self.assertFalse(out['complete'])
        self.assertTrue(out['error'])

    def test_404_after_a_full_page_is_incomplete(self):
        class R(FakeReader):
            def get(self, path, params=None):
                if params['Pn'] == 2:
                    return Resp(404, {})
                return super().get(path, params)
        out = self.run_fetch(R([[row('A'), row('B')]]))
        self.assertFalse(out['complete'])
        self.assertTrue(out['error'])
        self.assertEqual(EtaCodeUsage.objects.count(), 2)

    def test_two_pages_then_empty_is_complete_and_stores_every_status(self):
        r = FakeReader([{'result': [row('EG-100200300-A1'), row('EG-100200300-A2', 'Rejected')]},
                        [row('6221234567890', codeType='GS1')]])
        out = self.run_fetch(r)
        self.assertEqual((out['pages'], out['rows'], out['complete']), (2, 3, True))
        self.assertEqual(EtaCodeUsage.objects.count(), 3)
        u = EtaCodeUsage.objects.get(item_code='EG-100200300-A1')
        self.assertEqual((u.code_type, str(u.active_from), u.itemcode), ('EGS', '2024-05-01', 'A1'))
        self.assertTrue(EtaCodeUsage.objects.filter(status='Rejected').exists())

    def test_refetch_does_not_duplicate(self):
        pages = [{'items': [row('EG-100200300-A1')]}]
        self.run_fetch(FakeReader(pages))
        self.run_fetch(FakeReader(pages))
        self.assertEqual(EtaCodeUsage.objects.count(), 1)

    def test_404_first_page_is_no_rows_complete(self):
        out = self.run_fetch(FakeReader(None))
        self.assertEqual((out['rows'], out['complete'], out['error']), (0, True, ''))

    def test_failure_midway_keeps_rows_and_is_incomplete(self):
        out = self.run_fetch(FakeReader([[row('EG-100200300-A1'), row('X9')], [row('EG-100200300-A2')]], fail_at=2))
        self.assertFalse(out['complete'])
        self.assertTrue(out['error'])
        self.assertEqual(EtaCodeUsage.objects.count(), 2)

    def test_disabled_reader_does_not_fetch(self):
        out = eta_codes.fetch('production')
        self.assertFalse(out['complete'])
        self.assertTrue(out['error'])


class MatchAndReportTests(Fixture, TestCase):
    def setUp(self):
        self.build('c2')
        for code in ('A1', 'A2', 'A3', 'S1'):
            Item.objects.create(softech_id=code, name=f'Item {code}')
        ItemBarcode.objects.create(item=Item.objects.get(softech_id='A3'), barcode='6221111111111')
        for code, st in (('EG-100200300-A1', 'Approved'), ('EG-100200300-A2', 'Rejected'), ('6221111111111', 'Approved'),
                         ('EG-999-ZZ', 'Approved')):
            EtaCodeUsage.objects.create(system='production', code_type='GS1' if code[0] == '6' else 'EGS',
                                        item_code=code, status=st)
        for code in ('S1', 'A1'):    # the sheet
            TaxItemProfile.objects.create(softech_itemcode=code, list_status=TaxItemProfile.LIST_WHITE,
                                          eta_code='x', coding_env='')

    def test_match_egs_and_gs1(self):
        self.assertEqual(eta_codes.match('production'), 3)
        got = dict(EtaCodeUsage.objects.values_list('item_code', 'itemcode'))
        self.assertEqual(got['EG-100200300-A1'], 'A1')
        self.assertEqual(got['6221111111111'], 'A3')
        self.assertEqual(got['EG-999-ZZ'], '')

    def test_report_buckets_count_only_approved(self):
        eta_codes.match('production')
        rep = eta_codes.report('production')
        self.assertEqual(sorted(x['itemcode'] for x in rep['on_eta_not_in_sheet']), ['', 'A3'])
        self.assertEqual(rep['in_sheet_not_on_eta'], ['S1'])
        self.assertEqual(rep['counts']['active'], 3)
        self.assertEqual(rep['counts']['usages'], 4)


class EndpointTests(Fixture, TestCase):
    def setUp(self):
        self.build('c3')

    def test_accountant_reads_and_pharmacist_is_refused(self):
        r = api(self.accountant).get('/api/tax-invoicing/codes/eta-holds/', {'system': 'production'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('counts', r.json())
        self.assertEqual(api(self.pharmacist).get('/api/tax-invoicing/codes/eta-holds/').status_code, 403)
        self.assertEqual(api(self.accountant).get('/api/tax-invoicing/codes/eta-holds/', {'system': 'x'}).status_code, 400)
