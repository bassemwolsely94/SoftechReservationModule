"""
apps/tax_invoicing/eta_reader.py — reading what ETA holds, from either ETA system, without any way to send.

One reader per system ("preprod", "production"), each with its own ERP login, token and pace. A server reads
a system it may never send to (the office reads production history while it sends nothing there), so this is
separate from eta_client, which serves the one system the server sends to. Its only POSTs are the two package
requests, which ask ETA to prepare a download.

Logins come from the environment / .env only: TAX_ETA_READ_<SYSTEM>_CLIENT_ID / _CLIENT_SECRET. Production
uses an ERP registration made for us, never Invoicer's. Preprod may fall back to the sending login when this
server sends to preprod. Each system has its own switch, TAX_ETA_READ_<SYSTEM>_ENABLED (default off).
"""
import json
import threading
import time

import requests
from django.conf import settings

from . import environment
from .eta_client import TIMEOUT, EtaNotConfigured, EtaRefused, EtaUncertain, _json, _verify

SYSTEMS = ('preprod', 'production')
PACKAGE_PATHS = {'documents': '/api/v1.0/documentpackages', 'receipts': '/api/v1.0/receiptpackages'}
# ETA's published pace per ERP system (apigovernance): search/get/details 2 per second, recent 3 per second.
MIN_INTERVAL = 0.5
RETRIES = 2

_lock = threading.Lock()
_tokens = {}
_last_call = {}


def reset_tokens():
    with _lock:
        _tokens.clear()
        _last_call.clear()


def _setting(name, default=''):
    return getattr(settings, name, default)


class EtaReader:
    def __init__(self, system):
        if system not in SYSTEMS:
            raise ValueError(f'unknown ETA system: {system}')
        self.system = system
        self.hosts = environment.ENVIRONMENTS[system]

    # ── switches and login ──────────────────────────────────────────────────────────────────────
    def enabled(self):
        return bool(_setting(f'TAX_ETA_READ_{self.system.upper()}_ENABLED', False))

    def _credentials(self):
        prefix = f'TAX_ETA_READ_{self.system.upper()}_'
        client_id = str(_setting(prefix + 'CLIENT_ID') or '').strip()
        secret = str(_setting(prefix + 'CLIENT_SECRET') or '').strip()
        if (not client_id or not secret) and self.system == 'preprod' and environment.name() == 'preprod':
            client_id = str(_setting('TAX_ETA_CLIENT_ID') or '').strip()
            secret = str(_setting('TAX_ETA_CLIENT_SECRET') or '').strip()
        return client_id, secret

    def configured(self):
        return all(self._credentials())

    def why_not(self):
        if not self.enabled():
            return f'قراءة سجل المنظومة {self.system} مغلقة (TAX_ETA_READ_{self.system.upper()}_ENABLED)'
        if not self.configured():
            return f'بيانات دخول القراءة للمنظومة {self.system} غير موجودة'
        return ''

    def _token(self):
        reason = self.why_not()
        if reason:
            raise EtaNotConfigured(reason)
        with _lock:
            cached = _tokens.get(self.system)
            if cached and cached['expires'] > time.time() + 60:
                return cached['value']
        client_id, secret = self._credentials()
        try:
            r = requests.post(self.hosts['id'] + '/connect/token',
                              data={'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': secret},
                              timeout=TIMEOUT, allow_redirects=False, verify=_verify())
        except requests.RequestException as exc:
            raise EtaUncertain(f'تعذر الدخول لمنظومة {self.system}: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise EtaRefused(f'رفضت منظومة {self.system} دخول القراءة (HTTP {r.status_code})', r.status_code)
        data = _json(r)
        with _lock:
            _tokens[self.system] = {'value': data.get('access_token', ''),
                                    'expires': time.time() + int(data.get('expires_in', 3600))}
            return _tokens[self.system]['value']

    # ── calls ───────────────────────────────────────────────────────────────────────────────────
    def _pace(self):
        with _lock:
            wait = _last_call.get(self.system, 0) + MIN_INTERVAL - time.time()
            _last_call[self.system] = time.time() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _call(self, method, path, **kw):
        headers = {'Authorization': f'Bearer {self._token()}', 'Accept': 'application/json',
                   'Content-Type': 'application/json'}
        url = self.hosts['api'] + path
        for attempt in range(RETRIES + 1):
            self._pace()
            try:
                r = method(url, headers=headers, timeout=TIMEOUT, allow_redirects=False, verify=_verify(), **kw)
            except requests.RequestException as exc:
                raise EtaUncertain(f'انقطع الاتصال بمنظومة {self.system}: {type(exc).__name__}') from exc
            if r.status_code == 429 and attempt < RETRIES:
                try:
                    time.sleep(float(r.headers.get('Retry-After') or 5))
                except ValueError:
                    time.sleep(5.0)
                continue
            if r.status_code in (502, 503, 504) and attempt < RETRIES:
                time.sleep(2.0)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                raise EtaUncertain(f'منظومة {self.system} ردت HTTP {r.status_code}', r.status_code)
            return r
        raise EtaUncertain(f'منظومة {self.system} لم ترد')

    def get(self, path, params=None):
        return self._call(requests.get, path, params=params)

    def request_package(self, kind, body):
        """Asks ETA to prepare a package (documents or receipts). Returns ETA's package id."""
        r = self._call(requests.post, PACKAGE_PATHS[kind] + '/requests', data=json.dumps(body).encode('utf-8'))
        payload = _json(r)
        if r.status_code in (200, 201):
            pid = payload.get('requestId') or payload.get('packageId') or payload.get('rid') if isinstance(payload, dict) else payload
            return str(pid or '').strip('"')
        raise EtaRefused(json.dumps(payload, ensure_ascii=False)[:500], r.status_code, payload)

    def package_requests(self, kind, page=1, size=50):
        r = self.get(PACKAGE_PATHS[kind] + '/requests', {'pageNo': page, 'pageSize': size})
        if r.status_code != 200:
            raise EtaUncertain(f'تعذر جلب حالة الحزم (HTTP {r.status_code})', r.status_code)
        payload = _json(r)
        return payload.get('result') or [] if isinstance(payload, dict) else []

    def download_package(self, kind, package_id):
        """The package ZIP, or None while ETA is still preparing it (204)."""
        r = self.get(f'{PACKAGE_PATHS[kind]}/{package_id}')
        if r.status_code == 204:
            return None
        if r.status_code != 200:
            raise EtaUncertain(f'تعذر تنزيل الحزمة (HTTP {r.status_code})', r.status_code)
        return r.content
