"""ETA history mirror (doc 36 §history, spec 2026-11-14-eta-history-mirror-design.md)."""
import inspect
from unittest import mock

import requests
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.tax_invoicing import eta_client, eta_reader
from apps.tax_invoicing.models import EtaHistoryWindow, EtaMirrorDocument, EtaMirrorReceipt


def _response(status_code, body=None, headers=None, content=b''):
    r = mock.Mock(status_code=status_code, headers=headers or {}, content=content)
    r.json.return_value = body if body is not None else {}
    return r


TOKEN = _response(200, {'access_token': 'T', 'expires_in': 3600})
READ_BOTH = dict(TAX_ETA_READ_PREPROD_ENABLED=True, TAX_ETA_READ_PRODUCTION_ENABLED=True,
                 TAX_ETA_READ_PREPROD_CLIENT_ID='pre-id', TAX_ETA_READ_PREPROD_CLIENT_SECRET='pre-sec',
                 TAX_ETA_READ_PRODUCTION_CLIENT_ID='prod-id', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET='prod-sec',
                 TAX_ETA_ENVIRONMENT='', TAX_ETA_CLIENT_ID='', TAX_ETA_CLIENT_SECRET='')


class ReaderTests(SimpleTestCase):

    def setUp(self):
        eta_reader.reset_tokens()
        self.addCleanup(eta_reader.reset_tokens)
        sleep = mock.patch.object(eta_reader.time, 'sleep')
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_reader_cannot_send(self):
        names = {n.lower() for n in dir(eta_reader.EtaReader)}
        for word in ('submit', 'cancel', 'reject', 'decline'):
            self.assertFalse(any(word in n for n in names), word)
        source = inspect.getsource(eta_reader)
        for path in ('documentsubmissions', 'receiptsubmissions', '/state', 'cancel', 'codetypes/requests/codes'):
            self.assertNotIn(path, source, path)
        self.assertNotIn('eta_client.submit', source)

    @override_settings(**READ_BOTH)
    def test_systems_use_their_own_hosts_and_credentials(self):
        with mock.patch.object(eta_reader.requests, 'post', return_value=TOKEN) as post, \
                mock.patch.object(eta_reader.requests, 'get', return_value=_response(200, {})) as get:
            eta_reader.EtaReader('production').get('/api/v1.0/documents/recent')
            eta_reader.EtaReader('preprod').get('/api/v1.0/documents/recent')
            eta_reader.EtaReader('production').get('/api/v1.0/documents/recent')
        logins = [(c[0][0], c[1]['data']['client_id']) for c in post.call_args_list]
        self.assertEqual(logins, [('https://id.eta.gov.eg/connect/token', 'prod-id'),
                                  ('https://id.preprod.eta.gov.eg/connect/token', 'pre-id')])   # cached per system
        self.assertEqual([c[0][0] for c in get.call_args_list],
                         ['https://api.invoicing.eta.gov.eg/api/v1.0/documents/recent',
                          'https://api.preprod.invoicing.eta.gov.eg/api/v1.0/documents/recent',
                          'https://api.invoicing.eta.gov.eg/api/v1.0/documents/recent'])

    @override_settings(TAX_ETA_READ_PREPROD_ENABLED=True, TAX_ETA_READ_PREPROD_CLIENT_ID='', TAX_ETA_READ_PREPROD_CLIENT_SECRET='',
                       TAX_ETA_CLIENT_ID='send-id', TAX_ETA_CLIENT_SECRET='send-sec', TAX_ETA_ENVIRONMENT='preprod')
    def test_preprod_falls_back_to_the_sending_client_only_on_a_preprod_server(self):
        self.assertTrue(eta_reader.EtaReader('preprod').configured())
        with override_settings(TAX_ETA_ENVIRONMENT='production', TAX_ETA_READ_PRODUCTION_ENABLED=True,
                               TAX_ETA_READ_PRODUCTION_CLIENT_ID='', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET=''):
            self.assertFalse(eta_reader.EtaReader('preprod').configured())
            self.assertFalse(eta_reader.EtaReader('production').configured())     # never borrows the sending login

    @override_settings(TAX_ETA_READ_PRODUCTION_ENABLED=False, TAX_ETA_READ_PRODUCTION_CLIENT_ID='x',
                       TAX_ETA_READ_PRODUCTION_CLIENT_SECRET='y', TAX_ETA_READ_PREPROD_ENABLED=True,
                       TAX_ETA_READ_PREPROD_CLIENT_ID='', TAX_ETA_READ_PREPROD_CLIENT_SECRET='', TAX_ETA_ENVIRONMENT='')
    def test_switch_off_or_missing_credentials_makes_no_call(self):
        with mock.patch.object(eta_reader.requests, 'post') as post, mock.patch.object(eta_reader.requests, 'get') as get:
            for system in ('production', 'preprod'):
                reader = eta_reader.EtaReader(system)
                self.assertTrue(reader.why_not())
                with self.assertRaises(eta_client.EtaNotConfigured):
                    reader.get('/api/v1.0/documents/recent')
        post.assert_not_called()
        get.assert_not_called()
        with self.assertRaises(ValueError):
            eta_reader.EtaReader('staging')

    @override_settings(**READ_BOTH)
    def test_429_waits_retry_after_then_retries_once(self):
        with mock.patch.object(eta_reader.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_reader.requests, 'get',
                                  side_effect=[_response(429, headers={'Retry-After': '7'}), _response(200, {'ok': 1})]):
            r = eta_reader.EtaReader('preprod').get('/api/v1.0/documents/recent')
        self.assertEqual(r.status_code, 200)
        self.assertIn(mock.call(7.0), self.sleep.call_args_list)

    @override_settings(**READ_BOTH)
    def test_503_retries_and_a_dead_connection_is_uncertain(self):
        with mock.patch.object(eta_reader.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_reader.requests, 'get', side_effect=[_response(503), _response(200, {})]):
            self.assertEqual(eta_reader.EtaReader('preprod').get('/x').status_code, 200)
        with mock.patch.object(eta_reader.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_reader.requests, 'get', side_effect=requests.ConnectionError()):
            with self.assertRaises(eta_client.EtaUncertain):
                eta_reader.EtaReader('preprod').get('/x')


class MirrorModelTests(TestCase):

    def _doc(self, system, uuid='U1'):
        return EtaMirrorDocument.objects.create(system=system, uuid=uuid, doc_type='i', direction='sent',
                                                issued_at=timezone.now(), status='valid')

    def test_one_row_per_system_and_uuid(self):
        self._doc('preprod')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._doc('preprod')
        EtaMirrorReceipt.objects.create(system='preprod', uuid='R1', issued_at=timezone.now(), status='valid')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EtaMirrorReceipt.objects.create(system='preprod', uuid='R1', issued_at=timezone.now(), status='valid')

    def test_same_uuid_may_exist_in_both_systems(self):
        self._doc('preprod')
        self._doc('production')
        self.assertEqual(EtaMirrorDocument.objects.filter(uuid='U1').count(), 2)

    def test_one_window_per_system_kind_and_range(self):
        import datetime as dt
        d = dt.date(2024, 1, 1)
        EtaHistoryWindow.objects.create(system='preprod', kind='receipts', date_from=d, date_to=d)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EtaHistoryWindow.objects.create(system='preprod', kind='receipts', date_from=d, date_to=d)
        self.assertEqual(EtaHistoryWindow.objects.get().state, 'planned')


# ── Task 3: package backfill (eta_history) ─────────────────────────────────────────────────────

import datetime as dt  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
import zipfile  # noqa: E402

from apps.tax_invoicing import eta_history  # noqa: E402


def _zip(rows, name='part1.json'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(name, _json.dumps(rows))
    return buf.getvalue()


def _doc_row(uuid, status='Valid', issuer='499336534', total=114):
    return {'uuid': uuid, 'submissionUUID': 'S-' + uuid, 'internalId': 'INV-' + uuid, 'typeName': 'i',
            'typeVersionName': '1.0', 'issuerId': issuer, 'issuerName': 'الرزيقى', 'receiverId': '999888777',
            'receiverName': 'شركة', 'receiverType': 'B', 'dateTimeIssued': '2024-01-02T10:00:00Z',
            'dateTimeReceived': '2024-01-02T10:01:00Z', 'status': status, 'netAmount': 100, 'totalAmount': total}


def _receipt_row(uuid, status='Valid'):
    return {'header': {'uuid': uuid, 'previousUUID': 'P', 'receiptNumber': 'R-' + uuid,
                       'dateTimeIssued': '2024-01-02T10:00:00Z'},
            'seller': {'branchCode': '3', 'deviceSerialNumber': 'POS1'}, 'documentType': {'receiptType': 's'},
            'buyer': {'type': 'P'}, 'netAmount': 50, 'totalAmount': 57, 'status': status}


class FakeReader:
    """Stands in for EtaReader: records requests, answers from scripted state."""
    def __init__(self, system):
        self.system = system
        self.requests = []
        self.statuses = {}          # package id -> ETA status number
        self.packages = {}          # package id -> zip bytes
        self.too_big_over_days = None
        self.fail_with = None

    def why_not(self):
        return ''

    def request_package(self, kind, body):
        if self.fail_with:
            raise self.fail_with
        q = body['queryParameters']
        days = (dt.date.fromisoformat(q['dateTo'][:10]) - dt.date.fromisoformat(q['dateFrom'][:10])).days + 1
        if self.too_big_over_days is not None and days > self.too_big_over_days:
            raise eta_client.EtaRefused('too big', 400, {'error': {'code': 'OperationExceedsLimit'}})
        pid = f'P{len(self.requests) + 1}'
        self.requests.append((kind, body))
        return pid

    def package_requests(self, kind, page=1, size=50):
        return [{'packageId': pid, 'status': st, 'isExpired': st == 4} for pid, st in self.statuses.items()]

    def download_package(self, kind, package_id):
        return self.packages.get(package_id)


class BackfillTests(TestCase):

    def setUp(self):
        from apps.tax_invoicing.models import TaxIssuerProfile
        issuer = TaxIssuerProfile.load()
        issuer.tax_id = '499336534'
        issuer.save()
        self.fake = FakeReader('preprod')
        p = mock.patch.object(eta_history, 'EtaReader', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)

    def _window(self, kind='documents', days=1):
        d = dt.date(2024, 1, 1)
        return EtaHistoryWindow.objects.create(system='preprod', kind=kind, date_from=d, date_to=d + dt.timedelta(days=days - 1))

    def test_plan_windows_uses_4_day_receipt_and_30_day_document_windows(self):
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 8)), 2)
        self.assertEqual(eta_history.plan_windows('preprod', 'documents', dt.date(2024, 1, 1), dt.date(2024, 3, 1)), 2)   # whole windows only
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 8)), 0)

    def test_backfill_requests_polls_downloads_and_loads(self):
        w = self._window()
        eta_history.step('preprod', 'documents')
        w.refresh_from_db()
        self.assertEqual((w.state, w.package_id), ('requested', 'P1'))
        self.fake.statuses['P1'] = 2
        self.fake.packages['P1'] = _zip([_doc_row('A'), _doc_row('B'), _doc_row('C', issuer='111')])
        eta_history.step('preprod', 'documents')
        w.refresh_from_db()
        self.assertEqual((w.state, w.loaded_count), ('loaded', 3))
        a = EtaMirrorDocument.objects.get(system='preprod', uuid='A')
        self.assertEqual((a.direction, a.status, a.internal_id, str(a.total_amount)), ('sent', 'valid', 'INV-A', '114.00000'))
        self.assertEqual(EtaMirrorDocument.objects.get(uuid='C').direction, 'received')

    def test_receipts_load_from_nested_rows(self):
        w = self._window('receipts')
        eta_history.step('preprod', 'receipts')
        self.fake.statuses['P1'] = 2
        self.fake.packages['P1'] = _zip({'receipts': [_receipt_row('R1')]})
        eta_history.step('preprod', 'receipts')
        r = EtaMirrorReceipt.objects.get(uuid='R1')
        self.assertEqual((r.receipt_number, r.pos_serial, r.branch_number, r.previous_uuid, r.status),
                         ('R-R1', 'POS1', '3', 'P', 'valid'))
        w.refresh_from_db()
        self.assertEqual(w.state, 'loaded')

    def test_too_big_window_is_split_in_halves(self):
        self._window('receipts', days=4)
        self.fake.too_big_over_days = 2
        eta_history.step('preprod', 'receipts', max_requests=1)
        spans = sorted((w.date_from.day, w.date_to.day, w.state) for w in EtaHistoryWindow.objects.all())
        self.assertEqual(spans, [(1, 2, 'planned'), (1, 4, 'split'), (3, 4, 'planned')])

    def test_one_day_window_still_too_big_is_marked_too_big(self):
        self._window('receipts', days=1)
        self.fake.too_big_over_days = 0
        eta_history.step('preprod', 'receipts')
        w = EtaHistoryWindow.objects.get()
        self.assertEqual(w.state, 'too_big')
        self.assertTrue(w.error)

    def test_unreachable_eta_leaves_window_unloaded_with_reason(self):
        w = self._window()
        self.fake.fail_with = eta_client.EtaUncertain('connection lost')
        out = eta_history.step('preprod', 'documents')
        w.refresh_from_db()
        self.assertEqual(w.state, 'planned')
        self.assertIn('connection lost', eta_history.progress('preprod')['documents']['last_error'])
        self.assertTrue(out['error'])
        self.assertEqual(EtaMirrorDocument.objects.count(), 0)

    def test_expired_package_is_requested_again(self):
        w = self._window()
        eta_history.step('preprod', 'documents')
        self.fake.statuses['P1'] = 4
        eta_history.step('preprod', 'documents')
        w.refresh_from_db()
        self.assertEqual((w.state, w.package_id), ('requested', 'P2'))

    def test_reload_is_idempotent_and_newest_status_wins(self):
        eta_history.upsert_documents('preprod', [_doc_row('A')], 'package')
        eta_history.upsert_documents('preprod', [_doc_row('A', status='Cancelled')], 'search')
        a = EtaMirrorDocument.objects.get()
        self.assertEqual((a.status, a.source), ('cancelled', 'search'))

    def test_request_body_never_truncates(self):
        self._window()
        eta_history.step('preprod', 'documents')
        kind, body = self.fake.requests[0]
        self.assertIs(body['queryParameters']['truncateIfExceeded'], False)
        self.assertEqual(body['format'], 'JSON')

    def test_progress_counts_states_and_says_why_off(self):
        self._window()
        with mock.patch.object(eta_history, 'EtaReader') as R:
            R.return_value.why_not.return_value = 'off'
            p = eta_history.progress('preprod')
        self.assertEqual(p['documents']['states']['planned'], 1)
        self.assertEqual(p['why_not'], 'off')


# ── Task 4: top-up, jobs, freshness ────────────────────────────────────────────────────────────

class TopUpTests(TestCase):

    def setUp(self):
        from apps.tax_invoicing.models import TaxIssuerProfile
        issuer = TaxIssuerProfile.load()
        issuer.tax_id = '499336534'
        issuer.save()

    def _reader(self, doc_pages, receipt_pages):
        reader = mock.Mock()
        reader.why_not.return_value = ''
        calls = []

        def get(path, params=None):
            calls.append((path, dict(params or {})))
            if path == '/api/v1.0/documents/search':
                return _response(200, doc_pages.pop(0))
            if path == '/api/v1/receipts/search':
                if not receipt_pages:
                    return _response(404, {'target': 'NoResult', 'code': 'NotFound'})
                return _response(200, receipt_pages.pop(0))
            raise AssertionError(path)
        reader.get.side_effect = get
        return reader, calls

    def test_topup_pages_with_continuation_token_until_EndofResultSet(self):
        docs = [{'result': [_doc_row('A')], 'metadata': {'continuationToken': 'NEXT'}},
                {'result': [_doc_row('B')], 'metadata': {'continuationToken': 'EndofResultSet'}}]
        receipts_ = [{'receipts': [{'uuid': 'R9', 'receiptNumber': 'R-9', 'status': 'Valid',
                                    'dateTimeIssued': '2026-11-13T10:00:00Z'}], 'metadata': {'totalPages': 1}}]
        reader, calls = self._reader(docs, receipts_)
        with mock.patch.object(eta_history, 'EtaReader', return_value=reader):
            out = eta_history.top_up('preprod', days=3)
        self.assertEqual((out['documents'], out['receipts']), (2, 1))
        doc_calls = [p for path, p in calls if path == '/api/v1.0/documents/search']
        self.assertEqual(doc_calls[1]['continuationToken'], 'NEXT')
        self.assertIn('submissionDateFrom', doc_calls[0])
        self.assertEqual(EtaMirrorDocument.objects.get(uuid='B').source, 'search')
        self.assertEqual(EtaMirrorReceipt.objects.get(uuid='R9').receipt_number, 'R-9')

    def test_topup_with_no_receipts_is_zero_not_an_error(self):
        reader, _ = self._reader([{'result': [], 'metadata': {'continuationToken': 'EndofResultSet'}}], [])
        with mock.patch.object(eta_history, 'EtaReader', return_value=reader):
            out = eta_history.top_up('preprod', days=1)
        self.assertEqual((out['documents'], out['receipts'], out['error']), (0, 0, ''))

    def test_jobs_skip_disabled_systems(self):
        from apps.sync import tasks
        with mock.patch.object(eta_history, 'step') as step, mock.patch.object(eta_history, 'top_up') as top, \
                override_settings(TAX_ETA_READ_PREPROD_ENABLED=True, TAX_ETA_READ_PRODUCTION_ENABLED=False):
            tasks._run_eta_history_backfill()
            tasks._run_eta_history_topup()
        self.assertEqual({c[0][0] for c in step.call_args_list}, {'preprod'})
        self.assertEqual({c[0][0] for c in top.call_args_list}, {'preprod'})

    def test_freshness_reports_the_newest_load_per_system(self):
        from apps.sync import freshness
        self.assertIn('eta_history_preprod', freshness.DOMAINS)
        self.assertIsNone(freshness._SOURCES['eta_history_preprod']()['last_success_at'])
        eta_history.upsert_documents('preprod', [_doc_row('A')], 'search')
        self.assertIsNotNone(freshness._SOURCES['eta_history_preprod']()['last_success_at'])
        self.assertIsNone(freshness._SOURCES['eta_history_production']()['last_success_at'])


# ── Task 5: progress and refresh views ─────────────────────────────────────────────────────────

from apps.tests.test_tax_invoicing import Fixture, api  # noqa: E402


class HistoryViewTests(Fixture, TestCase):

    def setUp(self):
        self.build('eh')
        EtaHistoryWindow.objects.create(system='preprod', kind='receipts', date_from=dt.date(2024, 1, 1),
                                        date_to=dt.date(2024, 1, 4), state='loaded', loaded_count=12)

    def test_progress_view_needs_view_and_lists_both_systems(self):
        self.assertEqual(api(self.pharmacist).get('/api/tax-invoicing/history/progress/').status_code, 403)
        body = api(self.accountant).get('/api/tax-invoicing/history/progress/').json()
        self.assertEqual([s['system'] for s in body['systems']], ['preprod', 'production'])
        self.assertEqual(body['systems'][0]['receipts']['states']['loaded'], 1)
        self.assertTrue(body['systems'][1]['why_not'])

    @override_settings(TAX_ETA_READ_PREPROD_ENABLED=True, TAX_ETA_READ_PREPROD_CLIENT_ID='i', TAX_ETA_READ_PREPROD_CLIENT_SECRET='s')
    def test_refresh_needs_edit_and_refuses_a_disabled_system(self):
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/history/refresh/', {'system': 'preprod'},
                                                   format='json').status_code, 403)
        r = api(self.accountant).post('/api/tax-invoicing/history/refresh/', {'system': 'production'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(api(self.accountant).post('/api/tax-invoicing/history/refresh/', {'system': 'x'},
                                                   format='json').status_code, 400)
        with mock.patch('apps.tax_invoicing.views.start_thread') as thread:
            r = api(self.accountant).post('/api/tax-invoicing/history/refresh/', {'system': 'preprod'}, format='json')
        self.assertEqual(r.status_code, 202)
        thread.assert_called_once()


# ── Final review fixes ─────────────────────────────────────────────────────────────────────────

class ReviewFixTests(TestCase):

    def setUp(self):
        from apps.tax_invoicing.models import TaxIssuerProfile
        issuer = TaxIssuerProfile.load()
        issuer.tax_id = '499336534'
        issuer.save()
        self.fake = FakeReader('preprod')
        p = mock.patch.object(eta_history, 'EtaReader', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_planning_after_a_split_never_brings_the_parent_back(self):
        eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 4))
        self.fake.too_big_over_days = 2
        eta_history.step('preprod', 'receipts', max_requests=1)
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 4)), 0)
        eta_history.step('preprod', 'receipts', max_requests=5)
        planned_or_asked = sorted((w.date_from.day, w.date_to.day) for w in EtaHistoryWindow.objects.exclude(state='split'))
        self.assertEqual(planned_or_asked, [(1, 2), (3, 4)])
        self.assertEqual(len(self.fake.requests), 2)        # only the halves were asked for

    def test_only_whole_windows_are_planned_so_days_never_overlap(self):
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 6)), 1)
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 7)), 0)
        self.assertEqual(eta_history.plan_windows('preprod', 'receipts', dt.date(2024, 1, 1), dt.date(2024, 1, 8)), 1)
        spans = [(w.date_from.day, w.date_to.day) for w in EtaHistoryWindow.objects.order_by('date_from')]
        self.assertEqual(spans, [(1, 4), (5, 8)])

    def test_a_vanished_package_goes_back_to_planned_and_others_still_move(self):
        a = EtaHistoryWindow.objects.create(system='preprod', kind='documents', date_from=dt.date(2024, 1, 1),
                                            date_to=dt.date(2024, 1, 1), state='requested', package_id='GONE')
        b = EtaHistoryWindow.objects.create(system='preprod', kind='documents', date_from=dt.date(2024, 1, 2),
                                            date_to=dt.date(2024, 1, 2), state='requested', package_id='OK')
        self.fake.statuses['OK'] = 2
        self.fake.packages['OK'] = _zip([_doc_row('A')])
        self.fake.download_package = lambda kind, pid: (_ for _ in ()).throw(
            eta_client.EtaUncertain('gone', 404)) if pid == 'GONE' else self.fake.packages[pid]
        eta_history.step('preprod', 'documents', max_requests=0)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.state, a.package_id), ('planned', ''))
        self.assertEqual(b.state, 'loaded')

    def test_a_broken_zip_fails_that_window_with_its_reason(self):
        w = EtaHistoryWindow.objects.create(system='preprod', kind='documents', date_from=dt.date(2024, 1, 1),
                                            date_to=dt.date(2024, 1, 1), state='requested', package_id='P9')
        self.fake.statuses['P9'] = 2
        self.fake.packages['P9'] = b'not a zip'
        eta_history.step('preprod', 'documents', max_requests=0)
        w.refresh_from_db()
        self.assertIn(w.state, ('planned', 'failed'))
        self.assertTrue(w.error)

    def test_a_uuid_twice_in_one_package_loads_once(self):
        self.assertEqual(eta_history.upsert_documents('preprod', [_doc_row('A'), _doc_row('A', status='Cancelled')], 'package'), 1)
        self.assertEqual(EtaMirrorDocument.objects.get().status, 'cancelled')

    def test_an_older_package_never_overwrites_a_newer_status(self):
        w = EtaHistoryWindow.objects.create(system='preprod', kind='documents', date_from=dt.date(2024, 1, 1),
                                            date_to=dt.date(2024, 1, 1), state='requested', package_id='P1',
                                            requested_at=timezone.now() - dt.timedelta(hours=2))
        eta_history.upsert_documents('preprod', [_doc_row('A', status='Cancelled')], 'search')   # after the request
        self.fake.statuses['P1'] = 2
        self.fake.packages['P1'] = _zip([_doc_row('A', status='Valid'), _doc_row('B')])
        eta_history.step('preprod', 'documents', max_requests=0)
        self.assertEqual(EtaMirrorDocument.objects.get(uuid='A').status, 'cancelled')
        self.assertTrue(EtaMirrorDocument.objects.filter(uuid='B').exists())
        w.refresh_from_db()
        self.assertEqual(w.state, 'loaded')

    def test_topup_covers_etas_cancel_and_reject_period(self):
        self.assertGreaterEqual(eta_history.TOPUP_DAYS['receipts'], 7)
        self.assertGreaterEqual(eta_history.TOPUP_DAYS['documents'], 7)

    def test_a_refused_login_stops_the_round_without_failing_windows(self):
        eta_history.plan_windows('preprod', 'documents', dt.date(2024, 1, 1), dt.date(2024, 3, 30))
        self.fake.fail_with = eta_client.EtaRefused('forbidden', 403)
        for _ in range(6):
            out = eta_history.step('preprod', 'documents')
        self.assertTrue(out['error'])
        self.assertFalse(EtaHistoryWindow.objects.filter(state='failed').exists())
        self.assertEqual(set(EtaHistoryWindow.objects.values_list('attempts', flat=True)), {0})

    def test_a_busy_system_is_skipped(self):
        eta_history.plan_windows('preprod', 'documents', dt.date(2024, 1, 1), dt.date(2024, 1, 30))
        with mock.patch.object(eta_history, '_try_lock', return_value=False):
            out = eta_history.step('preprod', 'documents')
        self.assertTrue(out['busy'])
        self.assertEqual(self.fake.requests, [])

    def test_the_last_error_belongs_to_the_last_round_and_clears(self):
        eta_history.plan_windows('preprod', 'documents', dt.date(2024, 1, 1), dt.date(2024, 1, 30))
        self.fake.fail_with = eta_client.EtaUncertain('down')
        eta_history.step('preprod', 'documents')
        self.assertIn('down', eta_history.progress('preprod')['documents']['last_error'])
        self.fake.fail_with = None
        eta_history.step('preprod', 'documents')
        self.assertEqual(eta_history.progress('preprod')['documents']['last_error'], '')
        self.assertEqual(EtaHistoryWindow.objects.exclude(error='').count(), 0)

    def test_failed_windows_can_be_retried(self):
        EtaHistoryWindow.objects.create(system='preprod', kind='documents', date_from=dt.date(2024, 1, 1),
                                        date_to=dt.date(2024, 1, 1), state='failed', attempts=5, error='x')
        self.assertEqual(eta_history.retry_failed('preprod'), 1)
        w = EtaHistoryWindow.objects.get()
        self.assertEqual((w.state, w.attempts), ('planned', 0))
