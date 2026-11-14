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


# ── Backfill from ETA's search lists (phase 1b) ────────────────────────────────────────────────

import datetime as dt  # noqa: E402

from apps.tax_invoicing import eta_history  # noqa: E402
from apps.tax_invoicing.models import EtaHistoryState  # noqa: E402

DOCS = '/api/v1.0/documents/search'
RECEIPTS = '/api/v1/receipts/search'


def _doc_row(uuid, status='Valid', issuer='499336534', total=114):
    """Shaped like ETA's production documents search row (2026-11-14)."""
    return {'uuid': uuid, 'submissionUUID': 'S-' + uuid, 'internalId': 'INV-' + uuid, 'typeName': 'I',
            'typeVersionName': '1.0', 'issuerId': issuer, 'issuerName': 'الرزيقى', 'receiverId': '999888777',
            'receiverName': 'شركة', 'receiverType': 'B', 'dateTimeIssued': '2024-01-02T10:00:00Z',
            'dateTimeReceived': '2024-01-02T10:01:00Z', 'status': status, 'netAmount': 100, 'totalSales': 100, 'total': total}


def _receipt_row(uuid, status='Valid'):
    """Shaped like ETA's production receipts search row (2026-11-14): flat."""
    return {'uuid': uuid, 'submissionUuid': 'SU-' + uuid, 'receiptNumber': 'R-' + uuid, 'posSerialNumber': 'POS1',
            'dateTimeIssued': '2025-01-02T10:00:00Z', 'dateTimeReceived': '2025-01-03T02:00:00Z', 'totalAmount': 57,
            'status': status, 'typeName': 'S', 'issuerId': '499336534', 'submitterName': 'Invoicer', 'direction': 'Submitted'}


class FakeSearch:
    """Stands in for EtaReader.get: answers ETA's search lists from scripted pages, records every call."""
    def __init__(self):
        self.calls = []
        self.doc_pages = []          # list of (rows, token)
        self.receipts = {}           # 'YYYY-MM-DD' (issued day) -> list of rows, or an int total (too many)
        self.fail_with = None

    def why_not(self):
        return ''

    def get(self, path, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        if self.fail_with:
            raise self.fail_with
        if path == DOCS:
            if not self.doc_pages:
                return _response(404, {'target': 'NoResult', 'code': 'NotFound'})
            rows, token = self.doc_pages.pop(0)
            return _response(200, {'result': rows, 'metadata': {'continuationToken': token}})
        if path == RECEIPTS:
            day = params['DateTimeIssuedFrom'][:10]
            rows = self.receipts.get(day)
            if rows is None:
                return _response(404, {'target': 'NoResult', 'code': 'NotFound'})
            if isinstance(rows, int):
                return _response(200, {'receipts': [], 'metadata': {'totalCount': rows, 'totalPages': 30}})
            size, page = int(params['PageSize']), int(params['PageNo'])
            pages = max(1, -(-len(rows) // size))
            return _response(200, {'receipts': rows[(page - 1) * size:page * size],
                                   'metadata': {'totalCount': len(rows), 'totalPages': pages}})
        raise AssertionError(path)


class SearchBackfillTests(TestCase):

    def setUp(self):
        from apps.tax_invoicing.models import TaxIssuerProfile
        issuer = TaxIssuerProfile.load()
        issuer.tax_id = '499336534'
        issuer.save()
        self.fake = FakeSearch()
        p = mock.patch.object(eta_history, 'EtaReader', return_value=self.fake)
        p.start()
        self.addCleanup(p.stop)

    def _window(self, kind, first, last=None):
        return EtaHistoryWindow.objects.create(system='production', kind=kind, date_from=first, date_to=last or first)

    def test_receipts_go_by_day_and_documents_by_30_days_whole_windows_only(self):
        self.assertEqual(eta_history.plan_windows('production', 'receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 3)), 3)
        self.assertEqual(eta_history.plan_windows('production', 'receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 3)), 0)
        self.assertEqual(eta_history.plan_windows('production', 'documents', dt.date(2024, 1, 1), dt.date(2024, 3, 1)), 2)

    def test_receipt_history_starts_in_2025(self):
        self.assertEqual(eta_history.start_date('receipts'), dt.date(2025, 1, 1))
        self.assertEqual(eta_history.start_date('documents'), dt.date(2022, 6, 1))

    def test_a_document_window_follows_continuation_tokens_and_maps_etas_fields(self):
        w = self._window('documents', dt.date(2024, 1, 1), dt.date(2024, 1, 30))
        self.fake.doc_pages = [([_doc_row('A'), _doc_row('B', issuer='111')], 'NEXT'), ([_doc_row('C')], 'EndofResultSet')]
        out = eta_history.step('production', 'documents')
        w.refresh_from_db()
        self.assertEqual((w.state, w.loaded_count, w.eta_count, out['loaded']), ('loaded', 3, 3, 1))
        first, second = [p for path, p in self.fake.calls]
        self.assertEqual((first['submissionDateFrom'], first['submissionDateTo']), ('2024-01-01T00:00:00Z', '2024-01-31T00:00:00Z'))
        self.assertEqual(second['continuationToken'], 'NEXT')
        a = EtaMirrorDocument.objects.get(uuid='A')
        self.assertEqual((a.direction, a.doc_type, a.status, str(a.total_amount), str(a.net_amount), a.internal_id),
                         ('sent', 'i', 'valid', '114.00000', '100.00000', 'INV-A'))
        self.assertEqual(EtaMirrorDocument.objects.get(uuid='B').direction, 'received')

    def test_a_receipt_day_pages_by_issued_date_and_keeps_etas_count(self):
        w = self._window('receipts', dt.date(2025, 1, 3))
        self.fake.receipts['2025-01-03'] = [_receipt_row(f'R{i}') for i in range(150)]
        eta_history.step('production', 'receipts')
        w.refresh_from_db()
        self.assertEqual((w.state, w.loaded_count, w.eta_count), ('loaded', 150, 150))
        params = [p for path, p in self.fake.calls]
        self.assertEqual([p['PageNo'] for p in params], [1, 2])
        self.assertEqual((params[0]['DateTimeIssuedFrom'], params[0]['DateTimeIssuedTo']),
                         ('2025-01-03T00:00:00Z', '2025-01-04T00:00:00Z'))
        r = EtaMirrorReceipt.objects.get(uuid='R7')
        self.assertEqual((r.receipt_number, r.pos_serial, r.receipt_type, r.status, str(r.total_amount), r.submission_uuid),
                         ('R-R7', 'POS1', 's', 'valid', '57.00000', 'SU-R7'))

    def test_a_day_over_etas_3000_cap_is_marked_too_big_never_cut(self):
        w = self._window('receipts', dt.date(2025, 1, 3))
        self.fake.receipts['2025-01-03'] = 3001
        eta_history.step('production', 'receipts')
        w.refresh_from_db()
        self.assertEqual((w.state, w.eta_count, w.loaded_count), ('too_big', 3001, 0))
        self.assertEqual(EtaMirrorReceipt.objects.count(), 0)

    def test_a_multi_day_window_over_the_cap_is_split_in_halves(self):
        w = self._window('receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 4))
        self.fake.receipts['2025-01-01'] = 5000            # the 4-day query starts on the 1st
        eta_history.step('production', 'receipts', max_windows=1)
        w.refresh_from_db()
        self.assertEqual(w.state, 'split')
        halves = sorted((x.date_from.day, x.date_to.day) for x in EtaHistoryWindow.objects.filter(state='planned'))
        self.assertEqual(halves, [(1, 2), (3, 4)])

    def test_no_result_is_a_loaded_window_with_zero(self):
        w = self._window('receipts', dt.date(2025, 1, 5))
        out = eta_history.step('production', 'receipts')
        w.refresh_from_db()
        self.assertEqual((w.state, w.loaded_count, w.eta_count, out['error']), ('loaded', 0, 0, ''))

    def test_unreachable_eta_keeps_the_window_and_records_the_reason_for_the_round(self):
        w = self._window('receipts', dt.date(2025, 1, 6))
        self.fake.fail_with = eta_client.EtaUncertain('connection lost')
        out = eta_history.step('production', 'receipts')
        w.refresh_from_db()
        self.assertEqual((w.state, w.attempts), ('planned', 0))
        self.assertIn('connection lost', out['error'])
        self.assertIn('connection lost', eta_history.progress('production')['receipts']['last_error'])
        self.fake.fail_with = None
        self.fake.receipts['2025-01-06'] = [_receipt_row('Z')]
        eta_history.step('production', 'receipts')
        self.assertEqual(eta_history.progress('production')['receipts']['last_error'], '')

    def test_a_refused_login_stops_the_round_and_fails_no_window(self):
        eta_history.plan_windows('production', 'receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 10))
        self.fake.fail_with = eta_client.EtaRefused('forbidden', 403)
        for _ in range(6):
            eta_history.step('production', 'receipts')
        self.assertFalse(EtaHistoryWindow.objects.exclude(state='planned').exists())
        self.assertEqual(len(self.fake.calls), 6)          # one attempt per round, then stop

    def test_other_refusals_count_attempts_until_failed(self):
        self._window('receipts', dt.date(2025, 1, 7))
        self.fake.fail_with = eta_client.EtaRefused('bad', 400)
        for _ in range(eta_history.MAX_ATTEMPTS):
            eta_history.step('production', 'receipts')
        w = EtaHistoryWindow.objects.get()
        self.assertEqual((w.state, w.attempts), ('failed', eta_history.MAX_ATTEMPTS))
        self.assertEqual(eta_history.retry_failed('production'), 1)

    def test_a_round_takes_at_most_max_windows_oldest_first(self):
        eta_history.plan_windows('production', 'receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 10))
        eta_history.step('production', 'receipts', max_windows=3)
        loaded = list(EtaHistoryWindow.objects.filter(state='loaded').order_by('date_from').values_list('date_from', flat=True))
        self.assertEqual(loaded, [dt.date(2025, 1, 1), dt.date(2025, 1, 2), dt.date(2025, 1, 3)])

    def test_a_busy_system_is_skipped(self):
        eta_history.plan_windows('production', 'receipts', dt.date(2025, 1, 1), dt.date(2025, 1, 2))
        with mock.patch.object(eta_history, '_try_lock', return_value=False):
            out = eta_history.step('production', 'receipts')
        self.assertTrue(out['busy'])
        self.assertEqual(self.fake.calls, [])

    def test_same_uuid_twice_loads_once_and_newest_wins(self):
        self.assertEqual(eta_history.upsert_documents('production', [_doc_row('A'), _doc_row('A', status='Cancelled')], 'search'), 1)
        self.assertEqual(EtaMirrorDocument.objects.get().status, 'cancelled')

    def test_topup_rereads_30_days_of_documents_and_14_days_of_receipts_by_day(self):
        self.assertEqual(eta_history.TOPUP_DAYS['receipts'], 14)     # Invoicer uploads late, in bursts
        today = timezone.now().date()
        self.fake.doc_pages = [([_doc_row('A')], 'EndofResultSet')]
        self.fake.receipts[(today - dt.timedelta(days=1)).isoformat()] = [_receipt_row('R1')]
        out = eta_history.top_up('production')
        self.assertEqual((out['documents'], out['receipts'], out['error']), (1, 1, ''))
        receipt_days = [p['DateTimeIssuedFrom'][:10] for path, p in self.fake.calls if path == RECEIPTS]
        self.assertEqual(len(receipt_days), eta_history.TOPUP_DAYS['receipts'] + 1)        # today included
        doc_from = [p['submissionDateFrom'] for path, p in self.fake.calls if path == DOCS][0]
        self.assertEqual(doc_from[:10], (today - dt.timedelta(days=eta_history.TOPUP_DAYS['documents'])).isoformat())

    def test_jobs_skip_disabled_systems(self):
        from apps.sync import tasks
        with mock.patch.object(eta_history, 'step') as step, mock.patch.object(eta_history, 'top_up') as top, \
                mock.patch.object(eta_history, 'EtaReader', eta_reader.EtaReader), \
                override_settings(TAX_ETA_READ_PREPROD_ENABLED=True, TAX_ETA_READ_PRODUCTION_ENABLED=False):
            tasks._run_eta_history_backfill()
            tasks._run_eta_history_topup()
        self.assertEqual({c[0][0] for c in step.call_args_list}, {'preprod'})
        self.assertEqual({c[0][0] for c in top.call_args_list}, {'preprod'})

    def test_freshness_reports_the_newest_load_per_system(self):
        from apps.sync import freshness
        self.assertIsNone(freshness._SOURCES['eta_history_production']()['last_success_at'])
        eta_history.upsert_documents('production', [_doc_row('A')], 'search')
        self.assertIsNotNone(freshness._SOURCES['eta_history_production']()['last_success_at'])
        self.assertIsNone(freshness._SOURCES['eta_history_preprod']()['last_success_at'])

    def test_the_round_record_is_kept_per_system_and_kind(self):
        self._window('receipts', dt.date(2025, 1, 9))
        self.fake.fail_with = eta_client.EtaUncertain('down')
        eta_history.step('production', 'receipts')
        state = EtaHistoryState.objects.get(system='production', kind='receipts')
        self.assertIn('down', state.last_error)
        self.assertIsNone(state.last_ok_at)


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
