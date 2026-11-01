"""N2 / Task 5 - admin device API: approve / block / retire / bulk, audited."""
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access import devices
from apps.access.models import Device, DeviceUser
from apps.audit.models import AuditLog
from apps.tests.factories import make_admin, make_branch, make_user
from apps.users.models import UserActivityLog

LIST = '/api/access/devices/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'


def _dev(name='جهاز', **kw):
    return Device.objects.create(secret_hash=devices.hash_secret(devices.new_secret()), name=name, **kw)


def _rows(resp):
    data = resp.json()
    return data['results'] if isinstance(data, dict) else data


class DeviceApiBase(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin_user, self.admin, self.api = make_admin('dv_admin')


class AccessTests(DeviceApiBase):

    def test_devices_admin_only(self):
        d = _dev()
        for role in ('pharmacist', 'supervisor', 'delivery'):
            _, _, c = make_user(f'dv_{role}', role=role)
            self.assertEqual(c.get(LIST).status_code, 403, role)
            self.assertEqual(c.get(f'{LIST}{d.pk}/').status_code, 403, role)
            self.assertEqual(c.patch(f'{LIST}{d.pk}/', {'name': 'x'}, format='json').status_code, 403, role)
            for act in ('approve', 'block', 'retire'):
                r = c.post(f'{LIST}{d.pk}/{act}/', {'note': 'x'}, format='json')
                self.assertEqual(r.status_code, 403, (role, act))
            self.assertEqual(c.post(f'{LIST}bulk-approve/', {'ids': [d.pk]}, format='json').status_code, 403)
        d.refresh_from_db()
        self.assertEqual(d.status, 'pending')
        self.assertEqual(APIClient().get(LIST).status_code, 401)

    def test_no_delete_no_create(self):
        d = _dev()
        self.assertEqual(self.api.delete(f'{LIST}{d.pk}/').status_code, 405)
        self.assertEqual(self.api.post(LIST, {'name': 'x'}, format='json').status_code, 405)
        self.assertTrue(Device.objects.filter(pk=d.pk).exists())


class ListTests(DeviceApiBase):

    def test_pending_listed_first(self):
        _dev('a', status='approved')
        _dev('b', status='blocked')
        p = _dev('p', status='pending')
        _dev('r', status='retired')
        rows = _rows(self.api.get(LIST))
        self.assertEqual(rows[0]['id'], p.pk)
        self.assertEqual(rows[0]['status_label'], 'بانتظار الاعتماد')
        self.assertEqual(rows[0]['kind_label'], 'لابتوب شخصي')

    def test_filter_status_and_search(self):
        br = make_branch('فرع المعادي', 'D01')
        a = _dev('Chrome Windows — Ahmed', status='approved', kind='branch_pc', branch=br,
                 last_ip='10.1.2.3')
        b = _dev('Safari iPhone', status='pending', kind='phone')
        _, prof, _ = make_user('dv_sara', role='pharmacist')
        DeviceUser.objects.create(device=b, user=prof)

        def ids(qs):
            return {x['id'] for x in _rows(self.api.get(LIST + qs))}
        self.assertEqual(ids('?status=approved'), {a.pk})
        self.assertEqual(ids('?kind=phone'), {b.pk})
        self.assertEqual(ids(f'?branch={br.pk}'), {a.pk})
        self.assertEqual(ids('?q=ahmed'), {a.pk})
        self.assertEqual(ids('?q=zzz*'), set())
        self.assertEqual(ids('?q=saf*iph'), {b.pk})
        self.assertEqual(ids('?q=10.1.2'), {a.pk})
        self.assertEqual(ids('?q=dv_sara'), {b.pk})

    def test_users_listed_without_n_plus_one(self):
        now = timezone.now()
        for i in range(6):
            d = _dev(f'd{i}')
            for j in range(3):
                _, prof, _ = make_user(f'dv_u{i}_{j}', role='pharmacist')
                DeviceUser.objects.create(device=d, user=prof, last_seen=now,
                                          mfa_remembered_at=now - timedelta(days=(40 if j == 0 else 5)))
        with CaptureQueriesContext(connection) as ctx:
            r = self.api.get(LIST)
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(ctx), 12)       # bounded, not per row (6 devices x 3 users)
        users = _rows(r)[0]['users']
        self.assertEqual(len(users), 3)
        self.assertEqual({'id', 'name', 'role', 'last_seen', 'mfa_remembered'}, set(users[0]))
        self.assertEqual(sorted(u['mfa_remembered'] for u in users), [False, True, True])


class ActionTests(DeviceApiBase):

    def test_approve_audited_before_after(self):
        _, owner, _ = make_user('dv_owner')
        d = _dev(owner=owner)
        r = self.api.post(f'{LIST}{d.pk}/approve/', {'note': 'جهاز الفرع'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'approved')
        d.refresh_from_db()
        self.assertEqual((d.status, d.approved_by, d.status_note), ('approved', self.admin, 'جهاز الفرع'))
        self.assertIsNotNone(d.approved_at)
        log = AuditLog.objects.filter(action='device_changed').latest('id')
        self.assertEqual(log.user_name, self.admin.full_name)
        self.assertEqual(log.changes['before']['status'], 'pending')
        self.assertEqual(log.changes['after']['status'], 'approved')
        act = UserActivityLog.objects.get(action='device_status')
        self.assertEqual((act.target_user, act.changed_by, act.device), (owner, self.admin, d))
        self.assertEqual(act.old_value, 'pending')
        self.assertEqual(act.new_value, 'approved')

    def test_block_requires_note(self):
        d = _dev(status='approved')
        for body in ({}, {'note': ''}, {'note': '   '}):
            r = self.api.post(f'{LIST}{d.pk}/block/', body, format='json')
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json(), {'error': 'اكتب سبب الحظر'})
        d.refresh_from_db()
        self.assertEqual(d.status, 'approved')
        r = self.api.post(f'{LIST}{d.pk}/block/', {'note': 'ضاع الجهاز'}, format='json')
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        self.assertEqual((d.status, d.status_note), ('blocked', 'ضاع الجهاز'))

    def test_retire_and_unblock_audited(self):
        d = _dev(status='blocked')
        self.assertEqual(self.api.post(f'{LIST}{d.pk}/approve/', {}, format='json').status_code, 200)
        self.assertEqual(self.api.post(f'{LIST}{d.pk}/retire/', {}, format='json').status_code, 200)
        d.refresh_from_db()
        self.assertEqual(d.status, 'retired')
        self.assertEqual(AuditLog.objects.filter(action='device_changed').count(), 2)

    def test_block_then_token_refused(self):
        make_user('dv_victim')
        victim = APIClient()
        r = victim.post('/api/auth/login/', {'username': 'dv_victim', 'password': 'TestPass123'},
                        format='json', HTTP_USER_AGENT=UA)
        self.assertEqual(r.status_code, 200)
        dev = Device.objects.get()
        self.assertEqual(victim.get('/api/auth/me/').status_code, 200)
        r = self.api.post(f'{LIST}{dev.pk}/block/', {'note': 'مسروق'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(victim.get('/api/auth/me/').status_code, 401)
        self.api.post(f'{LIST}{dev.pk}/approve/', {}, format='json')
        self.assertEqual(victim.get('/api/auth/me/').status_code, 200)

    def test_bulk_approve_only_pending(self):
        p1, p2 = _dev('p1'), _dev('p2')
        blk = _dev('b', status='blocked')
        r = self.api.post(f'{LIST}bulk-approve/', {'ids': [p1.pk, p2.pk, blk.pk, 999999]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'approved': 2, 'skipped': 2})
        blk.refresh_from_db()
        self.assertEqual(blk.status, 'blocked')
        self.assertEqual(AuditLog.objects.filter(action='device_changed').count(), 2)
        self.assertEqual(self.api.post(f'{LIST}bulk-approve/', {'ids': 'x'}, format='json').status_code, 400)

    def test_patch_kind_branch_audited(self):
        br = make_branch('فرع', 'D02')
        d = _dev(kind='personal_laptop')
        r = self.api.patch(f'{LIST}{d.pk}/', {'kind': 'branch_pc', 'branch': br.pk, 'name': 'كاشير 1',
                                              'allowed_roles': ['pharmacist']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d.refresh_from_db()
        self.assertEqual((d.kind, d.branch, d.name, d.allowed_roles, d.updated_by),
                         ('branch_pc', br, 'كاشير 1', ['pharmacist'], self.admin))
        log = AuditLog.objects.filter(action='device_changed').latest('id')
        self.assertEqual(log.changes['before']['kind'], 'personal_laptop')
        self.assertEqual(log.changes['after']['kind'], 'branch_pc')
        self.assertEqual(log.changes['after']['branch'], br.pk)
        self.api.patch(f'{LIST}{d.pk}/', {'status': 'approved'}, format='json')   # status is read-only
        d.refresh_from_db()
        self.assertEqual(d.status, 'pending')
