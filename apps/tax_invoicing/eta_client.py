"""
apps/tax_invoicing/eta_client.py — HTTP calls to the Egyptian Tax Authority. Nothing else here.

The important distinction is whether ETA may hold the document afterwards:
  EtaRefused   — we know it was not accepted (bad login, HTTP 4xx): safe to fix and send again.
  EtaUncertain — we can't tell (timeout, dropped connection, 5xx, duplicate): reconcile first.

Addresses and credentials come from the environment; there is no default, so an unconfigured
server cannot reach anything.
"""
import json
import threading
import time

import requests
from django.conf import settings
from core.errors import redact

TIMEOUT = (10, 60)
_token_lock = threading.Lock()
_token = {'value': '', 'expires': 0.0}


class EtaError(Exception):
    pass


class EtaNotConfigured(EtaError):
    pass


class EtaRefused(EtaError):
    def __init__(self, message, http_status=None, body=None):
        super().__init__(redact(message))
        self.http_status, self.body = http_status, body or {}


class EtaUncertain(EtaError):
    def __init__(self, message, http_status=None, body=None):
        super().__init__(redact(message))
        self.http_status, self.body = http_status, body or {}


def _setting(name):
    value = str(getattr(settings, name, '') or '').strip()
    if not value:
        raise EtaNotConfigured(f'إعداد الربط بالمصلحة غير مكتمل ({name})')
    return value


def _json(response):
    try:
        return response.json()
    except ValueError:
        return {}


def reset_token():
    with _token_lock:
        _token.update(value='', expires=0.0)


def access_token():
    """A cached token, as the SDK asks: renewed shortly before it expires."""
    with _token_lock:
        if _token['value'] and _token['expires'] > time.time() + 60:
            return _token['value']
        url = _setting('TAX_ETA_ID_BASE_URL').rstrip('/') + '/connect/token'
        auth = (_setting('TAX_ETA_CLIENT_ID'), _setting('TAX_ETA_CLIENT_SECRET'))
        try:
            r = requests.post(url, data={'grant_type': 'client_credentials'}, auth=auth, timeout=TIMEOUT,
                              allow_redirects=False)
        except requests.RequestException as exc:
            # No document was involved in a login, so nothing can have been sent.
            raise EtaRefused(f'تعذر الاتصال بخدمة الدخول: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise EtaRefused(f'رفضت المصلحة الدخول (HTTP {r.status_code})', r.status_code)
        body = _json(r)
        _token.update(value=body.get('access_token', ''), expires=time.time() + int(body.get('expires_in', 3600)))
        return _token['value']


def _headers():
    return {'Authorization': f'Bearer {access_token()}', 'Content-Type': 'application/json',
            'Accept': 'application/json'}


def _api(path):
    return _setting('TAX_ETA_API_BASE_URL').rstrip('/') + path


def submit_documents(signed_document_text):
    """POST one signed document, sending its exact text. Returns ETA's JSON answer."""
    headers = _headers()
    body = ('{"documents":[' + signed_document_text + ']}').encode('utf-8')
    try:
        r = requests.post(_api('/api/v1.0/documentsubmissions/'), data=body, headers=headers, timeout=TIMEOUT,
                          allow_redirects=False)
    except requests.RequestException as exc:
        raise EtaUncertain(f'انقطع الاتصال أثناء الإرسال: {type(exc).__name__}') from exc
    payload = _json(r)
    if r.status_code in (200, 202):
        return r.status_code, payload
    if r.status_code == 422 or r.status_code >= 500 or r.status_code == 429:
        # 422 = identical submission within 10 minutes: ETA may already have it.
        raise EtaUncertain(f'ردت المصلحة HTTP {r.status_code}', r.status_code, payload)
    raise EtaRefused(f'رفضت المصلحة الطلب (HTTP {r.status_code}): {json.dumps(payload, ensure_ascii=False)[:500]}',
                     r.status_code, payload)


def find_by_internal_id(internal_id, date_from, date_to):
    """The ETA summary of a document by our internal id, or None. Raises when ETA can't be asked:
    "could not ask" must never be read as "not there"."""
    params = {'internalID': internal_id, 'pageSize': 10,
              'issueDateFrom': date_from.strftime('%Y-%m-%dT%H:%M:%SZ'),
              'issueDateTo': date_to.strftime('%Y-%m-%dT%H:%M:%SZ')}
    try:
        r = requests.get(_api('/api/v1.0/documents/search'), params=params, headers=_headers(), timeout=TIMEOUT,
                         allow_redirects=False)
    except requests.RequestException as exc:
        raise EtaUncertain(f'تعذر الاستعلام: {type(exc).__name__}') from exc
    if r.status_code != 200:
        raise EtaUncertain(f'تعذر الاستعلام (HTTP {r.status_code})', r.status_code)
    for row in _json(r).get('result') or []:
        if str(row.get('internalId') or row.get('internalID') or '') == internal_id:
            return row
    return None


# ── E-receipts: each branch's POS logs in with its own serial and keys ─────────────────────────

_pos_tokens = {}


def _env_secret(name):
    import os
    value = os.environ.get(name or '', '') or ''
    if not name or not value:
        raise EtaNotConfigured(f'بيانات دخول الجهاز غير موجودة في البيئة ({name or "غير محدد"})')
    return value


def reset_pos_tokens():
    with _token_lock:
        _pos_tokens.clear()


def pos_token(config):
    with _token_lock:
        cached = _pos_tokens.get(config.softech_branchcode)
        if cached and cached['expires'] > time.time() + 60:
            return cached['value']
        if not (config.client_id and config.device_serial):
            raise EtaNotConfigured(f'بيانات جهاز الفرع {config.softech_branchcode} ناقصة')
        url = _setting('TAX_ETA_ID_BASE_URL').rstrip('/') + '/connect/token'
        headers = {'posserial': config.device_serial, 'pososversion': config.pos_os_version,
                   'posmodelframework': config.pos_model_framework, 'presharedkey': _env_secret(config.preshared_key_env)}
        body = {'grant_type': 'client_credentials', 'client_id': config.client_id,
                'client_secret': _env_secret(config.secret_env)}
        try:
            r = requests.post(url, data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            raise EtaRefused(f'تعذر دخول جهاز الفرع: {type(exc).__name__}') from exc
        if r.status_code != 200:
            raise EtaRefused(f'رفضت المصلحة دخول جهاز الفرع (HTTP {r.status_code})', r.status_code)
        data = _json(r)
        _pos_tokens[config.softech_branchcode] = {'value': data.get('access_token', ''),
                                                  'expires': time.time() + int(data.get('expires_in', 3600))}
        return _pos_tokens[config.softech_branchcode]['value']


def _pos_headers(config):
    return {'Authorization': f'Bearer {pos_token(config)}', 'Content-Type': 'application/json', 'Accept': 'application/json'}


def submit_receipts(config, receipt_texts, signature_b64):
    headers = _pos_headers(config)
    body = ('{"receipts":[' + ','.join(receipt_texts) + '],"signatures":[{"signatureType":"I","value":'
            + json.dumps(signature_b64) + '}]}').encode('utf-8')
    try:
        r = requests.post(_api('/api/v1/receiptsubmissions'), data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise EtaUncertain(f'انقطع الاتصال أثناء إرسال الإيصالات: {type(exc).__name__}') from exc
    payload = _json(r)
    if r.status_code in (200, 202):
        return r.status_code, payload
    if r.status_code == 422 or r.status_code >= 500 or r.status_code == 429:
        raise EtaUncertain(f'ردت المصلحة HTTP {r.status_code}', r.status_code, payload)
    raise EtaRefused(f'رفضت المصلحة الإيصالات (HTTP {r.status_code}): {json.dumps(payload, ensure_ascii=False)[:500]}',
                     r.status_code, payload)


def get_receipt_status(config, uuid_value, submission_uuid=''):
    """ETA's record of one receipt. None only when ETA says it has no such receipt."""
    headers = _pos_headers(config)
    try:
        if submission_uuid:
            r = requests.get(_api(f'/api/v1/receiptsubmissions/{submission_uuid}/details'), headers=headers,
                             params={'PageNo': 1, 'PageSize': 100}, timeout=TIMEOUT, allow_redirects=False)
            if r.status_code == 200:
                for row in _json(r).get('receipts') or []:
                    if row.get('uuid') == uuid_value:
                        return row
        r = requests.get(_api(f'/api/v1/receipts/{uuid_value}/raw'), headers=headers, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise EtaUncertain(f'تعذر الاستعلام: {type(exc).__name__}') from exc
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise EtaUncertain(f'تعذر الاستعلام (HTTP {r.status_code})', r.status_code)
    return _json(r)
