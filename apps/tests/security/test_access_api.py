"""
N1 / Task 4 — whoami («من أين أتصل؟»), the admin-only trusted-networks API and the seed command.
Log only: whoami just reports; nothing here refuses a request because of its network.
"""
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.access.models import TrustedNetwork
from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.tests.factories import make_branch, make_user

WHOAMI = '/api/access/whoami/'
LIST = '/api/access/networks/'
SITE_IP = '10.50.50.9'


@override_settings(NETWORK_HEADER_TRUSTED=True, ACCESS_NETWORKS_TTL=0, NUM_PROXIES=0)
class WhoamiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.branch = make_branch('فرع المعادي', 'W01')
        TrustedNetwork.objects.create(name='LAN المعادي', cidr='10.50.50.0/24',
                                      kind='branch_lan', branch=self.branch)

    def test_whoami_anonymous_internal_listed(self):
        r = APIClient().get(WHOAMI, HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual((d['zone'], d['ip']), ('internal', SITE_IP))
        self.assertEqual(d['label'], 'داخل الشبكة — LAN المعادي')
        self.assertEqual(d['site'], {'name': 'LAN المعادي', 'kind': 'branch_lan',
                                     'branch_label': 'فرع المعادي'})

    def test_whoami_internal_unlisted_has_no_site(self):
        d = APIClient().get(WHOAMI, HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR='172.16.0.4').json()
        self.assertEqual((d['zone'], d['site'], d['label']), ('internal', None, 'شبكة داخلية غير مسجلة'))

    def test_whoami_external_hides_site(self):
        # no header, trusted proxy -> external, even from an address that is on the list
        d = APIClient().get(WHOAMI, REMOTE_ADDR=SITE_IP).json()
        self.assertEqual((d['zone'], d['site'], d['label']), ('external', None, 'خارج الشبكة'))

    @override_settings(NETWORK_HEADER_TRUSTED=False, NETWORK_UNTRUSTED_ZONE='external')
    def test_whoami_ignores_client_header_when_untrusted(self):
        d = APIClient().get(WHOAMI, HTTP_X_ELR_NETWORK='internal', REMOTE_ADDR=SITE_IP).json()
        self.assertEqual((d['zone'], d['site']), ('external', None))

    def test_whoami_throttled(self):
        for _ in range(60):
            self.assertEqual(APIClient().get(WHOAMI, REMOTE_ADDR='10.9.9.9').status_code, 200)
        self.assertEqual(APIClient().get(WHOAMI, REMOTE_ADDR='10.9.9.9').status_code, 429)

    def test_whoami_open_to_any_role(self):
        _, _, viewer = make_user('wh_viewer', role='viewer')
        self.assertEqual(viewer.get(WHOAMI, HTTP_X_ELR_NETWORK='internal').status_code, 200)


@override_settings(ACCESS_NETWORKS_TTL=0)
class NetworksApiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.branch = make_branch('فرع المعادي', 'W01')
        _, self.admin, self.admin_c = make_user('na_admin', role='admin')
        _, _, self.pharm_c = make_user('na_pharm', role='pharmacist')

    def _body(self, **kw):
        return {'name': 'LAN المعادي', 'cidr': '192.168.3.0/24', 'kind': 'branch_lan',
                'branch': self.branch.pk, **kw}

    def test_networks_admin_only(self):
        self.assertEqual(self.pharm_c.get(LIST).status_code, 403)
        self.assertEqual(self.pharm_c.post(LIST, self._body(), format='json').status_code, 403)
        self.assertEqual(APIClient().get(LIST).status_code, 401)
        self.assertEqual(TrustedNetwork.objects.count(), 0)
        self.assertEqual(self.admin_c.get(LIST).status_code, 200)

    def test_network_crud_audited(self):
        r = self.admin_c.post(LIST, self._body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()['id']
        self.assertEqual(r.json()['branch_label'], 'فرع المعادي')
        r = self.admin_c.patch(f'{LIST}{pk}/', {'is_active': False, 'notes': 'مغلقة'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.admin_c.delete(f'{LIST}{pk}/').status_code, 204)
        logs = list(AuditLog.objects.filter(action='trusted_network_changed').order_by('id'))
        self.assertEqual(len(logs), 3)
        self.assertTrue(all(lg.user == self.admin for lg in logs))
        create, edit, delete = logs
        self.assertEqual(create.new_data['cidr'], '192.168.3.0/24')
        self.assertEqual(edit.old_data['is_active'], True)
        self.assertEqual(edit.new_data['is_active'], False)
        self.assertEqual(delete.old_data['name'], 'LAN المعادي')
        self.assertEqual([lg.extra['op'] for lg in logs], ['create', 'update', 'delete'])
        self.assertFalse(TrustedNetwork.objects.exists())

    def test_invalid_cidr_rejected(self):
        for bad in ('not-a-net', '192.168.3.0/99', '', '300.1.1.1/24'):
            r = self.admin_c.post(LIST, self._body(cidr=bad), format='json')
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('نطاق الشبكة غير صحيح', str(r.json()['cidr']), bad)
        self.assertEqual(TrustedNetwork.objects.count(), 0)

    def test_duplicate_cidr_rejected_in_arabic(self):
        self.assertEqual(self.admin_c.post(LIST, self._body(), format='json').status_code, 201)
        r = self.admin_c.post(LIST, self._body(name='نسخة', cidr='192.168.3.9/24'), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        msg = str(r.json()['cidr'])
        self.assertIn('مسجّل بالفعل', msg)
        self.assertIn('LAN المعادي', msg)
        self.assertEqual(TrustedNetwork.objects.count(), 1)

    def test_patch_same_cidr_on_self_allowed(self):
        pk = self.admin_c.post(LIST, self._body(), format='json').json()['id']
        r = self.admin_c.patch(f'{LIST}{pk}/', {'cidr': '192.168.3.0/24', 'notes': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_cidr_normalised_on_post(self):
        r = self.admin_c.post(LIST, self._body(cidr='192.168.3.7/24'), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(TrustedNetwork.objects.get().cidr, '192.168.3.0/24')

    def test_cidr_normalised_on_orm_create(self):
        tn = TrustedNetwork.objects.create(name='x', cidr=' 10.1.2.3/16 ', kind='server')
        self.assertEqual(tn.cidr, '10.1.0.0/16')

    def test_patch_cidr_normalised_and_validated(self):
        tn = TrustedNetwork.objects.create(name='x', cidr='10.1.0.0/16', kind='server')
        r = self.admin_c.patch(f'{LIST}{tn.pk}/', {'cidr': '10.2.3.4/24'}, format='json')
        self.assertEqual(r.status_code, 200)
        tn.refresh_from_db()
        self.assertEqual(tn.cidr, '10.2.3.0/24')
        self.assertEqual(self.admin_c.patch(f'{LIST}{tn.pk}/', {'cidr': 'zzz'}, format='json').status_code, 400)

    def test_updated_by_set(self):
        pk = self.admin_c.post(LIST, self._body(), format='json').json()['id']
        self.assertEqual(TrustedNetwork.objects.get(pk=pk).updated_by, self.admin)


class SeedCommandTests(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command('seed_trusted_networks', *args, stdout=out)
        return out.getvalue()

    def setUp(self):
        self.b1 = Branch.objects.create(softech_branch_id='101', name='A', name_ar='فرع أ', db_host='192.168.3.10')
        self.b2 = Branch.objects.create(softech_branch_id='102', name='B', name_ar='فرع ب', db_host='192.168.30.12')
        Branch.objects.create(softech_branch_id='103', name='C', db_host='10.0.0.5')   # not 192.168.x
        Branch.objects.create(softech_branch_id='104', name='D', db_host='')
        Branch.objects.create(softech_branch_id='110', name='X', db_host='192.168.110.5', kind='closed')

    def test_dry_run_writes_nothing(self):
        out = self._run()
        self.assertEqual(TrustedNetwork.objects.count(), 0)
        self.assertIn('192.168.3.0/24', out)

    def test_seed_from_branch_db_hosts(self):
        self._run('--apply')
        rows = {t.cidr: t for t in TrustedNetwork.objects.all()}
        self.assertEqual(set(rows), {'192.168.3.0/24', '192.168.30.0/24', '10.50.50.0/24'})
        self.assertEqual(rows['192.168.3.0/24'].branch, self.b1)
        self.assertEqual(rows['192.168.3.0/24'].kind, 'branch_lan')
        self.assertEqual(rows['192.168.3.0/24'].name, 'فرع أ')
        zt = rows['10.50.50.0/24']
        self.assertEqual((zt.kind, zt.name, zt.branch), ('staff_vpn', 'ZeroTier', None))
        self._run('--apply')
        self.assertEqual(TrustedNetwork.objects.count(), 3)

    def test_never_overwrites_existing_cidr(self):
        TrustedNetwork.objects.create(name='يدوي', cidr='192.168.3.0/24', kind='server', is_active=False)
        self._run('--apply')
        tn = TrustedNetwork.objects.get(cidr='192.168.3.0/24')
        self.assertEqual((tn.name, tn.kind, tn.is_active), ('يدوي', 'server', False))


@override_settings(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='', ACCESS_POLICY_TTL=0,
                   SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_POLICY_ENFORCEMENT='log')
class WhoamiSoftechTests(TestCase):
    """N4: whoami tells the banner the effective SOFTECH grant; it never writes an audit row."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _get(self, user, cookie=None):
        from rest_framework_simplejwt.tokens import AccessToken
        c = APIClient()
        if cookie:
            c.cookies['erp_device'] = cookie
        return c.get(WHOAMI, HTTP_X_ELR_NETWORK='internal',
                     HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}').json()

    def test_whoami_softech_access_read_in_z2(self):
        from apps.access.models import ZonePolicy
        user, _, _ = make_user('wh_sa_z2', role='pharmacist')
        ZonePolicy.objects.update_or_create(role='pharmacist', zone='Z2',
                                            defaults=dict(access='full', softech_read=True,
                                                          softech_write=False))
        before = AuditLog.objects.count()
        d = self._get(user)
        self.assertEqual((d['access_zone'], d['softech_access'], d['softech_gate_mode']),
                         ('Z2', 'read', 'enforce'))
        self.assertEqual(AuditLog.objects.count(), before)    # whoami never audits

    def test_whoami_softech_access_none_without_read(self):
        from apps.access.models import ZonePolicy
        user, _, _ = make_user('wh_sa_none', role='pharmacist')
        ZonePolicy.objects.update_or_create(role='pharmacist', zone='Z2',
                                            defaults=dict(access='full', softech_read=False,
                                                          softech_write=False))
        before = AuditLog.objects.count()
        self.assertEqual(self._get(user)['softech_access'], 'none')
        self.assertEqual(AuditLog.objects.count(), before)

    def test_whoami_softech_access_full_in_z1(self):
        from apps.access import devices
        from apps.access.models import Device, ZonePolicy
        user, _, _ = make_user('wh_sa_z1', role='pharmacist')
        secret = devices.new_secret()
        Device.objects.create(secret_hash=devices.hash_secret(secret), status='approved')
        ZonePolicy.objects.update_or_create(role='pharmacist', zone='Z1',
                                            defaults=dict(access='full', softech_read=True,
                                                          softech_write=True))
        d = self._get(user, cookie=secret)
        self.assertEqual((d['access_zone'], d['softech_access']), ('Z1', 'full'))

    @override_settings(SOFTECH_GATE_ENFORCEMENT='off')
    def test_whoami_softech_access_full_when_gate_off(self):
        user, _, _ = make_user('wh_sa_off', role='pharmacist')
        d = self._get(user)
        self.assertEqual((d['softech_access'], d['softech_gate_mode']), ('full', 'off'))

    def test_whoami_anonymous_has_softech_access_and_no_audit(self):
        before = AuditLog.objects.count()
        r = APIClient().get(WHOAMI, HTTP_X_ELR_NETWORK='internal')
        self.assertEqual(r.status_code, 200)
        self.assertIn('softech_access', r.json())
        self.assertEqual(AuditLog.objects.count(), before)
