"""
core/sms.py — provider-neutral SMS sender (Batch 6, W-1 fallback; owner 2026-11-02).

No SMS company is chosen yet, so SMS_PROVIDER='' keeps it off. SMS_PROVIDER='http' drives any
gateway that takes one HTTP request carrying the number and the text (SMS Misr, Cequens, Victory
Link, …): the request shape lives in settings, so the chosen company is switched on from .env:

    SMS_HTTP_URL           https://gateway/api/send
    SMS_HTTP_METHOD        POST | GET
    SMS_HTTP_FORMAT        json | form | query
    SMS_HTTP_PARAMS        JSON object; "{to}", "{message}", "{sender}" are filled in
    SMS_HTTP_HEADERS       JSON object (e.g. an Authorization header)
    SMS_SENDER             the approved sender name
    SMS_HTTP_SUCCESS_TEXT  text the reply must contain (gateways that answer 200 on errors)

The message often carries a one-time code: it is never logged or put in an error.
"""
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger('elrezeiky.sms')

TIMEOUT_SECS = 10


class SmsError(Exception):
    pass


def sms_number(phone) -> str:
    """International digits for an Egyptian number: 01012345678 / +20… / 0020… → 201012345678."""
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    if not digits.startswith('20'):
        digits = '20' + digits.lstrip('0')
    return digits


def _json_setting(name):
    raw = getattr(settings, name, '') or '{}'
    try:
        value = json.loads(raw)
    except ValueError:
        raise SmsError(f'{name} is not valid JSON')
    if not isinstance(value, dict):
        raise SmsError(f'{name} must be a JSON object')
    return value


class SmsSender:

    def __init__(self):
        self.provider = (getattr(settings, 'SMS_PROVIDER', '') or '').strip().lower()

    @property
    def is_configured(self) -> bool:
        return self.provider == 'http' and bool(getattr(settings, 'SMS_HTTP_URL', ''))

    def send(self, to: str, body: str) -> dict:
        if not self.is_configured:
            raise SmsError('SMS provider not configured')
        fill = {'{to}': sms_number(to), '{message}': body,
                '{sender}': getattr(settings, 'SMS_SENDER', '') or ''}
        params = {k: self._fill(v, fill) for k, v in _json_setting('SMS_HTTP_PARAMS').items()}
        method = (getattr(settings, 'SMS_HTTP_METHOD', '') or 'POST').upper()
        fmt = (getattr(settings, 'SMS_HTTP_FORMAT', '') or 'json').lower()
        body_kw = {'json': {'json': params}, 'form': {'data': params}}.get(fmt, {'params': params})
        try:
            reply = requests.request(method, settings.SMS_HTTP_URL,
                                     headers=_json_setting('SMS_HTTP_HEADERS'),
                                     timeout=TIMEOUT_SECS, allow_redirects=False, **body_kw)
        except requests.RequestException as err:
            # The error text can hold the URL — with the code in it for a query-string gateway.
            logger.warning('[SMS] gateway unreachable: %s', type(err).__name__)
            raise SmsError(f'SMS gateway unreachable ({type(err).__name__})') from None
        marker = getattr(settings, 'SMS_HTTP_SUCCESS_TEXT', '') or ''
        if not 200 <= reply.status_code < 300 or (marker and marker not in (reply.text or '')):
            logger.warning('[SMS] gateway refused to=%s**** status=%s', fill['{to}'][:-4], reply.status_code)
            raise SmsError(f'SMS gateway refused the message (HTTP {reply.status_code})')
        logger.info('[SMS] sent to=%s****', fill['{to}'][:-4])
        return {'ok': True, 'status': reply.status_code}

    @staticmethod
    def _fill(value, fill):
        if not isinstance(value, str):
            return value
        for key, sub in fill.items():
            value = value.replace(key, sub)
        return value
