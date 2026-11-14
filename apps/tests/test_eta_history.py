"""ETA history mirror (doc 36 §history, spec 2026-11-14-eta-history-mirror-design.md)."""
import inspect
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.tax_invoicing import eta_client, eta_reader


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
