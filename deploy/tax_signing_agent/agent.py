#!/usr/bin/env python3
"""
deploy/tax_signing_agent/agent.py — the signing agent on the PC that holds the eSeal USB token.

    python agent.py identify --module <pkcs11.dll>     no PIN: slots, token labels, certificates
    python agent.py selftest                           asks for the PIN, signs a local text, verifies it
    python agent.py run [--once]                       pulls jobs from the server, signs, returns them

Version 2 also reads and writes Invoicer's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx) in the folder set
as [agent] invoicer_dir, for the server's file jobs (egs_fetch, egs_write). The folder comes from config.ini,
never from the server. A write is made only in write mode, after the received bytes match their SHA-256 and
the live file is still the one the server expects; it goes through a .new file and a backup, and anything
that goes wrong leaves the live file untouched.

The agent only makes outbound HTTPS calls; nothing connects to it. The PIN comes from a prompt or
TAX_TOKEN_PIN, stays in this process, and is never logged, written or sent. The agent signs in to the
server with its own staff account (TAX_AGENT_PASSWORD, prompt) and sends the agent token as well; a
refused password stops it, like a refused PIN. Steps for the owner:
docs/deploy/2026-11-tax-signing-workstation.md.

Lock safety: a token locks after a few wrong PINs, so a refused PIN stops the agent at once and is
never tried again. The PIN is not tried at all on a token whose certificate is not the expected one,
or which already reports failed attempts.

Tested with a software key and a fake PKCS#11 session only (apps/tests/test_tax_signing.py).
"""
import argparse
import base64
import configparser
import datetime as dt
import getpass
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cades

log = logging.getLogger('tax_agent')

EXIT_OK, EXIT_FAILED, EXIT_FATAL, EXIT_NO_TOKEN, EXIT_CONFIG, EXIT_SERVER_REFUSED, EXIT_NO_SERVER = 0, 1, 2, 3, 4, 5, 6

ENV_PIN = 'TAX_TOKEN_PIN'
ENV_AGENT_TOKEN = 'TAX_SIGNING_AGENT_TOKEN'   # same name as the server setting
ENV_USERNAME = 'TAX_AGENT_USERNAME'
ENV_PASSWORD = 'TAX_AGENT_PASSWORD'
API_LOGIN = '/api/auth/login/'
API_REFRESH = '/api/auth/refresh/'
API_NEXT = '/api/tax-invoicing/signing-agent/next/'
API_RESULT = '/api/tax-invoicing/signing-agent/jobs/{id}/result/'
API_FILE_DOWNLOAD = '/api/tax-invoicing/signing-agent/files/{id}/download/'   # built from the job id only:
API_FILE_RESULT = '/api/tax-invoicing/signing-agent/files/{id}/result/'       # no URL or path from the server
AGENT_VERSION = 2       # sent on every call; the server offers file jobs only to version >= 2
SECRET_CONFIG_KEYS = {'pin', 'token_pin', 'agent_token', 'password', 'secret'}

# PKCS#11 v2.x values, written out so the behaviour does not depend on what a binding exposes.
CKF_USER_PIN_COUNT_LOW, CKF_USER_PIN_FINAL_TRY, CKF_USER_PIN_LOCKED = 0x10000, 0x20000, 0x40000
CKR_USER_ALREADY_LOGGED_IN = 0x100
PIN_ERRORS = {0xA0: 'the token refused the PIN', 0xA1: 'the token refused the PIN format',
              0xA2: 'the token refused the PIN length', 0xA3: 'the PIN has expired on the token',
              0xA4: 'the PIN is locked on the token', 0x102: 'the user PIN is not set on this token'}
ABSENT_ERRORS = {0x03, 0x32, 0xE0, 0xE1}      # slot invalid, device removed, not present, not recognized
BUSY_ERRORS = {0x05, 0x06, 0x30, 0x31, 0x90, 0xB0, 0xB1, 0xB3, 0x101, 0x104}
# general, function failed, device error, device memory, operation active, session closed,
# session count, session handle invalid, not logged in, another user logged in

DIGEST_INFO_SHA256 = bytes.fromhex('3031300d060960864801650304020105000420')   # RFC 8017 §9.2 note 1


class AgentError(Exception):
    """The message of every subclass is safe to log and to send to the server."""


class TokenAbsent(AgentError):
    pass


class TokenBusy(AgentError):
    pass


class TokenFailed(AgentError):
    pass


class ServerUnreachable(AgentError):
    pass


class FatalError(AgentError):
    """Stop the agent: repeating this would not help and may hurt."""
    exit_code = EXIT_FATAL


class PinRefused(FatalError):
    pass


class WrongCertificate(FatalError):
    pass


class ConfigError(FatalError):
    exit_code = EXIT_CONFIG


class ServerRefused(FatalError):
    exit_code = EXIT_SERVER_REFUSED


def load_pkcs11():
    """Imported late so `--help` and the tests work without the binding."""
    try:
        import PyKCS11
    except ImportError as exc:
        raise ConfigError('PyKCS11 is not installed; run: pip install -r requirements.txt') from exc
    return PyKCS11


@dataclass(frozen=True)
class TokenCertificate:
    der: bytes
    key_id: bytes
    label: str
    thumbprint: str
    subject: str
    issuer: str
    serial: str
    not_after: dt.datetime
    is_ca: bool
    key_type: str


def normalise_thumbprint(value):
    return ''.join(ch for ch in str(value or '').upper() if ch in '0123456789ABCDEF')


def parse_certificate(der, key_id=b'', label=''):
    from asn1crypto import x509 as ax509
    loaded = cades.load_certificate(der)
    parsed = ax509.Certificate.load(der)
    return TokenCertificate(
        der=der, key_id=key_id, label=label,
        thumbprint=hashlib.sha1(der, usedforsecurity=False).hexdigest().upper(),   # Windows thumbprint, an identifier
        subject=loaded.subject.rfc4514_string(), issuer=loaded.issuer.rfc4514_string(),
        serial=cades.serial_hex(parsed), not_after=loaded.not_valid_after_utc,
        is_ca=bool(parsed.ca), key_type=parsed.public_key.algorithm.upper())


class Token:
    """One USB token. A session lasts one signature, so the token stays free between jobs."""

    def __init__(self, p11, module_path, *, label='', thumbprint='', allow_low_pin_count=False, pin=None):
        self.p11 = p11
        self.module_path = module_path
        self.label = label
        self.thumbprint = normalise_thumbprint(thumbprint)
        self.allow_low_pin_count = allow_low_pin_count
        self._pin = pin
        self._pin_refused = False
        self._lib = None

    def __repr__(self):
        return f'<Token module={self.module_path!r} label={self.label!r}>'

    def _library(self):
        if self._lib is None:
            lib = self.p11.PyKCS11Lib()
            try:
                lib.load(self.module_path)
            except self.p11.PyKCS11Error as exc:
                raise ConfigError(
                    f'cannot load the PKCS#11 module {self.module_path}. Check the path, and that it has the same '
                    f'bitness as this Python ({_bits()}-bit); identify_token.ps1 shows the module bitness.') from exc
            self._lib = lib
        return self._lib

    def _classify(self, exc):
        """Turn a PKCS#11 error into one of ours. The text holds only the code and its standard name."""
        code = getattr(exc, 'value', None)
        names = getattr(self.p11, 'CKR', {})
        name = f'{names.get(code, "CKR")} (0x{code:X})' if isinstance(code, int) and code >= 0 else 'library error'
        if code in PIN_ERRORS:
            self._pin_refused = True
            self._pin = None
            return PinRefused(f'{PIN_ERRORS[code]} [{name}]. The agent stopped and will not try again, so the token '
                              'does not lock. Check the PIN before starting it again.')
        if code in ABSENT_ERRORS:
            return TokenAbsent(f'the token is not reachable: it may have been removed [{name}]')
        if code in BUSY_ERRORS:
            return TokenBusy(f'the token is busy or returned a temporary error [{name}]')
        return TokenFailed(f'the token returned an error [{name}]')

    def _labelled(self, info):
        return str(getattr(info, 'label', '') or '').strip()

    def find_slot(self):
        """The slot holding our token. This touches the slot list only, not the token's key."""
        lib = self._library()
        try:
            slots = list(lib.getSlotList(tokenPresent=True))
            if self.label:
                slots = [s for s in slots if self._labelled(lib.getTokenInfo(s)) == self.label]
        except self.p11.PyKCS11Error as exc:
            raise self._classify(exc) from exc
        if not slots:
            wanted = f' with label "{self.label}"' if self.label else ''
            raise TokenAbsent(f'no token{wanted} is present')
        if len(slots) > 1:
            raise ConfigError('more than one token is present; set [token] label in the configuration')
        return slots[0]

    def _read_certificates(self, session):
        p11 = self.p11
        found = []
        for obj in session.findObjects([(p11.CKA_CLASS, p11.CKO_CERTIFICATE)]):
            value, key_id, label = session.getAttributeValue(obj, [p11.CKA_VALUE, p11.CKA_ID, p11.CKA_LABEL],
                                                             allAsBinary=True)
            if not value:
                continue
            found.append(parse_certificate(bytes(value), bytes(key_id or b''),
                                           bytes(label or b'').decode('utf-8', 'replace').strip()))
        return found

    def _select_certificate(self, certificates):
        if self.thumbprint:
            for cert in certificates:
                if cert.thumbprint == self.thumbprint:
                    chosen = cert
                    break
            else:
                seen = ', '.join(c.thumbprint for c in certificates) or 'none'
                raise WrongCertificate(f'this token does not hold the expected certificate {self.thumbprint} '
                                       f'(it has: {seen}). The PIN was not tried.')
        else:
            candidates = [c for c in certificates if not c.is_ca]
            if len(candidates) != 1:
                raise ConfigError(f'{len(candidates)} signing certificates found on the token; '
                                  'set [token] thumbprint in the configuration')
            chosen = candidates[0]
        if chosen.not_after <= dt.datetime.now(dt.timezone.utc):
            raise WrongCertificate(f'the certificate {chosen.thumbprint} expired on {chosen.not_after:%Y-%m-%d}. '
                                   'The PIN was not tried.')
        return chosen

    def _check_pin_state(self, slot):
        flags = int(self._library().getTokenInfo(slot).flags)
        if flags & CKF_USER_PIN_LOCKED:
            raise PinRefused('the token reports its PIN is locked. The PIN was not tried. '
                             'Unlocking needs the issuer or the vendor tool.')
        if flags & CKF_USER_PIN_FINAL_TRY:
            raise PinRefused('the token reports one PIN attempt left. The PIN was not tried, because one more wrong '
                             'attempt would lock it. Check the PIN with the vendor tool first.')
        if flags & CKF_USER_PIN_COUNT_LOW and not self.allow_low_pin_count:
            raise PinRefused('the token reports earlier wrong PIN attempts. The PIN was not tried. Check who else '
                             'uses this token and confirm the PIN; then run once with --allow-low-pin-count.')

    def _login(self, session):
        if self._pin_refused or not self._pin:
            raise PinRefused('no usable PIN; the agent will not try the token')
        try:
            session.login(self._pin)
        except self.p11.PyKCS11Error as exc:
            if getattr(exc, 'value', None) != CKR_USER_ALREADY_LOGGED_IN:
                raise

    def _private_key(self, session, cert):
        p11 = self.p11
        keys = list(session.findObjects([(p11.CKA_CLASS, p11.CKO_PRIVATE_KEY)]))
        if not keys:
            raise WrongCertificate('the token shows no private key after login')
        if cert.key_id:
            for key in keys:
                key_id = session.getAttributeValue(key, [p11.CKA_ID], allAsBinary=True)[0]
                if bytes(key_id or b'') == cert.key_id:
                    return key
        if len(keys) == 1:
            return keys[0]
        raise WrongCertificate('the private key for this certificate could not be identified on the token')

    def _signer(self, session, key, slot):
        """Prefer hashing on the token; otherwise send it the DigestInfo that CKM_RSA_PKCS expects."""
        p11 = self.p11
        supported = self._library().getMechanismList(slot)
        if 'CKM_SHA256_RSA_PKCS' in supported or p11.CKM_SHA256_RSA_PKCS in supported:
            mechanism = p11.Mechanism(p11.CKM_SHA256_RSA_PKCS, None)
            return lambda data: bytes(session.sign(key, data, mechanism))
        if 'CKM_RSA_PKCS' in supported or p11.CKM_RSA_PKCS in supported:
            mechanism = p11.Mechanism(p11.CKM_RSA_PKCS, None)
            return lambda data: bytes(session.sign(key, DIGEST_INFO_SHA256 + hashlib.sha256(data).digest(), mechanism))
        raise FatalError('the token offers neither CKM_SHA256_RSA_PKCS nor CKM_RSA_PKCS')

    def sign_content(self, content):
        """DER CAdES-BES over `content`. The certificate is checked before the PIN is used."""
        slot = self.find_slot()
        try:
            session = self._library().openSession(slot)
        except self.p11.PyKCS11Error as exc:
            raise self._classify(exc) from exc
        try:
            cert = self._select_certificate(self._read_certificates(session))
            self._check_pin_state(slot)
            self._login(session)
            try:
                sign = self._signer(session, self._private_key(session, cert), slot)
                return cades.build_cades_bes(content, cert.der, sign)
            finally:
                _quietly(session.logout)
        except self.p11.PyKCS11Error as exc:
            raise self._classify(exc) from exc
        finally:
            _quietly(session.closeSession)

    def describe(self):
        """Everything `identify` shows. Never logs in, and never asks for a PIN."""
        lib = self._library()
        rows = []
        try:
            for slot in lib.getSlotList(tokenPresent=True):
                info = lib.getTokenInfo(slot)
                mechanisms = [str(m) for m in lib.getMechanismList(slot)]
                session = lib.openSession(slot)
                try:
                    certificates = self._read_certificates(session)
                finally:
                    _quietly(session.closeSession)
                rows.append({'slot': slot, 'label': self._labelled(info),
                             'manufacturer': str(info.manufacturerID).strip(), 'model': str(info.model).strip(),
                             'serial': str(info.serialNumber).strip(), 'flags': int(info.flags),
                             'sha256_rsa': 'CKM_SHA256_RSA_PKCS' in mechanisms, 'rsa_pkcs': 'CKM_RSA_PKCS' in mechanisms,
                             'certificates': certificates})
        except self.p11.PyKCS11Error as exc:
            raise self._classify(exc) from exc
        return rows


def _quietly(call):
    try:
        call()
    except Exception as exc:   # closing a session on a removed token fails; the real error is already on its way
        log.debug('ignored while closing: %s', type(exc).__name__)


def _bits():
    return 64 if sys.maxsize > 2 ** 32 else 32


class Server:
    """The two agent endpoints. Refuses plain HTTP and redirects, so the agent token cannot leak."""

    def __init__(self, base_url, agent_token, *, username='', password='', ca_bundle='', http=None, timeout=20,
                 file_timeout=180):
        if not str(base_url).lower().startswith('https://'):
            raise ConfigError('[server] url must start with https://')
        if not agent_token:
            raise ConfigError(f'{ENV_AGENT_TOKEN} is not set')
        if not username or not password:
            raise ConfigError(f'the agent signs in with its own staff account: set [server] username '
                              f'(or {ENV_USERNAME}) and {ENV_PASSWORD}')
        self.base_url = base_url.rstrip('/')
        self.username = username
        self._password = password
        self._agent_token = agent_token
        self._access = ''
        self._refresh = ''
        self.verify = ca_bundle or True
        self.timeout = timeout
        self.file_timeout = file_timeout      # the server checks an uploaded sheet inside the request
        self.http = http or self._session()

    def __repr__(self):
        return f'<Server {self.base_url} as {self.username}>'

    @staticmethod
    def _session():
        import requests
        session = requests.Session()
        session.trust_env = False   # no proxy or .netrc from the machine's environment
        return session

    def _send(self, path, body, headers, *, method='post', files=None, timeout=None):
        """One request. The sign-in cookies the server also sets are dropped: the agent sends its token
        in the Authorization header only, and never X-Requested-With (that is the browser's mark)."""
        url, timeout = self.base_url + path, timeout or self.timeout
        try:
            if method == 'get':
                response = self.http.get(url, headers=headers, timeout=timeout, allow_redirects=False,
                                         verify=self.verify)
            elif files is not None:
                response = self.http.post(url, headers=headers, data=body, files=files, timeout=timeout,
                                          allow_redirects=False, verify=self.verify)
            else:
                response = self.http.post(url, headers=headers, json=body, timeout=timeout,
                                          allow_redirects=False, verify=self.verify)
        except OSError as exc:      # requests' errors are OSError, TLS failures included
            raise ServerUnreachable(f'cannot reach the server: {type(exc).__name__}') from exc
        jar = getattr(self.http, 'cookies', None)
        if jar is not None:
            jar.clear()
        if 300 <= response.status_code < 400:
            raise ServerRefused(f'the server answered with a redirect ({response.status_code}); check [server] url')
        if response.status_code >= 500:
            raise ServerUnreachable(f'the server answered {response.status_code}')
        return response

    def sign_in(self):
        """Username and password, once. A refusal stops the agent, as a wrong PIN does: repeating it
        would only lock the account."""
        response = self._send(API_LOGIN, {'username': self.username, 'password': self._password}, {})
        body = self._json(response) if response.status_code in (200, 403, 429) else {}
        if response.status_code == 200 and body.get('access') and body.get('refresh'):
            self._access, self._refresh = body['access'], body['refresh']
            log.info('signed in as %s', self.username)
            return
        if response.status_code == 200 and (body.get('mfa_required') or body.get('mfa_setup_required')):
            raise ServerRefused(f'the account {self.username} asks for two-factor sign-in, which the agent cannot '
                                'answer. Use an account whose role does not require it, with 2FA off.')
        if response.status_code == 401:
            raise ServerRefused(f'the server refused the username or password for {self.username}. The agent '
                                'stopped and will not try again, so the account does not lock.')
        if response.status_code == 429:
            raise ServerRefused(f'sign-in for {self.username} is locked or throttled. Wait, or ask an admin to '
                                'lift the lock, after checking the password.')
        if response.status_code == 403:
            reason = str(body.get('error') or body.get('detail') or '')[:200]
            raise ServerRefused(f'the server refused sign-in for {self.username} (403): {reason}')
        raise ServerUnreachable(f'sign-in answered {response.status_code}')

    def _renew(self):
        """A fresh access token from the refresh token; a full sign-in when that is refused."""
        if self._refresh:
            response = self._send(API_REFRESH, {'refresh': self._refresh}, {})
            body = self._json(response) if response.status_code == 200 else {}
            if response.status_code == 200 and body.get('access'):
                self._access = body['access']
                self._refresh = body.get('refresh') or self._refresh   # rotated: the old one is now void
                return
            if response.status_code not in (400, 401, 403):
                raise ServerUnreachable(f'token refresh answered {response.status_code}')
        self._access = self._refresh = ''
        self.sign_in()

    def _post(self, path, body, **options):
        if not self._access:
            self.sign_in()
        for attempt in (1, 2):
            headers = {'Authorization': f'Bearer {self._access}', 'X-Tax-Agent-Token': self._agent_token,
                       'X-Tax-Agent-Version': str(AGENT_VERSION)}
            response = self._send(path, body, headers, **options)
            if response.status_code == 401 and attempt == 1:
                self._renew()      # access tokens last an hour; the server answers 401 once one runs out
                continue
            if response.status_code in (401, 403):
                raise ServerRefused(
                    f'the server refused the agent ({response.status_code}). Check {ENV_AGENT_TOKEN} here and on the '
                    f'server, that the role of {self.username} holds tax_invoicing finalize, and the zone policy.')
            return response

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except ValueError as exc:
            raise ServerUnreachable(f'the server sent an unreadable answer ({response.status_code})') from exc

    def next_job(self):
        response = self._post(API_NEXT, {})
        if response.status_code == 404:
            raise ServerRefused('the agent address does not exist on this server; check [server] url')
        if response.status_code != 200:
            raise ServerUnreachable(f'the server answered {response.status_code}')
        return self._json(response).get('job')

    def post_result(self, job_id, *, signature='', error=''):
        """True if the server took it; False if the job is no longer waiting for us."""
        body = {'signature': signature} if signature else {'error': error[:1000]}
        response = self._post(API_RESULT.format(id=int(job_id)), body)
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise ServerUnreachable(f'the server answered {response.status_code}')
        return True

    def download_file(self, job_id):
        """The version file of an egs_write job: the response as it came (status, content, headers)."""
        return self._post(API_FILE_DOWNLOAD.format(id=int(job_id)), None, method='get', timeout=self.file_timeout)

    def post_file_result(self, job_id, status, *, result=None, error='', file_bytes=None):
        """True if the server took it; False if the job is no longer waiting for us, or the server refused the
        uploaded copy (it then marks the job failed itself)."""
        path = API_FILE_RESULT.format(id=int(job_id))
        if file_bytes is None:
            response = self._post(path, {'status': status, 'result': result or {}, 'error': error[:1000]})
        else:
            form = {'status': status, 'result': json.dumps(result or {}), 'error': error[:1000]}
            response = self._post(path, form, files={'file': (LIVE_NAME, file_bytes, XLSX_TYPE)},
                                  timeout=self.file_timeout)
        if response.status_code == 404:
            return False
        if response.status_code in (400, 413):
            detail = ''
            try:
                detail = str((response.json() or {}).get('detail') or '')[:200]
            except (ValueError, AttributeError):
                pass
            log.error('file job %s: the server refused the result (%s) %s', job_id, response.status_code, detail)
            return False
        if response.status_code != 200:
            raise ServerUnreachable(f'the server answered {response.status_code}')
        return True


# ── Invoicer's bulk EGS sheet (file jobs, version 2) ───────────────────────────────────────────

LIVE_NAME = 'ElRezeiky_Bulk_EGS_Items.xlsx'        # the name the Invoicer reads
NEW_NAME = 'ElRezeiky_Bulk_EGS_Items.new.xlsx'     # the next sheet, written beside it before the swap
BACKUP_FOLDER = 'backup'
BACKUP_KEEP = 30
BACKUP_NAME = re.compile(r'^ElRezeiky_Bulk_EGS_Items\.(\d{8}-\d{6})(?:-(\d+))?\.xlsx$')
MAX_SHEET_BYTES = 20 * 1024 * 1024                 # the server's upload cap
XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
FILE_KINDS = ('egs_fetch', 'egs_write')
DONE, FAILED, BUSY = 'done', 'failed', 'busy'
SHA256_HEX = re.compile(r'^[0-9a-f]{64}$')


class FileBusy(AgentError):
    """Invoicer or Excel held the sheet for the whole retry window."""


class LiveChanged(AgentError):
    """The live sheet is not the one the server expects to replace."""


@dataclass
class SheetPlace:
    """Where the sheet lives, from config.ini only. `retries` PermissionError retries, `retry_seconds` apart."""
    invoicer_dir: str
    sleep: object = time.sleep
    now: object = dt.datetime.now
    retries: int = 5
    retry_seconds: float = 24      # 5 retries over about two minutes

    @property
    def folder(self):
        return Path(self.invoicer_dir)

    @property
    def live(self):
        return self.folder / LIVE_NAME

    @property
    def new(self):
        return self.folder / NEW_NAME

    @property
    def backup_dir(self):
        return self.folder / BACKUP_FOLDER

    @property
    def excel_owner_file(self):
        return self.folder / ('~$' + LIVE_NAME)     # Excel's mark that someone has the sheet open


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_copy(path):
    """The bytes of `path`, read from a temporary copy outside the Invoicer folder: the file itself is only ever
    opened for reading, by the copy."""
    fd, temp = tempfile.mkstemp(prefix='egs_sheet_', suffix='.xlsx')
    os.close(fd)
    try:
        shutil.copyfile(path, temp)
        with open(temp, 'rb') as handle:
            return handle.read()
    finally:
        try:
            os.unlink(temp)
        except OSError:
            log.warning('could not remove the temporary copy %s', temp)


def _with_retries(place, call, what):
    """call() with PermissionError (the file is in use) retried; (value, retries used). FileBusy at the end."""
    for attempt in range(place.retries + 1):
        try:
            return call(), attempt
        except PermissionError:
            if attempt == place.retries:
                break
            log.warning('%s: the sheet is in use; retry %s of %s in %ss', what, attempt + 1, place.retries,
                        place.retry_seconds)
            place.sleep(place.retry_seconds)
    raise FileBusy(f'{what}: the sheet stayed in use (Invoicer or Excel) for the whole retry window')


def _live_state(place):
    """{'sha256', 'size', 'data', 'locked', 'retries'} of the live sheet, from a copy; None when it is not there."""
    if not place.live.is_file():
        return None
    data, retries = _with_retries(place, lambda: read_copy(place.live), 'reading the live sheet')
    return {'sha256': _sha256(data), 'size': len(data), 'data': data,
            'locked': bool(retries) or place.excel_owner_file.exists(), 'retries': retries}


def _backup_dir_writable(place):
    """Best effort, and writes nothing: on Windows this only sees the read-only flag."""
    target = place.backup_dir if place.backup_dir.is_dir() else place.folder
    return target.is_dir() and os.access(target, os.W_OK)


def _outcome(status, result, error='', file_bytes=None):
    return {'status': status, 'result': result, 'error': error, 'file': file_bytes}


def check_place(place):
    """An error text when the configured folder cannot be used; '' when it can."""
    if not str(place.invoicer_dir or '').strip():
        return 'invoicer_dir is not set in [agent] of config.ini; the agent does not touch the sheet without it'
    if not place.folder.is_dir():
        return f'invoicer_dir {place.invoicer_dir} is not a folder on this PC'
    return ''


def fetch_live(place):
    """egs_fetch: a copy of the live sheet for the server. Nothing in the Invoicer folder is written."""
    problem = check_place(place)
    if problem:
        return _outcome(FAILED, {}, problem)
    try:
        live = _live_state(place)
    except FileBusy as exc:
        return _outcome(BUSY, {'locked': True, 'retries': place.retries}, str(exc))
    except OSError as exc:
        return _outcome(FAILED, {}, f'cannot copy the live sheet: {type(exc).__name__}')
    if live is None:
        return _outcome(FAILED, {}, f'{LIVE_NAME} is not in {place.invoicer_dir}')
    result = {'live_sha256': live['sha256'], 'live_size': live['size'], 'locked': live['locked'],
              'retries': live['retries']}
    if live['size'] > MAX_SHEET_BYTES:
        return _outcome(FAILED, result, f'the live sheet is larger than {MAX_SHEET_BYTES // (1024 * 1024)} MB')
    return _outcome(DONE, result, file_bytes=live['data'])


def _backup_path(place):
    stamp = place.now().strftime('%Y%m%d-%H%M%S')
    path, n = place.backup_dir / f'ElRezeiky_Bulk_EGS_Items.{stamp}.xlsx', 0
    while path.exists():
        n += 1
        path = place.backup_dir / f'ElRezeiky_Bulk_EGS_Items.{stamp}-{n}.xlsx'
    return path


def prune_backups(place, keep=BACKUP_KEEP):
    """Keep the newest `keep` backups (by the time in their name). Only our own backup names are touched."""
    found = []
    if place.backup_dir.is_dir():
        for path in place.backup_dir.iterdir():
            match = BACKUP_NAME.match(path.name)
            if match and path.is_file():
                found.append(((match.group(1), int(match.group(2) or 0)), path))
    found.sort(key=lambda row: row[0], reverse=True)
    removed = []
    for _, path in found[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError as exc:
            log.warning('could not remove the old backup %s: %s', path.name, type(exc).__name__)
    return removed


def _make_backup(place, live_sha256):
    """Copy the live sheet into backup\\ and check the copy is the live sheet this write expects to replace."""
    place.backup_dir.mkdir(exist_ok=True)
    path = _backup_path(place)
    _with_retries(place, lambda: shutil.copyfile(place.live, path), 'backing up the live sheet')
    with open(path, 'rb') as handle:
        copied = _sha256(handle.read())
    if copied != live_sha256:
        path.unlink(missing_ok=True)
        raise LiveChanged('the live sheet changed while it was being backed up')
    return path


def _swap(place, data, expected, live, result):
    """Write mode, after every check: .new beside the live sheet, a backup, then os.replace. The live sheet is
    replaced whole or not at all, and .new never stays behind."""
    try:
        with open(place.new, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with open(place.new, 'rb') as handle:
            if _sha256(handle.read()) != expected:
                return _outcome(FAILED, result, 'the new sheet did not save correctly; live sheet untouched')
        backup = _make_backup(place, live['sha256'])
        result['backup'] = backup.name
        result['backups_removed'] = len(prune_backups(place))
        try:
            _, retries = _with_retries(place, lambda: os.replace(place.new, place.live), 'replacing the live sheet')
        except FileBusy as exc:
            result.update({'locked': True, 'retries': place.retries})
            return _outcome(BUSY, result, f'{exc}; live sheet untouched')
        result['retries'] = retries
    except LiveChanged as exc:
        result['live_changed'] = True
        return _outcome(FAILED, result, f'live_changed: {exc}; live sheet untouched')
    except FileBusy as exc:
        return _outcome(BUSY, result, f'{exc}; live sheet untouched')
    except OSError as exc:
        return _outcome(FAILED, result, f'could not write the sheet ({type(exc).__name__}); live sheet untouched')
    finally:
        if place.new.exists():
            try:
                place.new.unlink()
            except OSError as exc:
                log.error('could not remove %s: %s', NEW_NAME, type(exc).__name__)
    result['written'] = True
    try:
        after = _live_state(place)
    except (FileBusy, OSError):
        after = None    # Invoicer opened the new sheet at once; the swap itself is done
    result['live_sha256_after'] = after['sha256'] if after else ''
    if after is not None and after['sha256'] != expected:
        return _outcome(FAILED, result, 'the live sheet was replaced but reads back different; copy '
                                        f'{result["backup"]} back from the backup folder')
    return _outcome(DONE, result)


def write_sheet(place, job, download):
    """egs_write. `download(job_id)` returns the server's response. Unless both the job and the server's
    X-Job-Mode say 'write', this is a preview: nothing is written in the Invoicer folder, and the result says
    what a write would do."""
    expected = str(job.get('sha256') or '').lower()
    result = {'version': job.get('version'), 'sha256': expected, 'job_mode': job.get('mode')}
    problem = check_place(place)
    if problem:
        return _outcome(FAILED, result, problem)
    if not SHA256_HEX.match(expected):
        return _outcome(FAILED, result, 'the job carries no valid SHA-256; nothing written')
    try:
        response = download(job['id'])
    except ServerUnreachable as exc:
        return _outcome(FAILED, result, f'the download failed ({exc}); nothing written')
    if response.status_code != 200:
        return _outcome(FAILED, result, f'the download answered {response.status_code}; nothing written')
    data = response.content or b''
    headers = response.headers or {}
    received, header_sha = _sha256(data), str(headers.get('X-Content-SHA256') or '').lower()
    header_mode = str(headers.get('X-Job-Mode') or '')
    result.update({'received_size': len(data), 'received_sha256': received, 'header_mode': header_mode})
    if received != expected or header_sha != expected:
        return _outcome(FAILED, result, 'the downloaded sheet does not match its SHA-256 (truncated or changed); '
                                        'nothing written')
    writing = job.get('mode') == 'write' and header_mode == 'write'
    result['backup_dir_writable'] = _backup_dir_writable(place)
    try:
        live = _live_state(place)
    except FileBusy:
        live = None
        result.update({'locked': True, 'retries': place.retries})
        if writing:
            return _outcome(BUSY, result, 'the live sheet stayed in use while it was being read; live sheet untouched')
    except OSError as exc:
        return _outcome(FAILED, result, f'cannot copy the live sheet ({type(exc).__name__}); nothing written')
    if live is not None:
        result.update({'live_sha256_before': live['sha256'], 'live_size': live['size'], 'locked': live['locked']})
    live_matches = live is not None and live['sha256'] == str(job.get('live_sha256') or '').lower()
    result['live_changed'] = live is not None and not live_matches
    if not writing:
        result.update({'preview': True, 'would_write': live_matches and result['backup_dir_writable']})
        return _outcome(DONE, result)
    if live is None:
        return _outcome(FAILED, result, f'{LIVE_NAME} is not in {place.invoicer_dir}; nothing written')
    if not live_matches:
        return _outcome(FAILED, result, 'live_changed: the live sheet is not the one this write expects to '
                                        'replace (edited since the last read); live sheet untouched')
    return _swap(place, data, expected, live, result)


class Backoff:
    def __init__(self, base, cap=300):
        self.base, self.cap, self.failures = base, cap, 0

    def next_delay(self):
        delay = min(self.cap, self.base * (2 ** self.failures))
        self.failures += 1
        return delay

    def reset(self):
        self.failures = 0


class Agent:
    def __init__(self, token, server, *, sleep=time.sleep, poll_seconds=5, busy_budget_seconds=40,
                 result_attempts=6, retry_base_seconds=2, invoicer_dir='', now=dt.datetime.now,
                 swap_retries=5, swap_retry_seconds=24):
        self.token, self.server, self.sleep = token, server, sleep
        self.sheet = SheetPlace(invoicer_dir, sleep=sleep, now=now, retries=swap_retries,
                                retry_seconds=swap_retry_seconds)
        self.poll_seconds = poll_seconds
        self.busy_budget_seconds = busy_budget_seconds
        self.result_attempts = result_attempts
        self.retry_base_seconds = retry_base_seconds

    def _sign_with_retries(self, content):
        """A busy token gets short retries that stay inside the server's wait for the job."""
        waited, backoff = 0, Backoff(self.retry_base_seconds, cap=8)
        while True:
            try:
                return self.token.sign_content(content)
            except TokenBusy:
                delay = backoff.next_delay()
                if waited + delay > self.busy_budget_seconds:
                    raise
                log.warning('the token is busy; retrying in %ss', delay)
                self.sleep(delay)
                waited += delay

    def _report(self, job_id, *, signature='', error=''):
        """Network trouble retries the same answer; the token is never asked to sign twice."""
        backoff = Backoff(self.retry_base_seconds, cap=30)
        for attempt in range(self.result_attempts):
            try:
                taken = self.server.post_result(job_id, signature=signature, error=error)
            except ServerUnreachable as exc:
                log.warning('job %s: could not send the result (%s)', job_id, exc)
                if attempt + 1 < self.result_attempts:
                    self.sleep(backoff.next_delay())
                continue
            if not taken:
                log.warning('job %s: the server no longer waits for it (timed out there); result dropped', job_id)
            return taken
        log.error('job %s: the result was not delivered; the server will time this job out', job_id)
        return False

    def handle(self, job):
        """One job, by kind: a sheet file job, else a signing job (document or smoke)."""
        if job.get('kind') in FILE_KINDS:
            return self.handle_file(job)
        return self.handle_signing(job)

    def _report_file(self, job_id, outcome):
        """Network trouble retries the same answer; the sheet is never read or written twice for one job."""
        backoff = Backoff(self.retry_base_seconds, cap=30)
        for attempt in range(self.result_attempts):
            try:
                return self.server.post_file_result(job_id, outcome['status'], result=outcome['result'],
                                                    error=outcome['error'], file_bytes=outcome['file'])
            except ServerUnreachable as exc:
                log.warning('file job %s: could not send the result (%s)', job_id, exc)
                if attempt + 1 < self.result_attempts:
                    self.sleep(backoff.next_delay())
        log.error('file job %s: the result was not delivered; the server will time this job out', job_id)
        return False

    def handle_file(self, job):
        """egs_fetch or egs_write. True if the job ended 'done' and the server took the answer."""
        job_id, kind = job.get('id'), job.get('kind')
        if job_id is None:
            log.error('the server sent a file job without an id; ignored')
            return False
        if kind == 'egs_fetch':
            outcome = fetch_live(self.sheet)
        else:
            outcome = write_sheet(self.sheet, job, self.server.download_file)
        taken = self._report_file(job_id, outcome)
        r = outcome['result']
        log.info('job=%s kind=%s mode=%s status=%s sha256=%s backup=%s delivered=%s%s', job_id, kind,
                 job.get('mode'), outcome['status'], r.get('sha256') or r.get('live_sha256') or '',
                 r.get('backup', ''), 'yes' if taken else 'no',
                 f" error={outcome['error']}" if outcome['error'] else '')
        return bool(taken) and outcome['status'] == DONE

    def handle_signing(self, job):
        """One job. True if a signature reached the server. FatalError passes up after being reported."""
        job_id, text = job.get('id'), job.get('canonical_text')
        if job_id is None:
            log.error('the server sent a job without an id; ignored')
            return False
        if not isinstance(text, str):
            self._report(job_id, error='the job has no canonical text; refused')
            return False
        content = text.encode('utf-8')
        digest = hashlib.sha256(content).hexdigest()
        if digest != job.get('sha256'):
            log.error('job %s: canonical text does not match its SHA-256; refused, nothing signed', job_id)
            self._report(job_id, error='the canonical text does not match its SHA-256; refused, nothing signed')
            return False
        try:
            der = self._sign_with_retries(content)
            cades.inspect_signature(der, content)
        except FatalError as exc:
            log.error('job %s: %s', job_id, exc)
            self._report(job_id, error=str(exc))
            raise
        except (AgentError, cades.SignatureInvalid) as exc:
            log.error('job %s: %s', job_id, exc)
            self._report(job_id, error=str(exc))
            return False
        taken = self._report(job_id, signature=base64.b64encode(der).decode('ascii'))
        # This line is the workstation's own record of what the seal signed: hash, never the text.
        log.info('job=%s kind=%s sha256=%s signed=yes delivered=%s', job_id, job.get('kind'), digest,
                 'yes' if taken else 'no')
        return taken

    def run(self, *, once=False, should_stop=lambda: False):
        token_backoff, server_backoff = Backoff(self.poll_seconds, cap=60), Backoff(self.poll_seconds)
        while not should_stop():
            try:
                self.token.find_slot()     # no job is claimed while the token cannot sign it
                token_backoff.reset()
            except (TokenAbsent, TokenBusy, TokenFailed) as exc:
                if once:
                    log.error('%s', exc)
                    return EXIT_NO_TOKEN
                if not token_backoff.failures:
                    log.warning('%s; waiting for the token', exc)
                self.sleep(token_backoff.next_delay())
                continue
            try:
                job = self.server.next_job()
            except ServerUnreachable as exc:
                if once:
                    log.error('%s', exc)
                    return EXIT_NO_SERVER
                if not server_backoff.failures:
                    log.warning('%s; backing off', exc)
                self.sleep(server_backoff.next_delay())
                continue
            if server_backoff.failures:
                log.info('the server is reachable again')
            server_backoff.reset()
            if job is None:
                if once:
                    log.info('no job waiting')
                    return EXIT_OK
                self.sleep(self.poll_seconds)
                continue
            done = self.handle(job)
            if once:
                return EXIT_OK if done else EXIT_FAILED
        return EXIT_OK


def read_secret(name, label, *, env, prompt):
    """From the environment (removed from it at once), else a prompt on a real console."""
    value = env.pop(name, '')
    if value:
        return value
    if prompt is None:
        raise ConfigError(f'{name} is not set and there is no console to ask on')
    value = prompt(f'{label}: ')
    if not value:
        raise ConfigError(f'{label} was left empty')
    return value


def load_config(path):
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(path, encoding='utf-8'):
        raise ConfigError(f'cannot read the configuration file {path}')
    for section in parser.sections():
        for key in parser[section]:
            if key in SECRET_CONFIG_KEYS:
                raise ConfigError(f'[{section}] {key}: secrets do not belong in this file. Use {ENV_PIN} / '
                                  f'{ENV_AGENT_TOKEN} or the prompt.')
    return parser


def configure_logging(log_file=''):
    handlers = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)   # a fresh install has no logs folder yet
        handlers.append(RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding='utf-8'))
    logging.basicConfig(level=logging.INFO, handlers=handlers, format='%(asctime)s %(levelname)s %(message)s', force=True)


def print_identification(rows, out):
    print(f'Tokens present: {len(rows)}', file=out)
    print('No PIN was used. Certificates shown are the ones a token exposes without login.', file=out)
    for row in rows:
        print(f'\nSlot {row["slot"]}: label="{row["label"]}" manufacturer="{row["manufacturer"]}" '
              f'model="{row["model"]}" token-serial="{row["serial"]}"', file=out)
        states = [text for flag, text in ((CKF_USER_PIN_COUNT_LOW, 'EARLIER WRONG PIN ATTEMPTS'),
                                          (CKF_USER_PIN_FINAL_TRY, 'ONE PIN ATTEMPT LEFT'),
                                          (CKF_USER_PIN_LOCKED, 'PIN LOCKED')) if row['flags'] & flag]
        print(f'  PIN state: {", ".join(states) if states else "no warnings reported"}', file=out)
        print(f'  Mechanisms: CKM_SHA256_RSA_PKCS={"yes" if row["sha256_rsa"] else "no"} '
              f'CKM_RSA_PKCS={"yes" if row["rsa_pkcs"] else "no"}', file=out)
        if not row['certificates']:
            print('  No certificate is visible without login.', file=out)
        for cert in row['certificates']:
            print(f'  Certificate "{cert.label}"{" (CA)" if cert.is_ca else ""} key={cert.key_type}', file=out)
            print(f'    Subject:    {cert.subject}', file=out)
            print(f'    Issuer:     {cert.issuer}', file=out)
            print(f'    Serial:     {cert.serial}', file=out)
            print(f'    Expires:    {cert.not_after:%Y-%m-%d %H:%M} UTC', file=out)
            print(f'    Thumbprint: {cert.thumbprint}  (SHA-1)', file=out)


def self_test(token, out, *, count=1, pause_seconds=0, sleep=time.sleep):
    """Local only: nothing is sent anywhere. Each round is one PIN login. A refused PIN ends it."""
    failures = 0
    for round_number in range(1, count + 1):
        content = f'ElRezeiky signing selftest {dt.datetime.now(dt.timezone.utc).isoformat()}, not a document'.encode()
        started = time.monotonic()
        try:
            details = cades.inspect_signature(token.sign_content(content), content)
        except (TokenBusy, TokenAbsent, TokenFailed, cades.SignatureInvalid) as exc:
            failures += 1
            print(f'Round {round_number}/{count}: FAILED - {exc}', file=out)
        else:
            print(f'Round {round_number}/{count}: PASS in {time.monotonic() - started:.2f}s', file=out)
            if round_number == 1:
                print(f'  Signed by:  {details["subject"]}\n  Issuer:     {details["issuer"]}\n'
                      f'  Thumbprint: {details["thumbprint"]}\n  Expires:    {details["not_after"]}', file=out)
        if round_number < count and pause_seconds:
            sleep(pause_seconds)
    print('Checked on this PC only, with a local verification. This does not prove ETA accepts the signature.', file=out)
    return EXIT_OK if not failures else EXIT_FAILED


def _build_parser():
    parser = argparse.ArgumentParser(description='ElRezeiky tax signing agent')
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.ini')))
    commands = parser.add_subparsers(dest='command', required=True)
    identify = commands.add_parser('identify', help='list tokens and certificates; no PIN')
    identify.add_argument('--module', help='path of the PKCS#11 DLL (otherwise from the configuration)')
    selftest = commands.add_parser('selftest', help='ask for the PIN, sign a local text, verify it')
    selftest.add_argument('--allow-low-pin-count', action='store_true')
    selftest.add_argument('--count', type=int, default=1, help='rounds, for the contention test')
    selftest.add_argument('--pause', type=float, default=0, help='seconds between rounds')
    run = commands.add_parser('run', help='pull jobs from the server and sign them')
    run.add_argument('--once', action='store_true', help='handle at most one job, then exit')
    run.add_argument('--allow-low-pin-count', action='store_true')
    return parser


def _console_prompt():
    return getpass.getpass if sys.stdin is not None and sys.stdin.isatty() else None


def main(argv=None, *, p11=None, http=None, env=None, prompt=None, out=None, sleep=time.sleep):
    args = _build_parser().parse_args(argv)
    env = os.environ if env is None else env
    out = out or sys.stdout
    prompt = prompt if prompt is not None else _console_prompt()
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8', errors='replace')
    try:
        p11 = p11 or load_pkcs11()
        config_exists = Path(args.config).exists()
        if args.command == 'identify' and args.module and not config_exists:
            return _identify(p11, args.module, '', out)
        config = load_config(args.config)
        token_section = config['token'] if config.has_section('token') else {}
        module = (getattr(args, 'module', None) or token_section.get('pkcs11_module', '')).strip()
        if not module:
            raise ConfigError('set [token] pkcs11_module in the configuration')
        label = token_section.get('label', '').strip()
        if args.command == 'identify':
            return _identify(p11, module, label, out)

        agent_section = config['agent'] if config.has_section('agent') else {}
        configure_logging(agent_section.get('log_file', '').strip())
        server = None
        if args.command == 'run':
            section = config['server'] if config.has_section('server') else {}
            username = (env.pop(ENV_USERNAME, '') or section.get('username', '')).strip()
            if not username:
                raise ConfigError(f'set [server] username (or {ENV_USERNAME}): the agent signs in with its own account')
            server = Server(section.get('url', '').strip(),
                            read_secret(ENV_AGENT_TOKEN, 'Agent token', env=env, prompt=prompt),
                            username=username,
                            password=read_secret(ENV_PASSWORD, f'Password for {username}', env=env, prompt=prompt),
                            ca_bundle=section.get('ca_bundle', '').strip(), http=http)
        pin = read_secret(ENV_PIN, 'Token PIN', env=env, prompt=prompt)
        token = Token(p11, module, label=label, thumbprint=token_section.get('thumbprint', ''),
                      allow_low_pin_count=args.allow_low_pin_count, pin=pin)
        if args.command == 'selftest':
            return self_test(token, out, count=max(1, args.count), pause_seconds=args.pause, sleep=sleep)
        agent = Agent(token, server, sleep=sleep, poll_seconds=float(agent_section.get('poll_seconds', '5') or 5),
                      invoicer_dir=agent_section.get('invoicer_dir', '').strip())
        log.info('agent started; server %s; token module %s', server.base_url, module)
        return agent.run(once=args.once)
    except FatalError as exc:
        print(f'STOPPED: {exc}', file=sys.stderr)
        log.error('STOPPED: %s', exc)
        return exc.exit_code
    except AgentError as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        return EXIT_NO_TOKEN if isinstance(exc, TokenAbsent) else EXIT_FAILED
    except KeyboardInterrupt:
        return EXIT_OK


def _identify(p11, module, label, out):
    print_identification(Token(p11, module, label=label).describe(), out)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
