#!/usr/bin/env python3
"""
deploy/tax_signing_agent/agent.py — the signing agent on the PC that holds the eSeal USB token.

    python agent.py identify --module <pkcs11.dll>     no PIN: slots, token labels, certificates
    python agent.py selftest                           asks for the PIN, signs a local text, verifies it
    python agent.py run [--once]                       pulls jobs from the server, signs, returns them

The agent only makes outbound HTTPS calls; nothing connects to it. The PIN comes from a prompt or
TAX_TOKEN_PIN, stays in this process, and is never logged, written or sent. Steps for the owner:
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
import logging
import os
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cades

log = logging.getLogger('tax_agent')

EXIT_OK, EXIT_FAILED, EXIT_FATAL, EXIT_NO_TOKEN, EXIT_CONFIG, EXIT_SERVER_REFUSED, EXIT_NO_SERVER = 0, 1, 2, 3, 4, 5, 6

ENV_PIN = 'TAX_TOKEN_PIN'
ENV_AGENT_TOKEN = 'TAX_SIGNING_AGENT_TOKEN'   # same name as the server setting
API_NEXT = '/api/tax-invoicing/signing-agent/next/'
API_RESULT = '/api/tax-invoicing/signing-agent/jobs/{id}/result/'
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
    from cryptography import x509 as cx509
    loaded = cx509.load_der_x509_certificate(der)
    parsed = ax509.Certificate.load(der)
    return TokenCertificate(
        der=der, key_id=key_id, label=label,
        thumbprint=hashlib.sha1(der, usedforsecurity=False).hexdigest().upper(),   # Windows thumbprint, an identifier
        subject=loaded.subject.rfc4514_string(), issuer=loaded.issuer.rfc4514_string(),
        serial=format(loaded.serial_number, 'X'), not_after=loaded.not_valid_after_utc,
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

    def __init__(self, base_url, agent_token, *, ca_bundle='', http=None, timeout=20):
        if not str(base_url).lower().startswith('https://'):
            raise ConfigError('[server] url must start with https://')
        if not agent_token:
            raise ConfigError(f'{ENV_AGENT_TOKEN} is not set')
        self.base_url = base_url.rstrip('/')
        self._headers = {'X-Tax-Agent-Token': agent_token}
        self.verify = ca_bundle or True
        self.timeout = timeout
        self.http = http or self._session()

    def __repr__(self):
        return f'<Server {self.base_url}>'

    @staticmethod
    def _session():
        import requests
        session = requests.Session()
        session.trust_env = False   # no proxy or .netrc from the machine's environment
        return session

    def _post(self, path, body):
        try:
            response = self.http.post(self.base_url + path, headers=self._headers, json=body, timeout=self.timeout,
                                      allow_redirects=False, verify=self.verify)
        except OSError as exc:      # requests' errors are OSError, TLS failures included
            raise ServerUnreachable(f'cannot reach the server: {type(exc).__name__}') from exc
        status = response.status_code
        if status in (401, 403):
            raise ServerRefused(f'the server refused the agent ({status}); check {ENV_AGENT_TOKEN} here and on the server')
        if 300 <= status < 400:
            raise ServerRefused(f'the server answered with a redirect ({status}); check [server] url')
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
                 result_attempts=6, retry_base_seconds=2):
        self.token, self.server, self.sleep = token, server, sleep
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
            server = Server(section.get('url', '').strip(),
                            read_secret(ENV_AGENT_TOKEN, 'Agent token', env=env, prompt=prompt),
                            ca_bundle=section.get('ca_bundle', '').strip(), http=http)
        pin = read_secret(ENV_PIN, 'Token PIN', env=env, prompt=prompt)
        token = Token(p11, module, label=label, thumbprint=token_section.get('thumbprint', ''),
                      allow_low_pin_count=args.allow_low_pin_count, pin=pin)
        if args.command == 'selftest':
            return self_test(token, out, count=max(1, args.count), pause_seconds=args.pause, sleep=sleep)
        agent = Agent(token, server, sleep=sleep, poll_seconds=float(agent_section.get('poll_seconds', '5') or 5))
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
