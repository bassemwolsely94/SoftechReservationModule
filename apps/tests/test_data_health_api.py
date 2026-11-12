"""
Data lifecycle Stage 5, Task 2: the /api/data-health/ API and the `data_health` RBAC module.

Who may see what (design §7): admin everything; supervisor and quality manager Growth, Problems and the
forced refresh; nobody else anything. Rules, preview, held files, thumbnails and restore are admin only.
Held files never show their paths or hash; prescriptions never get a thumbnail.
"""
import datetime
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.data_lifecycle import holding, problems, reports, views
from apps.data_lifecycle.models import (DataHealthSnapshot, HeldFile, LifecycleRulePolicy, LifecycleRunLine,
                                        TableSizeSnapshot)
from apps.data_lifecycle.policy import AUDIT_ACTION
from apps.sync.models import SyncRun
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

from .factories import (make_admin, make_customer, make_pharmacist, make_quality_manager, make_salesperson,
                        make_supervisor, make_viewer)

API = '/api/data-health/'
ROLE_TABLE = {
    # role: (growth, problems, rules, held)
    'admin': (200, 200, 200, 200),
    'supervisor': (200, 200, 403, 403),
    'quality_manager': (200, 200, 403, 403),
    'pharmacist': (403, 403, 403, 403),
    'salesperson': (403, 403, 403, 403),
    'viewer': (403, 403, 403, 403),
}


def _jpeg_bytes():
    out = io.BytesIO()
    Image.new('RGB', (400, 300), (10, 120, 200)).save(out, 'JPEG')
    return out.getvalue()


def _snapshot(days_ago, db, media=0, total=10_000, free=5_000, **extra):
    day = timezone.localdate() - datetime.timedelta(days=days_ago)
    return DataHealthSnapshot.objects.create(day=day, db_bytes=db, media_bytes=media, disk_total_bytes=total,
                                             disk_free_bytes=free, **extra)


class _ApiCase(TestCase):
    def setUp(self):
        seed_code_matrix()
        self.addCleanup(module_access.clear_cache)
        cache.delete(views.REFRESH_KEY)
        self.addCleanup(cache.delete, views.REFRESH_KEY)
        self.admin_user, self.admin, _ = make_admin('dh_admin')
        self.client = bearer_client(self.admin_user)


class RoleSweepTests(_ApiCase):
    def _clients(self):
        users = {
            'admin': self.admin_user,
            'supervisor': make_supervisor('dh_sup')[0],
            'quality_manager': make_quality_manager('dh_qm')[0],
            'pharmacist': make_pharmacist('dh_ph')[0],
            'salesperson': make_salesperson('dh_sales')[0],
            'viewer': make_viewer('dh_viewer')[0],
        }
        return {role: bearer_client(user) for role, user in users.items()}

    def test_role_table(self):
        for role, client in self._clients().items():
            got = tuple(client.get(API + p).status_code for p in ('growth/', 'problems/', 'rules/', 'held/'))
            self.assertEqual(got, ROLE_TABLE[role], role)

    def test_admin_actions_refused_for_supervisor_and_quality_manager(self):
        held = HeldFile.objects.create(original_path='images/a.jpg', hold_path='a.jpg', rule_key='images_rejected',
                                       sha256='0' * 64, purge_after=timezone.now(),
                                       primary_model='images.ImageCandidate', primary_pk='1',
                                       primary_field='local_file')
        clients = self._clients()
        for role in ('supervisor', 'quality_manager'):
            c = clients[role]
            self.assertEqual(c.patch(API + 'rules/transit_alert_notes/', {'keep_days': 120, 'reason': 'x'},
                                     format='json').status_code, 403, role)
            self.assertEqual(c.post(API + 'rules/transit_alert_notes/preview/').status_code, 403, role)
            self.assertEqual(c.post(f'{API}held/{held.pk}/restore/').status_code, 403, role)
            self.assertEqual(c.get(f'{API}held/{held.pk}/thumbnail/').status_code, 403, role)
        self.assertFalse(LifecycleRulePolicy.objects.exists())
        self.assertFalse(LifecycleRunLine.objects.exists())

    def test_code_matrix_and_migration_agree(self):
        import importlib
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        from apps.users.models import ROLE_CHOICES
        mig = importlib.import_module('apps.users.migrations.0054_data_health_module')
        holders = {r: a for r, mods in PERMISSIONS.items() if (a := mods.get('data_health'))}
        self.assertEqual({r: a for r, a in holders.items() if r != 'admin'},
                         {'supervisor': {'view'}, 'quality_manager': {'view'}})
        self.assertEqual({r: a for r, a in mig.GRANTS.items() if r != 'admin'},
                         {'supervisor': {'view'}, 'quality_manager': {'view'}})
        self.assertEqual(set(mig.ROLES), {r for r, _ in ROLE_CHOICES})
        self.assertEqual(module_access.required('/api/data-health/refresh/', 'POST'), ('data_health', ('view',)))

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(API + 'growth/').status_code, (401, 403))


class GrowthTests(_ApiCase):
    def test_growth_with_no_snapshots_and_with_one(self):
        resp = self.client.get(API + 'growth/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data['as_of'])
        self.assertEqual(data['series'], [])
        self.assertIsNone(data['forecast']['daily_bytes'])
        self.assertIsNone(data['forecast']['days_to_level'])
        self.assertEqual(data['tables'], [])
        self.assertEqual(data['measures']['missed_retention_days'], 0)

        _snapshot(0, 1000, media=50, media_by_type={'unreferenced': {'bytes': 50, 'files': 2}},
                  media_by_folder={'orphans': {'bytes': 50, 'files': 2}})
        data = self.client.get(API + 'growth/').json()
        self.assertIsNotNone(data['as_of'])
        self.assertEqual(len(data['series']), 1)
        self.assertEqual(data['current']['db_bytes'], 1000)
        self.assertIsNone(data['forecast']['daily_bytes'])
        self.assertIsNone(data['forecast']['days_to_level'])
        self.assertEqual(data['types'][0]['key'], 'unreferenced')
        self.assertEqual(data['folders'][0]['folder'], 'orphans')

    def test_forecast_null_when_shrinking(self):
        _snapshot(10, 5000)
        _snapshot(0, 4000)
        forecast = self.client.get(API + 'growth/').json()['forecast']
        self.assertEqual(forecast['daily_bytes'], -100)
        self.assertIsNone(forecast['days_to_level'])

    @override_settings(DATA_HEALTH_DISK_LEVEL_PERCENT=85)
    def test_forecast_days(self):
        _snapshot(10, 1000, media=0)
        _snapshot(0, 1500, media=500)               # +1000 over 10 days = 100 a day
        forecast = self.client.get(API + 'growth/').json()['forecast']
        self.assertEqual(forecast['level_percent'], 85)
        self.assertEqual(forecast['daily_bytes'], 100)
        # level 85 % of 10,000 = 8,500; used 10,000 − 5,000 = 5,000; 3,500 left at 100 a day = 35 days
        self.assertEqual(forecast['days_to_level'], 35)

    def test_forecast_needs_seven_days(self):
        _snapshot(6, 1000)
        _snapshot(0, 2000)
        forecast = self.client.get(API + 'growth/').json()['forecast']
        self.assertIsNone(forecast['daily_bytes'])
        self.assertIsNone(forecast['days_to_level'])

    def test_forecast_floored_at_zero_when_past_level(self):
        _snapshot(10, 1000, free=500)
        _snapshot(0, 2000, free=500)
        self.assertEqual(self.client.get(API + 'growth/').json()['forecast']['days_to_level'], 0)

    def test_tables_growth_and_classification(self):
        old = timezone.now() - datetime.timedelta(days=20)
        new = timezone.now()
        TableSizeSnapshot.objects.create(taken_at=old, table='transits_intransitnote', total_bytes=100)
        TableSizeSnapshot.objects.create(taken_at=new, table='transits_intransitnote', total_bytes=300,
                                         heap_bytes=200, index_bytes=100, row_estimate=7)
        TableSizeSnapshot.objects.create(taken_at=new, table='mystery_table', total_bytes=50)
        _snapshot(0, 1, empty_by_table={'transits_intransitnote': 40})
        tables = {t['table']: t for t in self.client.get(API + 'growth/').json()['tables']}
        note = tables['transits_intransitnote']
        self.assertEqual((note['growth_bytes'], note['empty_bytes'], note['classified']), (200, 40, True))
        self.assertTrue(note['rule_label_ar'])
        self.assertIsNone(tables['mystery_table']['growth_bytes'])
        self.assertFalse(tables['mystery_table']['classified'])

    def test_p56_tables_classified(self):
        TableSizeSnapshot.objects.create(table='pbx_pbxevent', total_bytes=10)
        tables = {t['table']: t for t in self.client.get(API + 'growth/').json()['tables']}
        self.assertTrue(tables['pbx_pbxevent']['classified'])

    def test_measures(self):
        from apps.data_lifecycle.models import LifecycleRun
        run = LifecycleRun.objects.create()
        LifecycleRunLine.objects.create(run=run, rule_key='transit_alert_notes', count=3, bytes=0)
        LifecycleRunLine.objects.create(run=run, rule_key='transit_alert_notes', count=2, bytes=0)
        LifecycleRunLine.objects.create(run=run, rule_key='transit_alert_notes', count=99, is_preview=True)
        HeldFile.objects.create(original_path='a', hold_path='b', rule_key='unreferenced', sha256='0' * 64,
                                purge_after=timezone.now(), restored_at=timezone.now())
        _snapshot(5, 1)                         # first snapshot 5 days ago: days 1..5 count
        ok = SyncRun.objects.create(lane='retention', status='success')
        SyncRun.objects.filter(pk=ok.pk).update(started_at=timezone.now() - datetime.timedelta(days=2))
        failed = SyncRun.objects.create(lane='retention', status='failed')
        SyncRun.objects.filter(pk=failed.pk).update(started_at=timezone.now() - datetime.timedelta(days=3))
        measures = self.client.get(API + 'growth/').json()['measures']
        self.assertEqual(measures['removed'], [{'rule_key': 'transit_alert_notes',
                                                'label_ar': 'ملاحظات تنبيهات التحويلات المتأخرة',
                                                'count': 5, 'bytes': 0}])
        self.assertEqual(measures['restores'], 1)
        self.assertEqual(measures['missed_retention_days'], 4)


class ProblemsTests(_ApiCase):
    def test_problems_rows(self):
        keys = [p.key for p in problems.PROBLEMS]
        _snapshot(1, 1, problems={k: 10 for k in keys})
        _snapshot(0, 1, problems={**{k: 12 for k in keys}, keys[0]: None})
        data = self.client.get(API + 'problems/').json()
        rows = {r['key']: r for r in data['problems']}
        self.assertEqual(list(rows), keys)
        self.assertEqual((rows[keys[1]]['count'], rows[keys[1]]['previous_count'], rows[keys[1]]['change']),
                         (12, 10, 2))
        self.assertIsNone(rows[keys[0]]['count'])
        self.assertIsNone(rows[keys[0]]['change'])
        self.assertFalse(data['refreshing'])

    def test_problems_without_snapshot(self):
        data = self.client.get(API + 'problems/').json()
        self.assertIsNone(data['as_of'])
        self.assertTrue(all(r['count'] is None for r in data['problems']))

    def test_problems_contains_no_phone(self):
        make_customer(name='زبون سري للاختبار', phone='01099988877')
        Customer.objects.create(name='زبون سري ثان', phone='01099988877')
        _snapshot(0, 1, problems=problems.count_all())
        resp = self.client.get(API + 'problems/')
        text = json.dumps(resp.json(), ensure_ascii=False) + resp.content.decode('utf-8')
        for secret in ('01099988877', 'زبون سري'):
            self.assertNotIn(secret, text)


class RefreshTests(_ApiCase):
    def test_refresh_runs_once(self):
        with mock.patch.object(views, 'start_thread') as start:
            first = self.client.post(API + 'refresh/')
            second = bearer_client(make_supervisor('dh_sup2')[0]).post(API + 'refresh/')
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        self.assertEqual(first.json(), {'refreshing': True})
        self.assertEqual(second.json(), {'refreshing': True})
        self.assertEqual(start.call_count, 1)
        self.assertTrue(self.client.get(API + 'growth/').json()['refreshing'])

    def test_refresh_refused_for_pharmacist(self):
        with mock.patch.object(views, 'start_thread') as start:
            resp = bearer_client(make_pharmacist('dh_ph2')[0]).post(API + 'refresh/')
        self.assertEqual(resp.status_code, 403)
        start.assert_not_called()

    def test_refresh_job_clears_flag_and_closes_connection(self):
        cache.add(views.REFRESH_KEY, 1, 900)
        with mock.patch.object(views, 'take_snapshot') as take, \
                mock.patch.object(views.connection, 'close') as close:
            take.side_effect = RuntimeError('boom')
            with self.assertRaises(RuntimeError):
                views._refresh_job()
        take.assert_called_once_with(include_tables=True)
        close.assert_called_once()
        self.assertIsNone(cache.get(views.REFRESH_KEY))


class RulesTests(_ApiCase):
    def test_rules_list(self):
        data = self.client.get(API + 'rules/').json()
        rows = {r['key']: r for r in data['rules']}
        self.assertIn('file_rules_locked', data)
        rx = rows['prescriptions']
        self.assertEqual((rx['kind'], rx['minimum_days'], rx['keep_days'], rx['mode']), ('file', 1095, 1095, 'preview'))
        self.assertTrue(rx['can_change_days'])
        self.assertTrue(rx['changeable'])
        self.assertIsNone(rx['last_real'])
        self.assertIsNone(rx['last_preview'])
        self.assertFalse(rows['p56_pbx']['changeable'])
        self.assertFalse(rows['p56_pbx']['can_change_days'])
        self.assertFalse(rows['rate_runs']['can_change_days'])

    def test_patch_below_floor_refused_for_admin(self):
        resp = self.client.patch(API + 'rules/prescriptions/', {'keep_days': 30, 'reason': 'أقصر'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('1095', resp.json()['detail'])
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    def test_patch_on_without_preview_refused(self):
        resp = self.client.patch(API + 'rules/transit_alert_notes/', {'mode': 'on', 'reason': 'تشغيل'},
                                 format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()['detail'])

    def test_patch_needs_reason(self):
        resp = self.client.patch(API + 'rules/transit_alert_notes/', {'keep_days': 120}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    def test_patch_writes_audit(self):
        resp = self.client.patch(API + 'rules/transit_alert_notes/', {'keep_days': 120, 'reason': 'أطول'},
                                 format='json')
        self.assertEqual(resp.status_code, 200)
        row = resp.json()
        self.assertEqual((row['key'], row['keep_days'], row['policy_reason']), ('transit_alert_notes', 120, 'أطول'))
        self.assertTrue(row['changed_by'])
        self.assertIsNotNone(row['changed_at'])
        log = AuditLog.objects.get(action=AUDIT_ACTION)
        self.assertEqual(log.new_data['keep_days'], 120)

    def test_p56_refused(self):
        resp = self.client.patch(API + 'rules/p56_pbx/', {'keep_days': 200, 'reason': 'x'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.post(API + 'rules/p56_pbx/preview/').status_code, 400)

    def test_unknown_rule_404(self):
        self.assertEqual(self.client.patch(API + 'rules/nope/', {'keep_days': 9, 'reason': 'x'},
                                           format='json').status_code, 404)
        self.assertEqual(self.client.post(API + 'rules/nope/preview/').status_code, 404)

    def test_preview_writes_line_changes_nothing(self):
        from apps.transits.models import InTransitNote
        notes_before = InTransitNote.objects.count()
        resp = self.client.post(API + 'rules/transit_alert_notes/preview/')
        self.assertEqual(resp.status_code, 200)
        row = resp.json()
        self.assertEqual(row['key'], 'transit_alert_notes')
        self.assertIsNotNone(row['last_preview'])
        self.assertTrue(row['preview_fresh'])
        self.assertEqual(LifecycleRunLine.objects.filter(is_preview=True).count(), 1)
        self.assertFalse(LifecycleRunLine.objects.filter(is_preview=False).exists())
        self.assertEqual(InTransitNote.objects.count(), notes_before)
        self.assertFalse(LifecycleRulePolicy.objects.exists())


class HeldTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media, self.hold = self.tmp / 'media', self.tmp / 'media_hold'
        self.media.mkdir()
        self.hold.mkdir()
        s = override_settings(MEDIA_ROOT=self.media, LIFECYCLE_HOLD_ROOT=self.hold)
        s.enable()
        self.addCleanup(s.disable)

    def _held(self, rule_key, primary_model, original='images/x.jpg', hold_name=None, data=None, **kw):
        hold_name = hold_name or f'{rule_key}_{HeldFile.objects.count()}.jpg'
        (self.hold / hold_name).write_bytes(data if data is not None else _jpeg_bytes())
        return HeldFile.objects.create(original_path=original, hold_path=hold_name, rule_key=rule_key, size=10,
                                       sha256='ab' * 32, purge_after=timezone.now() + datetime.timedelta(days=30),
                                       primary_model=primary_model, primary_pk='7' if primary_model else '',
                                       primary_field='local_file' if primary_model else '', **kw)

    def test_held_rows_hide_paths(self):
        held = self._held('prescriptions', 'pos_orders.SoftechSalesOrder',
                          original='prescriptions/2023/secret_name.jpg', hold_name='feedbeef.jpg')
        resp = self.client.get(API + 'held/')
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode('utf-8')
        for secret in ('secret_name', 'prescriptions/2023', 'feedbeef', 'ab' * 32):
            self.assertNotIn(secret, text)
        data = resp.json()
        self.assertEqual(data['total'], 1)
        row = data['rows'][0]
        for key in ('hold_path', 'original_path', 'sha256', 'rows'):
            self.assertNotIn(key, row)
        self.assertEqual(row['id'], held.pk)
        self.assertEqual(row['rule_label_ar'], 'صور الروشتات')
        self.assertTrue(row['record_type_ar'])
        self.assertEqual(row['record_id'], '7')
        self.assertTrue(row['can_restore'])
        self.assertFalse(row['has_thumbnail'])
        self.assertIsNone(row['deleted_by'])

    def test_staff_hold_names_who_and_offers_no_restore(self):
        for n in range(3):
            self._held(holding.RECORD_DELETED, 'pos_orders.SoftechSalesOrder', deleted_by=self.admin)
        self._held(holding.FILE_REPLACED, 'images.ImageCandidate', deleted_by=self.admin)
        with self.assertNumQueries(2):          # count + one page with deleted_by and its user joined
            data = reports.held_payload()
        self.assertEqual(data['total'], 4)
        for row in data['rows']:
            self.assertEqual(row['deleted_by'], self.admin.full_name)
            self.assertFalse(row['can_restore'])

    def test_held_state_filter(self):
        self._held('images_rejected', 'images.ImageCandidate')
        self._held('images_rejected', 'images.ImageCandidate', restored_at=timezone.now())
        self._held('images_rejected', 'images.ImageCandidate', purged_at=timezone.now())
        self.assertEqual(self.client.get(API + 'held/').json()['total'], 1)
        self.assertEqual(self.client.get(API + 'held/?state=all').json()['total'], 3)
        unreferenced = self.client.get(API + 'held/?state=all').json()['rows']
        self.assertEqual(sum(r['can_restore'] for r in unreferenced), 1)

    def test_thumbnail_refused_for_prescription_and_pos_rx_and_orphan(self):
        cases = [
            self._held('prescriptions', 'pos_orders.SoftechSalesOrder'),
            self._held('ocr_pos_rx', 'vision.OcrSample'),
            self._held('unreferenced', '', original='prescriptions/2024/orphan.jpg'),
            self._held('conversations', 'whatsapp.WAMediaFile'),
            self._held('images_rejected', 'pos_orders.SoftechSalesOrder'),   # odd pairing: still refused
        ]
        for held in cases:
            self.assertFalse(reports.can_thumbnail(held), held.rule_key)
            resp = self.client.get(f'{API}held/{held.pk}/thumbnail/')
            self.assertEqual(resp.status_code, 404, held.rule_key)
            self.assertNotEqual(resp.get('Content-Type'), 'image/jpeg')

    def test_thumbnail_served_for_rejected_image(self):
        held = self._held('images_rejected', 'images.ImageCandidate')
        self.assertTrue(self.client.get(API + 'held/').json()['rows'][0]['has_thumbnail'])
        resp = self.client.get(f'{API}held/{held.pk}/thumbnail/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')
        self.assertEqual(resp['Cache-Control'], 'private, no-store')
        image = Image.open(io.BytesIO(resp.content))
        self.assertLessEqual(max(image.size), 160)

    def test_thumbnail_404_when_not_an_image_or_missing(self):
        broken = self._held('images_rejected', 'images.ImageCandidate', data=b'not an image')
        self.assertEqual(self.client.get(f'{API}held/{broken.pk}/thumbnail/').status_code, 404)
        gone = self._held('images_obsolete', 'product_experience.ProductMedia')
        (self.hold / gone.hold_path).unlink()
        self.assertEqual(self.client.get(f'{API}held/{gone.pk}/thumbnail/').status_code, 404)
        self.assertEqual(self.client.get(f'{API}held/999999/thumbnail/').status_code, 404)

    def test_p56_tables_resolve(self):
        self.assertEqual(sorted(reports.P56_TABLES), sorted(k for k in reports.RULES if k.startswith('p56_')))
        for key, labels in reports.P56_TABLES.items():
            self.assertTrue(labels, key)
            for label in labels:
                django_apps.get_model(label)


POLICY = 'data_lifecycle.LifecycleRulePolicy'
BYTES = b'restorable bytes'
NAME = 'images/2024/restore_me.jpg'


class RestoreTests(TransactionTestCase):
    """holding.restore uses a durable transaction, so these run without the TestCase wrapper."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media, self.hold = self.tmp / 'media', self.tmp / 'media_hold'
        self.media.mkdir()
        s = override_settings(MEDIA_ROOT=self.media, LIFECYCLE_HOLD_ROOT=self.hold)
        s.enable()
        self.addCleanup(s.disable)
        self.addCleanup(module_access.clear_cache)
        module_access.clear_cache()
        self.admin_user = make_admin('dh_restore_admin')[0]
        self.client = bearer_client(self.admin_user)
        path = self.media / NAME
        path.parent.mkdir(parents=True)
        path.write_bytes(BYTES)
        self.record = LifecycleRulePolicy.objects.create(rule_key='restore_target', reason=NAME)
        self.held = holding.hold_file(NAME, [{'model': POLICY, 'pk': self.record.pk, 'field': 'reason',
                                              'value': NAME}], 'unreferenced')

    def test_restore_returns_file(self):
        resp = self.client.post(f'{API}held/{self.held.pk}/restore/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual((self.media / NAME).read_bytes(), BYTES)
        self.record.refresh_from_db()
        self.assertEqual(self.record.reason, NAME)
        row = resp.json()
        self.assertEqual(row['id'], self.held.pk)
        self.assertIsNotNone(row['restored_at'])
        self.assertFalse(row['can_restore'])
        self.assertNotIn(NAME, resp.content.decode('utf-8'))

    def test_restore_refused_when_path_occupied(self):
        (self.media / NAME).write_bytes(b'someone else')
        resp = self.client.post(f'{API}held/{self.held.pk}/restore/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()['detail'])
        self.assertNotIn(NAME, resp.content.decode('utf-8'))
        self.held.refresh_from_db()
        self.assertIsNone(self.held.restored_at)
        self.assertEqual((self.media / NAME).read_bytes(), b'someone else')

    def test_restore_stranded_is_generic_500(self):
        with mock.patch.object(views.holding, 'restore', side_effect=holding.FileStranded('detail with ref')):
            resp = self.client.post(f'{API}held/{self.held.pk}/restore/')
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn('ref', resp.json()['detail'])

    def test_restore_unknown_is_400(self):
        resp = self.client.post(f'{API}held/999999/restore/')
        self.assertEqual(resp.status_code, 400)

