"""
apps/tax_invoicing/eta_coding_client.py — item-code (EGS / GS1) calls to one named ETA system. Doc 36 §coding.

eta_client talks to the one system this server is configured for (TAX_ETA_ENVIRONMENT). Item codes are asked
for on ETA's production system whatever the server sends invoices to (the office sends invoices to preprod while
coding goes to production), so this client is bound to a system by name: its addresses come from
environment.ENVIRONMENTS[system], never from TAX_ETA_API_BASE_URL / TAX_ETA_ID_BASE_URL.

Same calls and the same answers as eta_client (EtaRefused = ETA did not take it; EtaUncertain = ETA may hold
it), with its own login, token cache and pace (ETA's 2 calls per second), shared with neither eta_client nor
EtaReader. No retries: a code request sent twice is not harmless.

Login: TAX_ETA_<SYSTEM>_CLIENT_ID / _CLIENT_SECRET, else the reading login TAX_ETA_READ_<SYSTEM>_CLIENT_ID /
_CLIENT_SECRET (the owner chose one ERP registration for both). Secrets never appear in an error.

Sending (create, reuse) on production also needs TAX_ETA_CODING_PRODUCTION_ENABLED through writer_allowed —
a second lock under coding.production_gate, which also checks `finalize`, the typed count and the
first-request rule. Reading needs no switch.
"""
import json
import threading
import time
from urllib.parse import quote

import requests
from django.conf import settings

from config.writers import writer_allowed

from . import environment
from .eta_client import TIMEOUT, EtaNotConfigured, EtaRefused, EtaUncertain, _json, _verify

SYSTEMS = ('preprod', 'production')
PRODUCTION_FLAG = 'TAX_ETA_CODING_PRODUCTION_ENABLED'
SEND_FLAGS = {'production': PRODUCTION_FLAG, 'preprod': 'TAX_ETA_CODING_ENABLED'}
# ETA's published pace per ERP system (apigovernance): 2 calls per second.
MIN_INTERVAL = 0.5

_lock = threading.Lock()
_tokens = {}
_last_call = {}

__all__ = ['CodingClient', 'EtaNotConfigured', 'EtaRefused', 'EtaUncertain', 'reset_tokens']


def reset_tokens():
    with _lock:
        _tokens.clear()
        _last_call.clear()


def _setting(name):
    return str(getattr(settings, name, '') or '').strip()


class CodingClient:
    def __init__(self, system):
        if system not in SYSTEMS:
            raise ValueError(f'unknown ETA system: {system}')
        self.system = system
        self.hosts = environment.ENVIRONMENTS[system]

    # ── login ───────────────────────────────────────────────────────────────────────────────────
    def _credentials(self):
        own = f'TAX_ETA_{self.system.upper()}_'
        read = f'TAX_ETA_READ_{self.system.upper()}_'
        client_id, secret = _setting(own + 'CLIENT_ID'), _setting(own + 'CLIENT_SECRET')
        if not (client_id and secret):
            client_id, secret = _setting(read + 'CLIENT_ID'), _setting(read + 'CLIENT_SECRET')
        return client_id, secret

    def configured(self):
        return all(self._credentials())

    def _verify(self):
        # TAX_ETA_CA_BUNDLE holds ETA's pre-production root only; production uses the normal public roots.
        return True if self.system == 'production' else _verify()

    def _token(self):
        client_id, secret = self._credentials()
        if not (client_id and secret):
            raise EtaNotConfigured(f'بيانات دخول منظومة المصلحة «{self.system}» لطلب الأكواد غير موجودة '
                                   f'(TAX_ETA_{self.system.upper()}_CLIENT_ID)')
        key = (self.system, client_id)          # a changed login never reuses the old login's token
        with _lock:
            cached = _tokens.get(key)
            if cached and cached['expires'] > time.time() + 60:
                return cached['value']
        self._pace()                            # a login counts against ETA's pace too
        try:
            r = requests.post(self.hosts['id'] + '/connect/token',
                              data={'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': secret},
                              timeout=TIMEOUT, allow_redirects=False, verify=self._verify())
        except requests.RequestException as exc:
            # No code request was involved in a login, so nothing can have been sent.
            raise EtaRefused(f'تعذر الاتصال بخدمة الدخول ({self.system}): {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise EtaRefused(f'رفضت منظومة {self.system} الدخول (HTTP {r.status_code})', r.status_code)
        body = _json(r)
        value = str(body.get('access_token') or '') if isinstance(body, dict) else ''
        if not value:
            raise EtaRefused(f'لم ترسل منظومة {self.system} رمز الدخول', r.status_code)
        try:
            expires_in = int(body.get('expires_in', 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        with _lock:
            _tokens[key] = {'value': value, 'expires': time.time() + expires_in}
        return value

    def _headers(self):
        return {'Authorization': f'Bearer {self._token()}', 'Content-Type': 'application/json',
                'Accept': 'application/json'}

    def _api(self, path):
        return self.hosts['api'] + path

    def _pace(self):
        with _lock:
            wait = _last_call.get(self.system, 0) + MIN_INTERVAL - time.time()
            _last_call[self.system] = time.time() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _may_send(self):
        flag = SEND_FLAGS[self.system]
        if not writer_allowed(flag):
            raise EtaNotConfigured(f'طلب الأكواد من منظومة المصلحة «{self.system}» مغلق ({flag})')

    # ── calls (as eta_client's) ─────────────────────────────────────────────────────────────────
    def create_egs_codes(self, items):
        """POST /api/v1.0/codetypes/requests/codes. A 400 says ETA refused; nothing was registered by it."""
        self._may_send()
        headers = self._headers()
        self._pace()
        try:
            r = requests.post(self._api('/api/v1.0/codetypes/requests/codes'),
                              data=json.dumps({'items': items}).encode('utf-8'), headers=headers, timeout=TIMEOUT,
                              allow_redirects=False, verify=self._verify())
        except requests.RequestException as exc:
            raise EtaUncertain(f'انقطع الاتصال أثناء طلب الكود: {type(exc).__name__}') from exc
        payload = _json(r)
        if r.status_code in (200, 201, 202):
            return r.status_code, payload
        if r.status_code >= 500 or r.status_code == 429:
            raise EtaUncertain(f'ردت المصلحة HTTP {r.status_code}', r.status_code, payload)
        raise EtaRefused(f'رفضت المصلحة طلب الكود (HTTP {r.status_code}): {json.dumps(payload, ensure_ascii=False)[:500]}',
                         r.status_code, payload)

    def request_code_reuse(self, items):
        """PUT /api/v1.0/codetypes/requests/codeusages: ask to use a code ETA already holds (GS1)."""
        self._may_send()
        headers = self._headers()
        self._pace()
        try:
            r = requests.put(self._api('/api/v1.0/codetypes/requests/codeusages'),
                             data=json.dumps({'items': items}).encode('utf-8'), headers=headers, timeout=TIMEOUT,
                             allow_redirects=False, verify=self._verify())
        except requests.RequestException as exc:
            raise EtaUncertain(f'انقطع الاتصال أثناء طلب استخدام الكود: {type(exc).__name__}') from exc
        payload = _json(r)
        if r.status_code in (200, 201, 202):
            # ETA answers a refused item (for example "already has usage") inside a 200.
            if isinstance(payload, dict) and (payload.get('error') or payload.get('rejectedItems')):
                raise EtaRefused(f'رفضت المصلحة طلب استخدام الكود: {json.dumps(payload, ensure_ascii=False)[:500]}',
                                 r.status_code, payload)
            return r.status_code, payload
        if r.status_code >= 500 or r.status_code == 429:
            raise EtaUncertain(f'ردت المصلحة HTTP {r.status_code}', r.status_code, payload)
        raise EtaRefused(f'رفضت المصلحة طلب استخدام الكود (HTTP {r.status_code}): '
                         f'{json.dumps(payload, ensure_ascii=False)[:500]}', r.status_code, payload)

    def my_code_requests(self, item_code):
        """Our code-usage requests for one item code, newest first. Raises when ETA can't be asked."""
        params = {'ItemCode': item_code, 'OrderDirections': 'Descending', 'Pn': 1, 'Ps': 10}
        headers = self._headers()
        self._pace()
        try:
            r = requests.get(self._api('/api/v1.0/codetypes/requests/my'), params=params, headers=headers,
                             timeout=TIMEOUT, allow_redirects=False, verify=self._verify())
        except requests.RequestException as exc:
            raise EtaUncertain(f'تعذر الاستعلام عن طلبات الأكواد: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise EtaUncertain(f'تعذر الاستعلام عن طلبات الأكواد (HTTP {r.status_code})', r.status_code)
        body = _json(r)
        rows = body if isinstance(body, list) else (body.get('result') or body.get('items') or [])
        return [row for row in rows if str(row.get('itemCode') or '').upper() == item_code.upper()]

    def code_details(self, code_type, item_code):
        """ETA's record of one code, or None when ETA says it has no such code. Read only."""
        path = f'/api/v1.0/codetypes/{quote(code_type, safe="")}/codes/{quote(item_code, safe="")}'
        headers = self._headers()
        self._pace()
        try:
            r = requests.get(self._api(path), headers=headers, timeout=TIMEOUT, allow_redirects=False,
                             verify=self._verify())
        except requests.RequestException as exc:
            raise EtaUncertain(f'تعذر الاستعلام عن الكود: {type(exc).__name__}') from exc
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise EtaUncertain(f'تعذر الاستعلام عن الكود (HTTP {r.status_code})', r.status_code)
        return _json(r)
