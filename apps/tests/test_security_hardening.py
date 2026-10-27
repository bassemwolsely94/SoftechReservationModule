"""
apps/tests/test_security_hardening.py

Security hardening (deployment-readiness batch 1):
  - SOFTECH_READ_ONLY kill-switch: SQL classifier + java.sql proxy (covers the
    writers that bypass CursorWrapper via conn._conn) + _connect_with_retry wiring
  - SOFTECH_BRANCH_HOST_OVERRIDE
  - Loyalty manual point adjustment restricted to LOYALTY_ADJUST_ROLES
  - WhatsApp / Meta webhooks fail closed without the app secret; byte-safe compares
  - RBAC ModuleAccessMiddleware (off / log / enforce)
  - SECRET_KEY / ALLOWED_HOSTS production guards (subprocess, real settings import)
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from config import sybase
from config.sybase import (
    ConnectionWrapper, SoftechReadOnlyError, is_read_only_sql,
    _ReadOnlyJavaConnection, _branch_host, _connect_with_retry, _guard,
)
from core.middleware import module_access

from .factories import make_branch, make_user


# ── Fakes for the java.sql layer ──────────────────────────────────────────────

class FakeStatement:
    def __init__(self, log):
        self.log = log

    def execute(self, sql=None, *args):
        self.log.append(('execute', sql))
        return False

    def executeQuery(self, sql):
        self.log.append(('executeQuery', sql))

    def executeUpdate(self, sql, *args):
        self.log.append(('executeUpdate', sql))
        return 1

    def addBatch(self, sql):
        self.log.append(('addBatch', sql))

    def setQueryTimeout(self, secs):
        pass

    def setInt(self, *a):
        pass

    setString = setDouble = setObject = setInt

    def getResultSet(self):
        return None

    def close(self):
        pass


class FakeJavaConn:
    def __init__(self):
        self.log = []
        self.read_only = False

    def setReadOnly(self, flag):
        self.read_only = flag

    def createStatement(self, *args):
        return FakeStatement(self.log)

    def prepareStatement(self, sql, *args):
        self.log.append(('prepare', sql))
        return FakeStatement(self.log)

    def prepareCall(self, sql, *args):
        self.log.append(('prepareCall', sql))
        return FakeStatement(self.log)

    def setAutoCommit(self, flag):
        pass

    def commit(self):
        self.log.append(('commit', None))

    def rollback(self):
        pass

    def close(self):
        self.log.append(('close', None))


# ── SQL classifier ────────────────────────────────────────────────────────────

class ReadOnlySqlClassifierTests(SimpleTestCase):

    READS = [
        'SELECT 1',
        'select itemcode, itemname from SOFTECHDB9.dbo.items where itemcode = ?',
        '  (SELECT TOP 1 GETDATE())',
        'SET ROWCOUNT 50',
        'SET ROWCOUNT 0',
        "SELECT * FROM items WHERE itemname = 'DELETE ME; UPDATE x SET y=1'",
        'SELECT itemlastupdate, lastupdateuser FROM items',          # "update" inside identifiers
        '-- INSERT INTO x\nSELECT 1',
        '/* DROP TABLE items */ SELECT 1',
        'USE SOFTECHDB9',
        'DECLARE @x int SELECT @x = 1',
    ]
    WRITES = [
        'INSERT INTO SOFTECHDB9.dbo.picpoints (phcode) VALUES (?)',
        'UPDATE items SET posdiscp = 5 WHERE itemcode = ?',
        'update stkbal set salesrate = 1',
        'DELETE FROM stktrans5 WHERE docnumber = ?',
        'delete stktransm5 where docnumber = 1',
        'SELECT * INTO #tmp FROM items',
        'SELECT * INTO backup_items FROM items',
        'SELECT 1; DELETE FROM items',
        'SELECT 1\nUPDATE items SET x = 1',
        'EXEC sp_who',
        'execute sp_GetItemStock ?',
        'sp_who',
        'TRUNCATE TABLE items',
        'DROP TABLE items',
        'ALTER TABLE items ADD x int',
        'CREATE TABLE x (a int)',
        'DBCC SQLTEXT(1)',
        'BEGIN TRAN INSERT INTO x VALUES (1) COMMIT',
        'SELECT * FROM items FOR UPDATE',
        'WRITETEXT items.notes @p "x"',
        '',
        None,
        '   ',
    ]

    def test_reads_allowed(self):
        for sql in self.READS:
            with self.subTest(sql=sql):
                self.assertTrue(is_read_only_sql(sql))

    def test_writes_refused(self):
        for sql in self.WRITES:
            with self.subTest(sql=sql):
                self.assertFalse(is_read_only_sql(sql))


# ── java.sql proxy + wiring ───────────────────────────────────────────────────

class ReadOnlyConnectionProxyTests(SimpleTestCase):

    def setUp(self):
        self.raw = FakeJavaConn()
        self.conn = _ReadOnlyJavaConnection(self.raw)

    def test_sets_driver_read_only_hint(self):
        self.assertTrue(self.raw.read_only)

    def test_select_passes_through(self):
        self.conn.createStatement().execute('SELECT 1')
        self.assertIn(('execute', 'SELECT 1'), self.raw.log)

    def test_raw_statement_writes_blocked(self):
        # The invoice / ISR writers use conn._conn.createStatement() directly.
        stmt = self.conn.createStatement()
        for call in (stmt.execute, stmt.executeUpdate, stmt.addBatch):
            with self.subTest(call=call.__name__):
                with self.assertRaises(SoftechReadOnlyError):
                    call('INSERT INTO stktrans5 VALUES (1)')
        self.assertEqual(self.raw.log, [])

    def test_prepared_write_blocked_before_reaching_driver(self):
        with self.assertRaises(SoftechReadOnlyError):
            self.conn.prepareStatement('UPDATE items SET x = ? WHERE itemcode = ?')
        self.assertEqual(self.raw.log, [])

    def test_callable_statements_always_blocked(self):
        with self.assertRaises(SoftechReadOnlyError):
            self.conn.prepareCall('{call sp_GetItemStock(?)}')

    def test_cursor_wrapper_path_blocked(self):
        cur = ConnectionWrapper(self.conn).cursor()
        with self.assertRaises(SoftechReadOnlyError):
            cur.execute('DELETE FROM picpoints WHERE phcode = ?', ['1'])
        with self.assertRaises(SoftechReadOnlyError):
            cur.execute('UPDATE items SET x = 1')
        cur.execute('SELECT 1')
        cur.execute('SELECT phcode FROM localcustomers WHERE phcode = ?', ['1'])
        self.assertEqual([op for op, _ in self.raw.log], ['execute', 'prepare', 'execute'])

    def test_other_attributes_delegate(self):
        self.conn.close()
        self.assertIn(('close', None), self.raw.log)


class GuardWiringTests(SimpleTestCase):

    @override_settings(SOFTECH_READ_ONLY=False)
    def test_guard_is_transparent_when_off(self):
        raw = FakeJavaConn()
        self.assertIs(_guard(raw), raw)

    @override_settings(SOFTECH_READ_ONLY=True)
    def test_guard_wraps_when_on(self):
        self.assertIsInstance(_guard(FakeJavaConn()), _ReadOnlyJavaConnection)

    @override_settings(SOFTECH_READ_ONLY=True)
    def test_every_connection_goes_through_guard(self):
        # get_sybase_connection / get_branch_connection / SoftechConnector all
        # obtain their java connection from _connect_with_retry.
        driver = mock.Mock()
        driver.connect.return_value = FakeJavaConn()
        conn = _connect_with_retry(driver, 'jdbc:sybase:Tds:h:5000/SOFTECHDB9', None)
        with self.assertRaises(SoftechReadOnlyError):
            ConnectionWrapper(conn).cursor().execute('INSERT INTO picpoints VALUES (1)')

    def test_all_connect_paths_use_connect_with_retry(self):
        src = Path(sybase.__file__).read_text(encoding='utf-8')
        # Only probe_connection may call driver.connect directly (it runs SELECT 1).
        direct = [l for l in src.splitlines()
                  if '.connect(jdbc_url' in l and '_connect_with_retry' not in l
                  and 'return _guard(' not in l]
        self.assertEqual(len(direct), 1, direct)
        self.assertIn('SybDriver().connect', direct[0])


class BranchHostOverrideTests(SimpleTestCase):

    @override_settings(SOFTECH_BRANCH_HOST_OVERRIDE='')
    def test_no_override(self):
        self.assertEqual(_branch_host('10.0.0.5', 5000), ('10.0.0.5', 5000))

    @override_settings(SOFTECH_BRANCH_HOST_OVERRIDE='test-ase')
    def test_host_only(self):
        self.assertEqual(_branch_host('10.0.0.5', 5001), ('test-ase', 5001))

    @override_settings(SOFTECH_BRANCH_HOST_OVERRIDE='test-ase:6000')
    def test_host_and_port(self):
        self.assertEqual(_branch_host('10.0.0.5', 5000), ('test-ase', 6000))


# ── Loyalty manual adjustment ────────────────────────────────────────────────

class LoyaltyAdjustPermissionTests(TestCase):

    def setUp(self):
        from apps.customers.models import Customer
        self.branch = make_branch()
        self.customer = Customer.objects.create(name='عميل', phone='01000000001', softech_pic='P1')
        self.url = f'/api/loyalty/customers/{self.customer.pk}/adjust/'

    def _post(self, role, adjust_type='referral'):
        _, _, client = make_user(f'loy_{role}', role=role, branch=self.branch)
        return client.post(self.url, {'points': 10, 'reason': 'test', 'adjust_type': adjust_type},
                           format='json')

    def test_roles_outside_allow_list_refused(self):
        for role in ('viewer', 'salesperson', 'pharmacist', 'delivery', 'purchasing', 'quality_manager'):
            with self.subTest(role=role):
                self.assertEqual(self._post(role).status_code, 403)

    @mock.patch('apps.loyalty.pic_bridge.adjust_softech_points')
    def test_softech_write_never_reached_by_refused_role(self, adjust):
        self.assertEqual(self._post('viewer', adjust_type='purchase').status_code, 403)
        adjust.assert_not_called()

    def test_allowed_roles_can_adjust_referral_points(self):
        for role in ('call_center', 'supervisor', 'admin'):
            with self.subTest(role=role):
                self.assertEqual(self._post(role).status_code, 200)

    @override_settings(LOYALTY_ADJUST_ROLES=frozenset({'pharmacist'}))
    def test_roles_configurable(self):
        self.assertEqual(self._post('pharmacist').status_code, 200)
        self.assertEqual(self._post('call_center').status_code, 403)


# ── Webhooks ──────────────────────────────────────────────────────────────────

def _sig(secret, body):
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookSignatureTests(TestCase):
    BODY = json.dumps({'object': 'whatsapp_business_account', 'entry': []}).encode()

    def setUp(self):
        self.client = APIClient()

    def _wa(self, sig=None):
        extra = {'HTTP_X_HUB_SIGNATURE_256': sig} if sig is not None else {}
        return self.client.post('/api/whatsapp/webhook/', self.BODY,
                                content_type='application/json', **extra)

    def _meta(self, sig=None):
        extra = {'HTTP_X_HUB_SIGNATURE_256': sig} if sig is not None else {}
        return self.client.post('/api/social/webhook/meta/', self.BODY,
                                content_type='application/json', **extra)

    @override_settings(WHATSAPP_APP_SECRET='', DEBUG=False)
    def test_whatsapp_rejects_unsigned_when_secret_missing(self):
        self.assertEqual(self._wa().status_code, 403)

    @override_settings(WHATSAPP_APP_SECRET='s3cret')
    def test_whatsapp_signature_checks(self):
        self.assertEqual(self._wa().status_code, 403)
        self.assertEqual(self._wa('sha256=deadbeef').status_code, 403)
        self.assertEqual(self._wa('sha256=ﻻﻻﻻ').status_code, 403)       # non-ASCII → 403, not 500
        with mock.patch('apps.whatsapp.views.process_webhook'):
            self.assertEqual(self._wa(_sig('s3cret', self.BODY)).status_code, 200)

    @override_settings(META_GRAPH_APP_SECRET='', DEBUG=False)
    def test_meta_rejects_unsigned_when_secret_missing(self):
        self.assertEqual(self._meta().status_code, 403)

    @override_settings(META_GRAPH_APP_SECRET='s3cret')
    def test_meta_signature_checks(self):
        self.assertEqual(self._meta('sha256=deadbeef').status_code, 403)
        self.assertEqual(self._meta('sha256=ﻻﻻﻻ').status_code, 403)
        with mock.patch('apps.social.views.process_meta_webhook'):
            self.assertEqual(self._meta(_sig('s3cret', self.BODY)).status_code, 200)

    @override_settings(WHATSAPP_VERIFY_TOKEN='', META_GRAPH_VERIFY_TOKEN='')
    def test_verify_handshake_needs_configured_token(self):
        for url in ('/api/whatsapp/webhook/', '/api/social/webhook/meta/'):
            with self.subTest(url=url):
                r = self.client.get(url, {'hub.mode': 'subscribe', 'hub.verify_token': '',
                                          'hub.challenge': '123'})
                self.assertEqual(r.status_code, 403)

    @override_settings(WHATSAPP_VERIFY_TOKEN='tok', META_GRAPH_VERIFY_TOKEN='tok')
    def test_verify_handshake(self):
        for url in ('/api/whatsapp/webhook/', '/api/social/webhook/meta/'):
            with self.subTest(url=url):
                ok = self.client.get(url, {'hub.mode': 'subscribe', 'hub.verify_token': 'tok',
                                           'hub.challenge': '123'})
                self.assertEqual((ok.status_code, ok.content), (200, b'123'))
                bad = self.client.get(url, {'hub.mode': 'subscribe', 'hub.verify_token': 'ﻻ',
                                            'hub.challenge': '123'})
                self.assertEqual(bad.status_code, 403)


# ── RBAC middleware ───────────────────────────────────────────────────────────

class ModuleAccessMappingTests(SimpleTestCase):

    def test_mapping(self):
        r = module_access.required
        self.assertEqual(r('/api/finance/summary/', 'GET'), ('finance', ('view',)))
        self.assertEqual(r('/api/pos-orders/5/', 'PATCH'), ('pos', ('edit',)))
        self.assertEqual(r('/api/transits/1/', 'DELETE'), ('transfers', ('delete',)))
        self.assertEqual(r('/api/insurance/claims/', 'POST')[0], 'insurance')
        self.assertIn('approve', r('/api/approvals/1/decide/', 'POST')[1])

    def test_unchecked_paths(self):
        r = module_access.required
        for path in ('/api/auth/login/', '/api/notifications/', '/api/portal/me/',
                     '/api/social/webhook/meta/', '/api/personal/', '/api/search/',
                     '/admin/', '/media/x.png', '/api/unknown-module/'):
            with self.subTest(path=path):
                self.assertIsNone(r(path, 'POST'))

    def test_read_open_prefixes(self):
        r = module_access.required
        self.assertIsNone(r('/api/items/', 'GET'))
        self.assertIsNone(r('/api/branches/', 'GET'))
        self.assertEqual(r('/api/config/theme/', 'PUT'), ('settings', ('edit',)))

    def test_every_mapped_module_exists_in_matrix(self):
        from apps.users.models import MODULE_CHOICES
        valid = {m for m, _ in MODULE_CHOICES}
        mapped = set(module_access.MODULE_BY_PREFIX.values()) | set(module_access.READ_OPEN_PREFIXES.values())
        self.assertEqual(mapped - valid, set())


class ModuleAccessMiddlewareTests(TestCase):
    URL = '/api/sync/logs/'

    def setUp(self):
        from apps.users.models import RoleModuleAccess
        module_access.clear_cache()
        self.branch = make_branch()
        # Seed one unrelated grant so the matrix counts as "seeded".
        RoleModuleAccess.objects.create(role='pharmacist', module='reservations', action='view')

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        user, _, _ = make_user(f'rbac_{role}', role=role, branch=self.branch)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        return c

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_enforce_blocks_role_without_grant(self):
        r = self._client('viewer').get(self.URL)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['module'], 'sync')

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_enforce_allows_granted_role(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='viewer', module='sync', action='view')
        module_access.clear_cache()
        self.assertNotEqual(self._client('viewer').get(self.URL).status_code, 403)

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_admin_bypasses_matrix(self):
        r = self._client('admin').get('/api/sync/status/')
        self.assertNotEqual(r.status_code, 403)

    @override_settings(RBAC_ENFORCEMENT='log')
    def test_log_mode_never_blocks(self):
        with self.assertLogs('elrezeiky.rbac', level='WARNING') as logs:
            r = self._client('viewer').get('/api/sync/status/')
        self.assertNotEqual(r.status_code, 403)
        self.assertIn('would-deny', logs.output[0])

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_enforce_with_empty_matrix_does_not_lock_out(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        r = self._client('viewer').get('/api/sync/status/')
        self.assertNotEqual(r.status_code, 403)

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_anonymous_left_to_views(self):
        self.assertEqual(APIClient().get('/api/sync/status/').status_code, 401)

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_post_needs_a_write_grant(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='viewer', module='sync', action='view')
        module_access.clear_cache()
        r = self._client('viewer').post('/api/sync/trigger/', {}, format='json')
        self.assertEqual(r.status_code, 403)


# ── Production settings guards (real import in a subprocess) ──────────────────

class ProductionSettingsGuardTests(SimpleTestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def _import_settings(self, **env):
        base = {k: v for k, v in os.environ.items()
                if k not in ('SECRET_KEY', 'DEBUG', 'ALLOWED_HOSTS')}
        base.update(env)
        code = 'import config.settings as s; print(s.ALLOWED_HOSTS)'
        return subprocess.run([sys.executable, '-c', code], cwd=self.ROOT, env=base,
                              capture_output=True, text=True, timeout=120)

    def test_production_refuses_missing_secret_key(self):
        r = self._import_settings(DEBUG='False', SECRET_KEY='')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('SECRET_KEY is missing', r.stderr)

    def test_production_refuses_placeholder_secret_key(self):
        r = self._import_settings(DEBUG='False', SECRET_KEY='change-me-in-production')
        self.assertNotEqual(r.returncode, 0)

    def test_production_allowed_hosts_not_wildcard(self):
        r = self._import_settings(DEBUG='False', SECRET_KEY='x' * 50)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("'*'", r.stdout)

    def test_debug_still_boots_without_key(self):
        r = self._import_settings(DEBUG='True', SECRET_KEY='')
        self.assertEqual(r.returncode, 0, r.stderr)
