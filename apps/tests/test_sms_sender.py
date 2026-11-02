"""
core/sms.py — provider-neutral SMS sender (Batch 6, W-1 fallback; owner 2026-11-02).

No SMS company is chosen yet: SMS_PROVIDER='' leaves it off. 'http' drives any gateway that takes
an HTTP request with the number and text — the request shape (URL, method, JSON/form/query body,
headers) lives in settings, so the chosen company is switched on from .env with no code change.
The message often carries a code: it is never logged.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from core.sms import SmsError, SmsSender, sms_number

HTTP = dict(
    SMS_PROVIDER='http', SMS_HTTP_URL='https://sms.example/api/send', SMS_HTTP_METHOD='POST',
    SMS_HTTP_FORMAT='json', SMS_SENDER='ElRezeiky',
    SMS_HTTP_PARAMS='{"user": "u", "to": "{to}", "text": "{message}", "from": "{sender}"}',
    SMS_HTTP_HEADERS='{"Authorization": "Bearer t"}', SMS_HTTP_SUCCESS_TEXT='',
)


def _reply(status=200, text='{"ok": true}'):
    return mock.Mock(status_code=status, text=text)


class SmsNumberTests(SimpleTestCase):

    def test_egyptian_numbers_get_the_country_code(self):
        for raw in ('01012345678', '+20 101 234 5678', '201012345678', '00201012345678'):
            self.assertEqual(sms_number(raw), '201012345678', raw)


class SmsSenderTests(SimpleTestCase):

    @override_settings(SMS_PROVIDER='')
    def test_off_until_a_provider_is_set(self):
        sender = SmsSender()
        self.assertFalse(sender.is_configured)
        with self.assertRaises(SmsError):
            sender.send('01012345678', 'x')

    @override_settings(**HTTP)
    def test_http_gateway_fills_the_request_from_settings(self):
        with mock.patch('core.sms.requests.request', return_value=_reply()) as req:
            SmsSender().send('01012345678', 'رمزك 123456')
        args, kw = req.call_args
        self.assertEqual(args, ('POST', 'https://sms.example/api/send'))
        self.assertEqual(kw['json'], {'user': 'u', 'to': '201012345678', 'text': 'رمزك 123456',
                                      'from': 'ElRezeiky'})
        self.assertEqual(kw['headers'], {'Authorization': 'Bearer t'})
        self.assertFalse(kw['allow_redirects'])
        self.assertTrue(kw['timeout'])

    @override_settings(**{**HTTP, 'SMS_HTTP_FORMAT': 'form'})
    def test_form_body(self):
        with mock.patch('core.sms.requests.request', return_value=_reply()) as req:
            SmsSender().send('01012345678', 'hi')
        self.assertEqual(req.call_args.kwargs['data']['to'], '201012345678')
        self.assertNotIn('json', req.call_args.kwargs)

    @override_settings(**{**HTTP, 'SMS_HTTP_METHOD': 'GET', 'SMS_HTTP_FORMAT': 'query'})
    def test_query_string(self):
        with mock.patch('core.sms.requests.request', return_value=_reply()) as req:
            SmsSender().send('01012345678', 'hi')
        self.assertEqual(req.call_args.args[0], 'GET')
        self.assertEqual(req.call_args.kwargs['params']['text'], 'hi')

    @override_settings(**HTTP)
    def test_a_gateway_error_is_a_failed_send(self):
        with mock.patch('core.sms.requests.request', return_value=_reply(500, 'boom')):
            with self.assertRaises(SmsError):
                SmsSender().send('01012345678', 'hi')

    @override_settings(**{**HTTP, 'SMS_HTTP_SUCCESS_TEXT': '"code":"1901"'})
    def test_a_200_without_the_success_marker_is_a_failed_send(self):
        # Many gateways answer 200 with an error code in the body.
        with mock.patch('core.sms.requests.request', return_value=_reply(200, '{"code":"1903"}')):
            with self.assertRaises(SmsError):
                SmsSender().send('01012345678', 'hi')
        with mock.patch('core.sms.requests.request', return_value=_reply(200, '{"code":"1901"}')):
            SmsSender().send('01012345678', 'hi')

    @override_settings(**HTTP)
    def test_the_message_is_never_logged(self):
        with self.assertLogs('elrezeiky.sms', level='DEBUG') as logs:
            with mock.patch('core.sms.requests.request', return_value=_reply(500, 'boom')):
                with self.assertRaises(SmsError) as err:
                    SmsSender().send('01012345678', 'رمزك 987654')
        self.assertNotIn('987654', ' '.join(logs.output))
        self.assertNotIn('987654', str(err.exception))

    @override_settings(**{**HTTP, 'SMS_HTTP_METHOD': 'GET', 'SMS_HTTP_FORMAT': 'query'})
    def test_a_network_error_does_not_leak_the_url_with_the_code(self):
        import requests
        boom = requests.ConnectionError('GET https://sms.example/api/send?text=987654 failed')
        with self.assertLogs('elrezeiky.sms', level='DEBUG') as logs:
            with mock.patch('core.sms.requests.request', side_effect=boom):
                with self.assertRaises(SmsError) as err:
                    SmsSender().send('01012345678', '987654')
        self.assertNotIn('987654', ' '.join(logs.output) + str(err.exception))

    @override_settings(**{**HTTP, 'SMS_HTTP_URL': ''})
    def test_http_without_a_url_is_not_configured(self):
        self.assertFalse(SmsSender().is_configured)
