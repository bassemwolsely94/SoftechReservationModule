"""
apps/tests/security/test_privacy_logs.py — round 2, R4 step 5: what logs and error answers carry.

A customer of branch A is planted with a known phone number and a known PIC on every record the
canary planter can reach (as the phone sweep does). SOFTECH is "down" in a way that hurts: every
connection attempt raises an error whose text carries a SOFTECH connection string, the database
password and a token — the worst a driver could echo. Then every protected route is called
(GET, and POST {} to reach the error paths) by a branch-B pharmacist, an own-branch pharmacist who
may not see phones, and admin, while EVERY log record (all loggers, INFO and up) is captured.

Checks:
  • no log record carries the planted number unmasked, the PIC, the password, the fake token or
    a live access token of the callers;
  • no answer to a non-admin carries the connection string, the password or the token — which
    covers every public_error() answer and any view that echoes str(exc);
  • no answer to admin carries the password or the token (public_error shows admin the error
    text, so a secret inside it must be redacted first).

Exceptions are listed with a reason in baselines/privacy_log_leaks.txt (the usual ratchet).
"""
import logging
import re

from django.db import transaction
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .baseline import assert_matches_baseline
from .canary import Planter
from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire, handles
from .sweep import FEATURE_FLAGS_ON, SWEEP_ID, protected_routes

NUMBER = '01093847562'
NUMBER_TOKEN = '93847'                # middle digits: mask() keeps only the last 3
INTL_TOKEN = '2010938475'             # the same number written +20…
PIC = 'PRV77QX91'
SECRET_PW = 'Zq7-sybase-pw-Kx2'
FAKE_HOST = '10.77.66.55'
FAKE_TOKEN = 'tok_9f8e7d6c5b4a3210'
SOFTECH_ERROR = (f'JZ006: Caught IOException: java.net.ConnectException jdbc:sybase:Tds:{FAKE_HOST}:5000'
                 f'/SOFTECHDB9 user=sa password={SECRET_PW} api_key={FAKE_TOKEN}')

LOG_SECRETS = {'phone': NUMBER_TOKEN, 'phone+20': INTL_TOKEN, 'pic': PIC, 'password': SECRET_PW,
               'token': FAKE_TOKEN}
ANSWER_SECRETS_STAFF = {'connection string': f'jdbc:sybase:Tds:{FAKE_HOST}', 'host': FAKE_HOST,
                        'password': SECRET_PW, 'token': FAKE_TOKEN}
ANSWER_SECRETS_ADMIN = {'password': SECRET_PW, 'token': FAKE_TOKEN}
_JWT = re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.')


class LeakyTripwire(Tripwire):
    """The usual Tripwire, but a SOFTECH connection fails with a message full of secrets."""

    def _softech(self, name):
        def boom(*a, **k):
            self.softech_calls.append(name)
            raise ConnectionError(SOFTECH_ERROR)
        return boom


class LogScanner(logging.Handler):
    """Collects every record of every logger (root + loggers that don't propagate) while active."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.hits = set()
        self._saved = []

    def emit(self, record):
        try:
            text = record.getMessage()
        except Exception:          # noqa: BLE001 — a bad format string is not our finding
            text = str(record.msg)
        if record.exc_info:
            text += ' ' + logging.Formatter().formatException(record.exc_info)
        for what, needle in LOG_SECRETS.items():
            if needle in text:
                self.hits.add(f'{what} {record.name}')
        if _JWT.search(text):
            self.hits.add(f'jwt {record.name}')

    def __enter__(self):
        loggers = [logging.getLogger()] + [lg for lg in logging.root.manager.loggerDict.values()
                                           if isinstance(lg, logging.Logger) and lg.handlers]
        for lg in loggers:
            self._saved.append((lg, lg.handlers[:], lg.level))
            lg.handlers = [self]
            if lg.level == logging.NOTSET or lg.level > logging.INFO:
                lg.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        for lg, handlers, level in self._saved:
            lg.handlers = handlers
            lg.setLevel(level)


def _call(client, method, path):
    try:
        with transaction.atomic():
            if method == 'GET':
                r = client.get(path)
            else:
                r = client.post(path, {}, format='json')
            transaction.set_rollback(True)
        ctype = r.get('Content-Type', '')
        if 'json' not in ctype and not ctype.startswith('text/'):
            return r.status_code, ''
        return r.status_code, r.content.decode('utf-8', 'replace')
    except Exception as exc:          # noqa: BLE001 — a crash is the role sweep's business
        return f'raised {type(exc).__name__}', ''


@override_settings(RBAC_ENFORCEMENT='enforce', SYBASE_PASSWORD=SECRET_PW, **FEATURE_FLAGS_ON)
class PrivacyLogSweepTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role='pharmacist').update(is_allowed=True)
        module_access.clear_cache()
        a = make_branch('Privacy A', softech_id='PVA')
        b = make_branch('Privacy B', softech_id='PVB')
        user_a, prof_a, _ = make_user('pv_a', role='pharmacist', branch=a)
        prof_a.can_see_customer_phone = False
        prof_a.save(update_fields=['can_see_customer_phone'])
        user_b, _, _ = make_user('pv_b', role='pharmacist', branch=b)
        admin, _, _ = make_user('pv_admin', role='admin', branch=b, access_all=True)
        staff = {'other_branch': bearer_client(user_b), 'no_phone_flag': bearer_client(user_a)}
        adm = bearer_client(admin)
        cls.log_hits, cls.answer_hits, cls.calls, cls.softech_errors = set(), set(), 0, 0
        with LeakyTripwire() as tw:
            previous = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                cls.planter = Planter(a, user_a, prof_a, phone=NUMBER).plant_phones()
                if cls.planter.customer is not None:
                    type(cls.planter.customer).objects.filter(pk=cls.planter.customer.pk).update(softech_pic=PIC)
            finally:
                logging.disable(previous)
            routes = sorted(p for p in protected_routes() if SWEEP_ID not in p)
            with LogScanner() as scan:
                for path in routes:
                    for method in ('GET', 'POST'):
                        if not handles(path, method):
                            continue
                        for who, client in (('admin', adm), *staff.items()):
                            code, body = _call(client, method, path)
                            cls.calls += 1
                            secrets = ANSWER_SECRETS_ADMIN if who == 'admin' else ANSWER_SECRETS_STAFF
                            for what, needle in secrets.items():
                                if needle in body:
                                    cls.answer_hits.add(f'{what} {who} {method} {path}')
            cls.log_hits = scan.hits
            cls.softech_errors = len(tw.softech_calls)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()

    def test_the_sweep_ran_and_softech_failed_loudly(self):
        self.assertGreater(self.calls, 2000)
        self.assertIsNotNone(self.planter.customer)
        self.assertGreater(self.softech_errors, 10)     # the leaky error was really raised

    def test_logs_carry_no_phone_pic_password_or_token(self):
        assert_matches_baseline(self, 'privacy_log_leaks', self.log_hits)

    def test_answers_carry_no_connection_string_password_or_token(self):
        assert_matches_baseline(self, 'privacy_answer_leaks', self.answer_hits)


class PublicErrorTests(TestCase):
    """core.errors.public_error — the one helper error answers go through."""

    def _req(self, role):
        from rest_framework.test import APIRequestFactory
        user, _, _ = make_user(f'pe_{role}', role=role, branch=make_branch())
        req = APIRequestFactory().get('/api/x/')
        req.user = user
        return req

    def test_staff_get_only_a_reference(self):
        from core.errors import public_error
        with self.assertLogs('elrezeiky', level='ERROR'):
            out = public_error(self._req('pharmacist'), ConnectionError(SOFTECH_ERROR + f' {NUMBER} {PIC}'))
        for needle in (FAKE_HOST, SECRET_PW, FAKE_TOKEN, NUMBER, PIC):
            self.assertNotIn(needle, out)
        self.assertIn('مرجع', out)

    @override_settings(SYBASE_PASSWORD=SECRET_PW)
    def test_admin_detail_and_the_log_redact_secrets(self):
        from core.errors import public_error
        with self.assertLogs('elrezeiky', level='ERROR') as logs:
            out = public_error(self._req('admin'), ConnectionError(SOFTECH_ERROR))
        for needle in (SECRET_PW, FAKE_TOKEN):
            self.assertNotIn(needle, out)
            self.assertNotIn(needle, '\n'.join(logs.output))
