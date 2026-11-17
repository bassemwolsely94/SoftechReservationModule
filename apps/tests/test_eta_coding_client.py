"""
ETA production item coding, S4 task 1: the per-system coding client (apps/tax_invoicing/eta_coding_client.py)
and the production send gates in coding.py (production_gate, client_for, send / refresh / check_codes per system).
ETA is mocked; no real HTTP.
"""
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.tax_invoicing import coding, eta_client, eta_coding_client, eta_reader
from apps.tax_invoicing.models import TaxAuditEvent, TaxCodeRequest, TaxItemProfile
from apps.tests.test_tax_invoicing import Fixture, api

PROD_API = 'https://api.invoicing.eta.gov.eg'
PROD_ID = 'https://id.eta.gov.eg'
PREPROD_API = 'https://api.preprod.invoicing.eta.gov.eg'
SECRET = 'prod-secret-do-not-leak'

# A server that sends invoices to preprod (the office until cutover), holding the production reading login.
PREPROD_SERVER = dict(
    WRITER_INSTANCE=True, TAX_ETA_ENVIRONMENT='preprod', TAX_ETA_API_BASE_URL='', TAX_ETA_ID_BASE_URL='',
    TAX_ETA_CLIENT_ID='cid', TAX_ETA_CLIENT_SECRET='sec', TAX_ETA_CODING_ENABLED=True,
    TAX_ETA_PRODUCTION_ALLOWED=False, TAX_ETA_CODING_PRODUCTION_ENABLED=True, TAX_ETA_CODING_PRODUCTION_BATCH_OK=False,
    TAX_ETA_PRODUCTION_CLIENT_ID='', TAX_ETA_PRODUCTION_CLIENT_SECRET='',
    TAX_ETA_READ_PRODUCTION_CLIENT_ID='prod-id', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET=SECRET)


def _response(status_code, body, headers=None):
    r = mock.Mock(status_code=status_code, headers=headers or {})
    r.json.return_value = body
    return r


TOKEN = _response(200, {'access_token': 'PT', 'expires_in': 3600})


def _reset():
    eta_client.reset_token()
    eta_coding_client.reset_tokens()


class _Clean:
    def setUp(self):
        super().setUp()
        _reset()
        self.addCleanup(_reset)
        pace = mock.patch.object(eta_coding_client, 'MIN_INTERVAL', 0)
        pace.start()
        self.addCleanup(pace.stop)


@override_settings(**PREPROD_SERVER)
class CodingClientTests(_Clean, SimpleTestCase):

    def test_production_login_and_call_go_to_production_whatever_the_server_sends_to(self):
        client = eta_coding_client.CodingClient('production')
        with mock.patch.object(eta_coding_client.requests, 'post',
                               side_effect=[TOKEN, _response(200, {'ok': 1})]) as post:
            self.assertEqual(client.create_egs_codes([{'itemCode': 'X'}]), (200, {'ok': 1}))
        login, call = post.call_args_list
        self.assertEqual(login[0][0], PROD_ID + '/connect/token')
        self.assertEqual(login[1]['data']['client_id'], 'prod-id')        # the reading login, as the owner chose
        self.assertIs(login[1]['verify'], True)                           # public roots, never the preprod CA
        self.assertEqual(call[0][0], PROD_API + '/api/v1.0/codetypes/requests/codes')
        self.assertEqual(call[1]['headers']['Authorization'], 'Bearer PT')

    @override_settings(TAX_ETA_PRODUCTION_CLIENT_ID='own-id', TAX_ETA_PRODUCTION_CLIENT_SECRET='own-sec')
    def test_own_production_login_comes_first(self):
        with mock.patch.object(eta_coding_client.requests, 'post', side_effect=[TOKEN, _response(200, {})]) as post:
            eta_coding_client.CodingClient('production').create_egs_codes([{}])
        self.assertEqual(post.call_args_list[0][1]['data']['client_id'], 'own-id')

    @override_settings(TAX_ETA_READ_PRODUCTION_CLIENT_ID='', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET='')
    def test_no_login_configured_reaches_nothing(self):
        client = eta_coding_client.CodingClient('production')
        self.assertFalse(client.configured())
        with mock.patch.object(eta_coding_client.requests, 'post') as post, \
                mock.patch.object(eta_coding_client.requests, 'get') as get:
            with self.assertRaises(eta_coding_client.EtaNotConfigured):
                client.create_egs_codes([{}])
            with self.assertRaises(eta_coding_client.EtaNotConfigured):
                client.my_code_requests('EG-1')
        post.assert_not_called()
        get.assert_not_called()

    @override_settings(TAX_ETA_CODING_PRODUCTION_ENABLED=False)
    def test_sending_needs_the_production_coding_switch_reading_does_not(self):
        client = eta_coding_client.CodingClient('production')
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN) as post, \
                mock.patch.object(eta_coding_client.requests, 'put') as put, \
                mock.patch.object(eta_coding_client.requests, 'get',
                                  return_value=_response(200, [{'itemCode': 'EG-1', 'status': 'Submitted'}])):
            for call in (lambda: client.create_egs_codes([{}]), lambda: client.request_code_reuse([{}])):
                with self.assertRaises(eta_coding_client.EtaNotConfigured):
                    call()
            put.assert_not_called()
            self.assertEqual(len(client.my_code_requests('EG-1')), 1)
        self.assertEqual([c[0][0] for c in post.call_args_list], [PROD_ID + '/connect/token'])   # the read's login only

    @override_settings(WRITER_INSTANCE=False)
    def test_switch_counts_only_on_the_writer_instance(self):
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaises(eta_coding_client.EtaNotConfigured):
                eta_coding_client.CodingClient('production').create_egs_codes([{}])
        post.assert_not_called()

    def test_answers_mirror_eta_client(self):
        client = eta_coding_client.CodingClient('production')
        cases = [(requests.Timeout(), eta_coding_client.EtaUncertain), (_response(500, {}), eta_coding_client.EtaUncertain),
                 (_response(429, {}), eta_coding_client.EtaUncertain), (_response(400, {'e': 1}), eta_coding_client.EtaRefused)]
        for answer, exc in cases:
            with self.subTest(answer=answer):
                _reset()
                with mock.patch.object(eta_coding_client.requests, 'post', side_effect=[TOKEN, answer]):
                    with self.assertRaises(exc):
                        client.create_egs_codes([{}])
        with mock.patch.object(eta_coding_client.requests, 'put', return_value=_response(200, {'rejectedItems': [1]})):
            with self.assertRaises(eta_coding_client.EtaRefused):
                client.request_code_reuse([{}])
        with mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(404, {})) as get:
            self.assertIsNone(client.code_details('EGS', 'EG-1/2'))
        self.assertEqual(get.call_args[0][0], PROD_API + '/api/v1.0/codetypes/EGS/codes/EG-1%2F2')
        with mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(503, {})):
            with self.assertRaises(eta_coding_client.EtaUncertain):
                client.my_code_requests('EG-1')

    def test_exceptions_are_eta_clients_so_coding_handles_them_alike(self):
        self.assertIs(eta_coding_client.EtaUncertain, eta_client.EtaUncertain)
        self.assertIs(eta_coding_client.EtaRefused, eta_client.EtaRefused)
        self.assertIs(eta_coding_client.EtaNotConfigured, eta_client.EtaNotConfigured)

    def test_refused_login_never_shows_the_secret(self):
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=_response(401, {'error': SECRET})):
            with self.assertRaises(eta_coding_client.EtaRefused) as ctx:
                eta_coding_client.CodingClient('production').create_egs_codes([{}])
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertNotIn('prod-id', str(ctx.exception))
        with mock.patch.object(eta_coding_client.requests, 'post', side_effect=requests.ConnectionError(SECRET)):
            with self.assertRaises(eta_coding_client.EtaRefused) as ctx:
                eta_coding_client.CodingClient('production').create_egs_codes([{}])
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_own_token_cache_shared_with_neither_eta_client_nor_the_reader(self):
        eta_reader.reset_tokens()
        client = eta_coding_client.CodingClient('production')
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN) as post, \
                mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(200, [])):
            client.my_code_requests('EG-1')
            client.my_code_requests('EG-2')
        self.assertEqual(post.call_count, 1)                       # logged in once, then cached
        self.assertEqual(eta_client._token['value'], '')
        self.assertNotIn('production', eta_reader._tokens)

    def test_paced_at_two_calls_a_second(self):
        with mock.patch.object(eta_coding_client, 'MIN_INTERVAL', 0.5), \
                mock.patch.object(eta_coding_client.time, 'sleep') as sleep, \
                mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(200, [])):
            client = eta_coding_client.CodingClient('production')
            client.my_code_requests('EG-1')
            client.my_code_requests('EG-2')
        self.assertTrue(sleep.called)
        self.assertLessEqual(sleep.call_args_list[0][0][0], 0.5)     # (sleep is mocked, so later waits add up)

    def test_token_is_kept_per_login(self):
        client = eta_coding_client.CodingClient('production')
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN) as post, \
                mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(200, [])):
            client.my_code_requests('EG-1')
            with override_settings(TAX_ETA_PRODUCTION_CLIENT_ID='own-id', TAX_ETA_PRODUCTION_CLIENT_SECRET='own-sec'):
                client.my_code_requests('EG-1')
            client.my_code_requests('EG-1')
        self.assertEqual([c[1]['data']['client_id'] for c in post.call_args_list], ['prod-id', 'own-id'])

    def test_login_without_a_token_is_refused_and_not_cached(self):
        client = eta_coding_client.CodingClient('production')
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=_response(200, {'expires_in': 3600})), \
                mock.patch.object(eta_coding_client.requests, 'get') as get:
            with self.assertRaises(eta_coding_client.EtaRefused):
                client.my_code_requests('EG-1')
            get.assert_not_called()
        self.assertEqual(eta_coding_client._tokens, {})

    def test_login_is_paced_too(self):
        with mock.patch.object(eta_coding_client, 'MIN_INTERVAL', 0.5), \
                mock.patch.object(eta_coding_client.time, 'sleep') as sleep, \
                mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_coding_client.requests, 'get', return_value=_response(200, [])):
            eta_coding_client.CodingClient('production').my_code_requests('EG-1')   # login, then the call
        self.assertEqual(sleep.call_count, 1)

    def test_unknown_system_refused(self):
        with self.assertRaises(ValueError):
            eta_coding_client.CodingClient('staging')


@override_settings(**PREPROD_SERVER)
class ProductionGateTests(_Clean, Fixture, TestCase):

    def setUp(self):
        super().setUp()
        self.build('pg')
        self.p1 = TaxItemProfile.objects.create(softech_itemcode='70001', item_name='Panadol', item_name_ar='بانادول',
                                                gpc_code='10000454')
        self.p2 = TaxItemProfile.objects.create(softech_itemcode='70002', item_name='Brufen', gpc_code='10000454')

    def _prod(self, *profiles):
        coding.prepare([p.pk for p in profiles], self.accountant, system='production')
        return list(TaxCodeRequest.objects.filter(environment='production').order_by('id'))

    def _send(self, rows, confirm=None, can_finalize=True, answers=None):
        answers = answers or [_response(200, {})] * len(rows)
        with mock.patch.object(eta_coding_client.requests, 'post', side_effect=[TOKEN, *answers]) as post:
            out = coding.send([r.pk for r in rows], self.admin, str(len(rows)) if confirm is None else confirm,
                              actor_can_finalize=can_finalize)
        return out, post

    def _assert_nothing_left(self, rows, post):
        post.assert_not_called()
        for row in rows:
            row.refresh_from_db()
            self.assertEqual(row.status, TaxCodeRequest.PREPARED)

    def test_production_request_from_a_preprod_server_goes_to_production(self):
        rows = self._prod(self.p1)
        out, post = self._send(rows)
        self.assertEqual(out['submitted'], 1)
        urls = [c[0][0] for c in post.call_args_list]
        self.assertEqual(urls, [PROD_ID + '/connect/token', PROD_API + '/api/v1.0/codetypes/requests/codes'])
        self.assertFalse(any('preprod' in u for u in urls))
        rows[0].refresh_from_db()
        self.p1.refresh_from_db()
        self.assertEqual((rows[0].status, rows[0].environment), (TaxCodeRequest.SUBMITTED, 'production'))
        self.assertEqual((self.p1.coding_status, self.p1.coding_env), (TaxItemProfile.CODE_PENDING, 'production'))
        self.assertTrue(TaxAuditEvent.objects.filter(action='code_request_sent', entity_id=str(rows[0].pk)).exists())

    def test_preprod_request_still_goes_to_preprod_with_the_sending_login(self):
        coding.prepare([self.p1.pk], self.accountant)
        row = TaxCodeRequest.objects.get(environment='preprod')
        with mock.patch.object(eta_client.requests, 'post', side_effect=[TOKEN, _response(200, {})]) as post:
            self.assertEqual(coding.send([row.pk], self.admin, '1')['submitted'], 1)
        login, call = post.call_args_list
        self.assertEqual(login[0][0], 'https://id.preprod.eta.gov.eg/connect/token')
        self.assertEqual(login[1]['auth'], ('cid', 'sec'))
        self.assertEqual(call[0][0], PREPROD_API + '/api/v1.0/codetypes/requests/codes')
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.coding_status, TaxItemProfile.CODE_MISSING)    # preprod never touches the profile

    def test_each_gate_refuses_with_its_reason_and_sends_nothing(self):
        rows = self._prod(self.p1)
        for kwargs, words in (({'can_finalize': False}, 'finalize'), ({'confirm': '7'}, 'اكتب عدد الطلبات (1)')):
            with self.subTest(kwargs=kwargs):
                with mock.patch.object(eta_coding_client.requests, 'post') as post:
                    with self.assertRaisesMessage(coding.TaxRuleError, words):
                        coding.send([rows[0].pk], self.admin, kwargs.get('confirm', '1'),
                                    actor_can_finalize=kwargs.get('can_finalize', True))
                self._assert_nothing_left(rows, post)

    def test_finalize_is_never_assumed(self):
        rows = self._prod(self.p1)
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaises(coding.TaxRuleError):
                coding.send([rows[0].pk], self.admin, '1')      # no actor_can_finalize given
        self._assert_nothing_left(rows, post)

    @override_settings(TAX_ETA_CODING_PRODUCTION_ENABLED=False)
    def test_switch_off_message_and_no_http(self):
        rows = self._prod(self.p1)
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaisesMessage(coding.TaxRuleError, 'TAX_ETA_CODING_PRODUCTION_ENABLED'):
                coding.send([rows[0].pk], self.admin, '1', actor_can_finalize=True)
        self._assert_nothing_left(rows, post)

    @override_settings(TAX_ETA_PRODUCTION_ALLOWED=True, TAX_ETA_CODING_PRODUCTION_ENABLED=False)
    def test_invoice_production_switch_does_not_open_coding(self):
        rows = self._prod(self.p1)
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaises(coding.TaxRuleError):
                coding.send([rows[0].pk], self.admin, '1', actor_can_finalize=True)
        self._assert_nothing_left(rows, post)

    def test_first_request_rule(self):
        rows = self._prod(self.p1, self.p2)
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaisesMessage(coding.TaxRuleError, coding.FIRST_REQUEST_ONLY):
                coding.send([r.pk for r in rows], self.admin, '2', actor_can_finalize=True)
        self._assert_nothing_left(rows, post)
        self.assertTrue(coding.first_request_pending())
        out, _ = self._send(rows[:1])                                  # one at a time is allowed
        self.assertEqual(out['submitted'], 1)

    def test_one_production_request_in_flight_until_eta_approves_one(self):
        rows = self._prod(self.p1, self.p2)
        self.assertEqual(self._send(rows[:1])[0]['submitted'], 1)
        for state in (TaxCodeRequest.SUBMITTED, TaxCodeRequest.UNCERTAIN, TaxCodeRequest.SENDING):
            with self.subTest(state=state):
                TaxCodeRequest.objects.filter(pk=rows[0].pk).update(status=state)
                with mock.patch.object(eta_coding_client.requests, 'post') as post:
                    with self.assertRaisesMessage(coding.TaxRuleError, coding.FIRST_REQUEST_IN_FLIGHT):
                        coding.send([rows[1].pk], self.admin, '1', actor_can_finalize=True)
                self._assert_nothing_left(rows[1:], post)
        TaxCodeRequest.objects.filter(pk=rows[0].pk).update(status=TaxCodeRequest.APPROVED)
        self.assertEqual(self._send(rows[1:])[0]['submitted'], 1)

    @override_settings(TAX_ETA_CODING_PRODUCTION_BATCH_OK=True)
    def test_owner_flag_lifts_the_in_flight_rule(self):
        rows = self._prod(self.p1, self.p2)
        self._send(rows[:1])
        self.assertEqual(self._send(rows[1:])[0]['submitted'], 1)

    def test_in_flight_check_runs_after_the_lock_with_the_claim(self):
        """Another sender claims its first request while we wait on the lock: we must see it and stop."""
        rows = self._prod(self.p1)
        other = TaxItemProfile.objects.create(softech_itemcode='70003', item_name='Other', gpc_code='10000454')
        real_lock = coding._lock_production

        def lock_then_other_sender_wins():
            real_lock()
            TaxCodeRequest.objects.create(profile=other, item_code='EG-100200300-70003', parent_code='10000454',
                                          code_name='O', code_name_ar='O', active_from=timezone.localdate(),
                                          environment='production', status=TaxCodeRequest.SENDING)
        with mock.patch.object(coding, '_lock_production', side_effect=lock_then_other_sender_wins) as lock, \
                mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaisesMessage(coding.TaxRuleError, coding.FIRST_REQUEST_IN_FLIGHT):
                coding.send([rows[0].pk], self.admin, '1', actor_can_finalize=True)
        lock.assert_called_once()
        self._assert_nothing_left(rows, post)

    def test_the_production_lock_is_a_transaction_advisory_lock(self):
        from django.db import connection, transaction
        with transaction.atomic():
            coding._lock_production()
            with connection.cursor() as cur:
                cur.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()")
                self.assertGreaterEqual(cur.fetchone()[0], 1)

    @override_settings(TAX_ETA_CODING_PRODUCTION_BATCH_OK=True)
    def test_owner_flag_lifts_the_first_request_rule(self):
        rows = self._prod(self.p1, self.p2)
        out, _ = self._send(rows)
        self.assertEqual(out['submitted'], 2)

    def test_after_one_approved_production_request_batches_are_allowed(self):
        other = TaxItemProfile.objects.create(softech_itemcode='70009', item_name='Old', gpc_code='10000454')
        TaxCodeRequest.objects.create(profile=other, item_code='EG-100200300-70009', parent_code='10000454',
                                      code_name='Old', code_name_ar='Old', active_from=timezone.localdate(),
                                      environment='preprod', status=TaxCodeRequest.APPROVED)
        rows = self._prod(self.p1, self.p2)
        self.assertTrue(coding.first_request_pending())                # a preprod approval does not count
        TaxCodeRequest.objects.filter(pk=TaxCodeRequest.objects.get(profile=other).pk).update(environment='production')
        self.assertFalse(coding.first_request_pending())
        out, _ = self._send(rows)
        self.assertEqual(out['submitted'], 2)

    def test_mixed_systems_are_refused(self):
        rows = self._prod(self.p1)
        coding.prepare([self.p2.pk], self.accountant)
        pre = TaxCodeRequest.objects.get(environment='preprod')
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            with self.assertRaisesMessage(coding.TaxRuleError, 'وحدها'):
                coding.send([rows[0].pk, pre.pk], self.admin, '2', actor_can_finalize=True)
        self._assert_nothing_left(rows + [pre], post)

    @override_settings(TAX_ETA_CODING_PRODUCTION_BATCH_OK=True)
    def test_uncertain_send_stops_the_batch(self):
        rows = self._prod(self.p1, self.p2)
        out, post = self._send(rows, answers=[requests.Timeout()])
        self.assertEqual((out['uncertain'], out['submitted']), (1, 0))
        self.assertTrue(out['stopped'])
        rows[0].refresh_from_db()
        rows[1].refresh_from_db()
        self.assertEqual((rows[0].status, rows[1].status), (TaxCodeRequest.UNCERTAIN, TaxCodeRequest.PREPARED))
        self.assertEqual(post.call_count, 2)                           # login + the one uncertain call

    def test_refused_by_eta_marks_failed(self):
        rows = self._prod(self.p1)
        out, _ = self._send(rows, answers=[_response(400, {'error': 'exists'})])
        self.assertEqual(out['failed'], 1)
        rows[0].refresh_from_db()
        self.assertEqual(rows[0].status, TaxCodeRequest.FAILED)

    def test_send_view_passes_finalize(self):
        rows = self._prod(self.p1)
        with mock.patch.object(eta_coding_client.requests, 'post', side_effect=[TOKEN, _response(200, {})]):
            r = api(self.admin).post('/api/tax-invoicing/codes/send/', {'ids': [rows[0].pk], 'confirm': '1'},
                                     format='json')
        self.assertEqual((r.status_code, r.json()['submitted']), (200, 1))
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/codes/send/',
                                                   {'ids': [rows[0].pk], 'confirm': '1'}, format='json').status_code, 403)

    # ── refresh and check, per system ─────────────────────────────────────────────────────────
    def test_refresh_asks_production_rows_of_production_and_preprod_rows_of_preprod(self):
        prod = self._prod(self.p1)[0]
        coding.prepare([self.p2.pk], self.accountant)
        pre = TaxCodeRequest.objects.get(environment='preprod')
        TaxCodeRequest.objects.filter(pk__in=[prod.pk, pre.pk]).update(status=TaxCodeRequest.SUBMITTED)

        def answer(url, params=None, **kw):
            return _response(200, [{'itemCode': params['ItemCode'], 'status': 'Approved'}])
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN) as post, \
                mock.patch.object(eta_coding_client.requests, 'get', side_effect=answer) as get:
            out = coding.refresh(self.admin)
        self.assertEqual(out['checked'], 2)
        asked = {c[1]['params']['ItemCode']: c[0][0] for c in get.call_args_list}
        self.assertTrue(asked[prod.item_code].startswith(PROD_API + '/'))
        self.assertTrue(asked[pre.item_code].startswith(PREPROD_API + '/'))
        logins = sorted(c[0][0] for c in post.call_args_list)
        self.assertEqual(logins, sorted([PROD_ID + '/connect/token', 'https://id.preprod.eta.gov.eg/connect/token']))
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.coding_status, TaxItemProfile.CODE_APPROVED)
        self.assertEqual(self.p2.coding_status, TaxItemProfile.CODE_MISSING)    # preprod approval: request only

    @override_settings(TAX_ETA_READ_PRODUCTION_CLIENT_ID='', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET='')
    def test_production_could_not_ask_does_not_stop_preprod_rows(self):
        prod = self._prod(self.p1)[0]
        coding.prepare([self.p2.pk], self.accountant)
        pre = TaxCodeRequest.objects.get(environment='preprod')
        TaxCodeRequest.objects.filter(pk__in=[prod.pk, pre.pk]).update(status=TaxCodeRequest.SUBMITTED)
        with mock.patch.object(eta_client.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_client.requests, 'get',
                                  return_value=_response(200, [{'itemCode': pre.item_code, 'status': 'Approved'}])):
            out = coding.refresh(self.admin)
        self.assertEqual(out['checked'], 1)
        self.assertTrue(out['error'])
        prod.refresh_from_db()
        self.assertEqual(prod.status, TaxCodeRequest.SUBMITTED)

    @override_settings(TAX_ETA_ENVIRONMENT='production')
    def test_production_server_never_asks_about_preprod_rows(self):
        TaxCodeRequest.objects.create(profile=self.p2, item_code='EG-100200300-70002', parent_code='10000454',
                                      code_name='B', code_name_ar='B', active_from=timezone.localdate(),
                                      environment='preprod', status=TaxCodeRequest.SUBMITTED)
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_coding_client.requests, 'get') as get:
            out = coding.refresh(self.admin)
        get.assert_not_called()
        self.assertEqual(out['checked'], 0)

    @override_settings(TAX_ETA_ENVIRONMENT='production')
    def test_production_server_sends_production_through_the_coding_client_not_eta_client(self):
        # eta_client would need TAX_ETA_PRODUCTION_ALLOWED (off here); the coding client needs only its own gate.
        coding.prepare([self.p1.pk], self.accountant)
        row = TaxCodeRequest.objects.get()
        self.assertEqual(row.environment, 'production')
        out, post = self._send([row])
        self.assertEqual(out['submitted'], 1)
        self.assertEqual(post.call_args_list[0][1]['data']['client_id'], 'prod-id')

    @override_settings(TAX_ETA_ENVIRONMENT='production')
    def test_production_server_refuses_a_preprod_row(self):
        TaxCodeRequest.objects.create(profile=self.p2, item_code='EG-100200300-70002', parent_code='10000454',
                                      code_name='B', code_name_ar='B', active_from=timezone.localdate(),
                                      environment='preprod')
        row = TaxCodeRequest.objects.get()
        with mock.patch.object(eta_coding_client.requests, 'post') as post:
            out = coding.send([row.pk], self.admin, '1')
        post.assert_not_called()
        self.assertEqual((out['submitted'], len(out['refused'])), (0, 1))
        self.assertIn('preprod', out['refused'][0]['why'])

    def test_check_codes_on_production_from_a_preprod_server(self):
        self.p1.eta_code, self.p1.code_type = 'EG-100200300-70001', 'EGS'
        self.p1.coding_status = TaxItemProfile.CODE_APPROVED
        self.p1.save()
        with mock.patch.object(eta_coding_client.requests, 'post', return_value=TOKEN), \
                mock.patch.object(eta_coding_client.requests, 'get',
                                  return_value=_response(200, {'codeID': 1, 'active': True})) as get:
            out = coding.check_codes(self.admin, system='production')
        self.assertEqual((out['environment'], out['found']), ('production', 1))
        self.assertTrue(get.call_args[0][0].startswith(PROD_API + '/'))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.eta_check_env, 'production')

    def test_client_for(self):
        self.assertIsInstance(coding.client_for('production'), eta_coding_client.CodingClient)
        self.assertIs(coding.client_for('preprod'), eta_client)
        self.assertIs(coding.client_for(''), eta_client)
        with self.assertRaises(coding.TaxRuleError):
            coding.client_for('custom')
