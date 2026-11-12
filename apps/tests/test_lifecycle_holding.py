"""
Data lifecycle Stage 3: the holding folder (design §6 Stage 3, §7, §8).

A mistake here can lose a real document, so most of these tests are about what happens when a step fails:
the file must always end up in exactly one known place, and the record must agree.
"""
import datetime
import hashlib
import logging
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.core.management import CommandError, call_command
from django.db import transaction
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.data_lifecycle import holding, runner
from apps.data_lifecycle.holding import (AUDIT_ACTION, HOLD_DAYS, FileStranded, HoldError, hold_file, purge_expired,
                                         restore)
from apps.data_lifecycle.models import HeldFile, LifecycleRulePolicy
from apps.notifications.models import Notification
from core.media import serve_media
from core.storage import sign_media_name

from .factories import make_admin, make_branch, make_pharmacist

POLICY = 'data_lifecycle.LifecycleRulePolicy'     # a text field and an auto_now field, and nothing it needs first
BYTES = b'prescription bytes \xd8\xb1\xd9\x88\xd8\xb4\xd8\xaa\xd8\xa9'
SHA = hashlib.sha256(BYTES).hexdigest()
NAME = 'prescriptions/2023/secret_name.jpg'


class HoldingCase(TestCase):
    """A temporary media folder and a temporary hold folder beside it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media = self.tmp / 'media'
        self.hold = self.tmp / 'media_hold'
        self.media.mkdir()
        settings = override_settings(MEDIA_ROOT=self.media, LIFECYCLE_HOLD_ROOT=self.hold)
        settings.enable()
        self.addCleanup(settings.disable)
        self.file = self._put(NAME)

    def _put(self, name, data=BYTES):
        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _record(self, key='prescriptions', value=NAME):
        return LifecycleRulePolicy.objects.create(rule_key=key, reason=value)

    def _row(self, record, value=NAME):
        return {'model': POLICY, 'pk': record.pk, 'field': 'reason', 'value': value}

    def _hold_files(self):
        return [p for p in self.hold.rglob('*') if p.is_file()] if self.hold.exists() else []

    def _held(self, **kwargs):
        record = self._record()
        held = hold_file(NAME, [self._row(record)], 'prescriptions', **kwargs)
        return held, record


class HoldTests(HoldingCase):
    def test_hold_moves_file_and_clears_rows(self):
        first, second = self._record('a'), self._record('b')
        before = timezone.now()
        held = hold_file(NAME, [self._row(first), self._row(second)], 'prescriptions')

        self.assertFalse(self.file.exists())
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.reason, second.reason), ('', ''))
        self.assertEqual((held.original_path, held.rule_key, held.size, held.sha256),
                         (NAME, 'prescriptions', len(BYTES), SHA))
        self.assertEqual((held.primary_model, held.primary_pk, held.primary_field),
                         (POLICY, str(first.pk), 'reason'))
        self.assertEqual(held.rows, [self._row(first), self._row(second)])
        self.assertGreaterEqual(held.moved_at, before)
        self.assertEqual(held.purge_after, held.moved_at + datetime.timedelta(days=30))
        self.assertEqual(HOLD_DAYS, 30)

    def test_clearing_skips_auto_now(self):
        record = self._record()
        changed_at = LifecycleRulePolicy.objects.get(pk=record.pk).changed_at
        hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertEqual(LifecycleRulePolicy.objects.get(pk=record.pk).changed_at, changed_at)

    def test_real_file_field_is_cleared_and_restored(self):
        from apps.invoices.models import InvoiceBatch
        batch = InvoiceBatch.objects.create(branch=make_branch(), source_file=NAME)
        row = {'model': 'invoices.InvoiceBatch', 'pk': batch.pk, 'field': 'source_file', 'value': NAME}
        held = hold_file(NAME, [row], 'prescriptions')
        self.assertEqual(InvoiceBatch.objects.get(pk=batch.pk).source_file.name, '')
        _, admin, _ = make_admin('hold_filefield')
        restore(held.pk, admin)
        self.assertEqual(InvoiceBatch.objects.get(pk=batch.pk).source_file.name, NAME)

    def test_folder_file_with_no_rows_is_a_valid_hold(self):
        held = hold_file(NAME, [], 'bundle_pages')
        self.assertEqual((held.primary_model, held.primary_pk, held.primary_field, held.rows), ('', '', '', []))
        _, admin, _ = make_admin('hold_folder')
        restore(held.pk, admin)
        self.assertEqual(self.file.read_bytes(), BYTES)

    def test_two_files_with_one_name_do_not_collide(self):
        other = self._put('prescriptions/2024/secret_name.jpg', b'other bytes')
        first = hold_file(NAME, [], 'bundle_pages')
        second = hold_file('prescriptions/2024/secret_name.jpg', [], 'bundle_pages')
        self.assertFalse(other.exists())
        self.assertNotEqual(first.hold_path, second.hold_path)
        self.assertEqual((self.hold / first.hold_path).read_bytes(), BYTES)
        self.assertEqual((self.hold / second.hold_path).read_bytes(), b'other bytes')

    def test_hold_path_does_not_carry_the_filename(self):
        held = hold_file(NAME, [], 'bundle_pages')
        self.assertNotIn('secret_name', held.hold_path)

    def test_failed_db_step_puts_file_back(self):
        record = self._record()
        with mock.patch.object(HeldFile.objects, 'create', side_effect=RuntimeError('db down')):
            with self.assertRaises(HoldError):
                hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertEqual(self._hold_files(), [])
        record.refresh_from_db()
        self.assertEqual(record.reason, NAME)        # the cleared row rolled back too
        self.assertFalse(HeldFile.objects.exists())

    def test_interrupt_during_db_step_still_puts_file_back(self):
        record = self._record()
        with mock.patch.object(HeldFile.objects, 'create', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), BYTES)

    def test_row_changed_meanwhile_rolls_back(self):
        changed, untouched = self._record('a', value='a newer upload'), self._record('b')
        with self.assertRaises(HoldError):
            hold_file(NAME, [self._row(untouched), self._row(changed)], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertEqual(self._hold_files(), [])
        changed.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual((changed.reason, untouched.reason), ('a newer upload', NAME))
        self.assertFalse(HeldFile.objects.exists())

    def test_deleted_row_rolls_back(self):
        record = self._record()
        row = self._row(record)
        record.delete()
        with self.assertRaises(HoldError):
            hold_file(NAME, [row], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), BYTES)

    def test_bad_rows_are_refused_before_the_file_moves(self):
        record = self._record()
        for row in ({'model': 'no.Such', 'pk': 1, 'field': 'x', 'value': 'y'},
                    {'model': POLICY, 'pk': record.pk, 'field': 'no_such_field', 'value': 'y'},
                    {'model': POLICY, 'pk': record.pk, 'field': 'reason', 'value': ''},
                    {'model': POLICY, 'pk': record.pk, 'field': 'reason'}):
            with self.subTest(row=row):
                with mock.patch.object(holding.shutil, 'move') as move:
                    with self.assertRaises(HoldError):
                        hold_file(NAME, [row], 'prescriptions')
                move.assert_not_called()
        self.assertEqual(self.file.read_bytes(), BYTES)

    def test_file_that_does_not_move_changes_nothing(self):
        record = self._record()
        with mock.patch.object(holding.shutil, 'move', side_effect=PermissionError('locked ' + NAME)):
            with self.assertRaises(HoldError) as caught:
                hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertNotIn('secret_name', str(caught.exception))
        self.assertEqual(self.file.read_bytes(), BYTES)
        record.refresh_from_db()
        self.assertEqual(record.reason, NAME)
        self.assertFalse(HeldFile.objects.exists())

    def test_partial_copy_is_removed_when_a_move_across_disks_fails(self):
        def copy_then_fail(src, dst):
            Path(dst).write_bytes(b'half')
            raise OSError('disk full')

        with mock.patch.object(holding.shutil, 'move', side_effect=copy_then_fail):
            with self.assertRaises(HoldError):
                hold_file(NAME, [], 'bundle_pages')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertEqual(self._hold_files(), [])

    def test_put_back_never_overwrites_a_new_file_and_reports_the_stranded_one(self):
        record = self._record()

        def new_upload_arrives(**kwargs):
            self.file.write_bytes(b'new upload')
            raise RuntimeError('db down')

        with mock.patch.object(HeldFile.objects, 'create', side_effect=new_upload_arrives):
            with self.assertLogs('elrezeiky.sync', level=logging.CRITICAL) as logs:
                with self.assertRaises(FileStranded):
                    hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), b'new upload')
        stranded = self._hold_files()
        self.assertEqual([p.read_bytes() for p in stranded], [BYTES])     # not lost, and the log says where
        line = logs.output[0]
        self.assertIn(stranded[0].name, line)
        for part in ('rule_key=prescriptions', f'primary_model={POLICY}', f'primary_pk={record.pk}',
                     'primary_field=reason', f'sha256={SHA}'):
            self.assertIn(part, line)
        self.assertNotIn('secret_name', line)

    def test_hold_is_refused_inside_a_callers_transaction(self):
        record = self._record()
        with transaction.atomic():
            with self.assertRaises(HoldError):
                hold_file(NAME, [self._row(record)], 'prescriptions')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertEqual(self._hold_files(), [])
        record.refresh_from_db()
        self.assertEqual(record.reason, NAME)
        self.assertFalse(HeldFile.objects.exists())

    def test_path_outside_media_is_refused(self):
        outside = self.tmp / 'outside.jpg'
        outside.write_bytes(BYTES)
        for path in ('../outside.jpg', str(outside), '../media_hold/x.jpg', 'prescriptions/../../outside.jpg'):
            with self.subTest(path=path):
                with self.assertRaises(HoldError):
                    hold_file(path, [], 'bundle_pages')
        self.assertEqual(outside.read_bytes(), BYTES)

    def test_media_root_itself_folders_and_missing_files_are_refused(self):
        for path in ('', '.', 'prescriptions', 'prescriptions/none.jpg'):
            with self.subTest(path=path):
                with self.assertRaises(HoldError):
                    hold_file(path, [], 'bundle_pages')
        self.assertEqual(self.file.read_bytes(), BYTES)

    def test_original_path_is_stored_relative_to_media(self):
        held = hold_file('prescriptions/2023/../2023/secret_name.jpg', [], 'bundle_pages')
        self.assertEqual(held.original_path, NAME)

    def test_logs_carry_no_filename(self):
        record = self._record()
        with self.assertLogs('elrezeiky.sync', level=logging.INFO) as logs:
            held = hold_file(NAME, [self._row(record)], 'prescriptions')
            _, admin, _ = make_admin('hold_logs')
            restore(held.pk, admin)
            logging.getLogger('elrezeiky.sync').info('end')    # assertLogs fails on no output at all
        self.assertNotIn('secret_name', '\n'.join(logs.output))


class HoldRootTests(HoldingCase):
    def _refused(self, root):
        with override_settings(LIFECYCLE_HOLD_ROOT=root):
            with self.assertRaises(HoldError):
                hold_file(NAME, [], 'bundle_pages')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertFalse(HeldFile.objects.exists())

    def test_hold_root_equal_to_media_is_refused(self):
        self._refused(self.media)

    def test_hold_root_under_media_is_refused(self):
        self._refused(self.media / 'a' / 'hold')

    def test_hold_root_written_so_it_only_resolves_into_media_is_refused(self):
        self._refused(self.tmp / 'other' / '..' / 'media' / 'hold')

    def test_empty_setting_means_current_directory_and_is_refused(self):
        self._refused(Path(''))

    def test_current_directory_by_full_path_is_refused(self):
        self._refused(Path.cwd())

    def test_sibling_that_only_starts_with_the_same_text_is_accepted(self):
        self.assertTrue(str(self.hold).startswith(str(self.media)))
        held = hold_file(NAME, [], 'bundle_pages')
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)

    def test_restore_and_purge_refuse_a_bad_hold_root_too(self):
        held, _ = self._held()
        _, admin, _ = make_admin('hold_badroot')
        HeldFile.objects.filter(pk=held.pk).update(purge_after=timezone.now() - datetime.timedelta(days=1))
        with override_settings(LIFECYCLE_HOLD_ROOT=self.media):
            with self.assertRaises(HoldError):
                restore(held.pk, admin)
            with self.assertRaises(HoldError):
                purge_expired()
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)


class RestoreTests(HoldingCase):
    def setUp(self):
        super().setUp()
        _, self.admin, _ = make_admin('hold_admin')

    def test_restore_returns_path_and_bytes(self):
        first, second = self._record('a'), self._record('b')
        held = hold_file(NAME, [self._row(first), self._row(second)], 'prescriptions')

        result = restore(held.pk, self.admin)

        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(), SHA)
        self.assertEqual(self._hold_files(), [])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.reason, second.reason), (NAME, NAME))
        self.assertEqual(result.restored_by, self.admin)
        self.assertIsNotNone(result.restored_at)
        self.assertIsNone(result.purged_at)

    def test_restore_writes_each_rows_own_value(self):
        url = '/media/' + NAME
        by_path, by_url = self._record('a'), self._record('b', value=url)
        held = hold_file(NAME, [self._row(by_path), self._row(by_url, url)], 'prescriptions')
        restore(held.pk, self.admin)
        by_path.refresh_from_db()
        by_url.refresh_from_db()
        self.assertEqual((by_path.reason, by_url.reason), (NAME, url))

    def test_restore_writes_audit(self):
        held, record = self._held()
        restore(held.pk, self.admin)
        log = AuditLog.objects.get(action=AUDIT_ACTION)
        self.assertEqual((log.user, log.model_name, log.object_id), (self.admin, 'HeldFile', str(held.pk)))
        self.assertEqual(log.extra['rule_key'], 'prescriptions')
        self.assertEqual((log.extra['primary_model'], log.extra['primary_pk']), (POLICY, str(record.pk)))
        self.assertIsNone(log.old_data['restored_at'])
        self.assertIsNotNone(log.new_data['restored_at'])
        self.assertNotIn('secret_name', f'{log.object_repr} {log.note} {log.extra} {log.old_data} {log.new_data}')

    def test_restore_is_undone_when_the_audit_cannot_be_written(self):
        held, record = self._held()
        with mock.patch.object(holding.AuditLog, 'log', return_value=None):
            with self.assertRaises(HoldError):
                restore(held.pk, self.admin)
        self._assert_still_held(held, record)

    def test_restore_needs_a_user(self):
        held, record = self._held()
        with self.assertRaises(HoldError):
            restore(held.pk, None)
        self._assert_still_held(held, record)

    def _assert_still_held(self, held, record):
        self.assertFalse(self.file.exists())
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)
        record.refresh_from_db()
        self.assertEqual(record.reason, '')
        held.refresh_from_db()
        self.assertIsNone(held.restored_at)
        self.assertFalse(AuditLog.objects.filter(action=AUDIT_ACTION).exists())

    def test_restore_is_refused_inside_a_callers_transaction(self):
        held, record = self._held()
        with transaction.atomic():
            with self.assertRaises(HoldError):
                restore(held.pk, self.admin)
        self._assert_still_held(held, record)

    def test_stranded_restore_logs_where_the_file_really_is(self):
        held, record = self._held()
        hold_copy = self.hold / held.hold_path

        def something_takes_the_hold_name(*args, **kwargs):
            hold_copy.write_bytes(b'in the way')
            raise RuntimeError('db down')

        with mock.patch.object(holding.AuditLog, 'log', side_effect=something_takes_the_hold_name):
            with self.assertLogs('elrezeiky.sync', level=logging.CRITICAL) as logs:
                with self.assertRaises(FileStranded):
                    restore(held.pk, self.admin)
        self.assertEqual(self.file.read_bytes(), BYTES)         # it is at the original path, and intact
        self.assertEqual(hold_copy.read_bytes(), b'in the way')
        line = logs.output[0]
        self.assertIn(f'held {held.pk}: it is at the original_path of that record', line)
        self.assertNotIn('secret_name', line)
        record.refresh_from_db()
        self.assertEqual(record.reason, '')
        held.refresh_from_db()
        self.assertIsNone(held.restored_at)

    def test_restore_refused_when_row_has_new_file(self):
        held, record = self._held()
        LifecycleRulePolicy.objects.filter(pk=record.pk).update(reason='a newer upload')
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        self.assertFalse(self.file.exists())
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)
        record.refresh_from_db()
        self.assertEqual(record.reason, 'a newer upload')
        held.refresh_from_db()
        self.assertIsNone(held.restored_at)

    def test_restore_refused_when_row_is_gone(self):
        held, record = self._held()
        record.delete()
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)

    def test_restore_refused_when_original_path_is_occupied(self):
        held, record = self._held()
        self.file.write_bytes(b'new upload')
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        self.assertEqual(self.file.read_bytes(), b'new upload')
        self.assertEqual((self.hold / held.hold_path).read_bytes(), BYTES)
        record.refresh_from_db()
        self.assertEqual(record.reason, '')

    def test_restore_refused_when_bytes_changed(self):
        held, record = self._held()
        (self.hold / held.hold_path).write_bytes(b'damaged')
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        self.assertFalse(self.file.exists())
        self.assertEqual(LifecycleRulePolicy.objects.get(pk=record.pk).reason, '')

    def test_restore_refused_when_held_file_is_missing(self):
        held, _ = self._held()
        (self.hold / held.hold_path).unlink()
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        held.refresh_from_db()
        self.assertIsNone(held.restored_at)

    def test_restore_twice_is_refused(self):
        held, _ = self._held()
        restore(held.pk, self.admin)
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertEqual(AuditLog.objects.filter(action=AUDIT_ACTION).count(), 1)

    def test_restore_refused_after_purge_and_for_unknown_id(self):
        held, _ = self._held()
        purge_expired(now=held.purge_after)
        with self.assertRaises(HoldError):
            restore(held.pk, self.admin)
        with self.assertRaises(HoldError):
            restore(held.pk + 1000, self.admin)

    def test_restore_is_refused_for_a_stored_path_that_leaves_its_folder(self):
        for field, value in (('original_path', '../outside.jpg'), ('hold_path', '../media/x.jpg')):
            with self.subTest(field=field):
                held = hold_file(self._put(f'{field}.jpg').name, [], 'bundle_pages')
                HeldFile.objects.filter(pk=held.pk).update(**{field: value})
                with self.assertRaises(HoldError):
                    restore(held.pk, self.admin)

    def test_failed_db_step_during_restore_returns_file_to_hold(self):
        held, record = self._held()
        with mock.patch.object(holding.AuditLog, 'log', side_effect=RuntimeError('db down')):
            with self.assertRaises(HoldError):
                restore(held.pk, self.admin)
        self._assert_still_held(held, record)

    def test_restore_after_the_purge_date_works_while_the_file_is_still_there(self):
        held, _ = self._held()
        HeldFile.objects.filter(pk=held.pk).update(purge_after=timezone.now() - datetime.timedelta(days=1))
        restore(held.pk, self.admin)
        self.assertEqual(self.file.read_bytes(), BYTES)


class PurgeTests(HoldingCase):
    def test_purge_only_after_30_days(self):
        held, _ = self._held()
        path = self.hold / held.hold_path

        self.assertEqual(purge_expired(now=held.moved_at + datetime.timedelta(days=29, hours=23)), 0)
        self.assertTrue(path.exists())
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)

        when = held.moved_at + datetime.timedelta(days=30)
        self.assertEqual(purge_expired(now=when), 1)
        self.assertFalse(path.exists())
        held.refresh_from_db()                 # the row stays, so the removal date stays known
        self.assertEqual(held.purged_at, when)

    def test_purge_skips_restored(self):
        held, _ = self._held()
        _, admin, _ = make_admin('hold_purge')
        restore(held.pk, admin)
        self.assertEqual(purge_expired(now=held.purge_after + datetime.timedelta(days=1)), 0)
        self.assertEqual(self.file.read_bytes(), BYTES)
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)

    def test_purge_runs_once(self):
        held, _ = self._held()
        self.assertEqual(purge_expired(now=held.purge_after), 1)
        self.assertEqual(purge_expired(now=held.purge_after), 0)

    def test_one_failed_file_does_not_stop_the_others_and_the_step_fails(self):
        bad = hold_file(NAME, [], 'bundle_pages')
        good = hold_file(self._put('b.jpg').name, [], 'bundle_pages')
        when = bad.purge_after + datetime.timedelta(days=1)
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == Path(bad.hold_path).name:
                raise PermissionError('locked ' + NAME)
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, 'unlink', unlink):
            with self.assertLogs('elrezeiky.sync', level=logging.ERROR) as logs:
                with self.assertRaises(HoldError) as caught:
                    purge_expired(now=when)
        self.assertNotIn('secret_name', str(caught.exception) + '\n'.join(logs.output))
        self.assertIn(str(bad.pk), '\n'.join(logs.output))
        bad.refresh_from_db()
        good.refresh_from_db()
        self.assertIsNone(bad.purged_at)        # it failed, so the record must not say it was removed
        self.assertTrue((self.hold / bad.hold_path).exists())
        self.assertEqual(good.purged_at, when)
        self.assertFalse((self.hold / good.hold_path).exists())

    def _holds(self, count):
        return [hold_file(self._put(f'f{i}.jpg').name, [], 'bundle_pages') for i in range(count)]

    def _alerts(self):
        return Notification.objects.filter(notification_type='sync_failure')

    def test_one_missing_file_is_skipped_with_one_alert_a_day(self):
        make_admin('hold_missing')
        lost, *others = self._holds(3)
        (self.hold / lost.hold_path).unlink()
        when = lost.purge_after + datetime.timedelta(days=1)

        self.assertEqual(purge_expired(now=when), 2)
        lost.refresh_from_db()
        self.assertIsNone(lost.purged_at)       # not recorded as purged: nobody has said what happened to it
        for held in others:
            held.refresh_from_db()
            self.assertEqual(held.purged_at, when)
        self.assertEqual(self._alerts().count(), 1)
        self.assertIn(str(lost.pk), self._alerts().get().body)
        self.assertNotIn('f0.jpg', self._alerts().get().body)

        # The others are gone now, so it is the only one due. It is still one lost file, not a wrong folder.
        self.assertEqual(purge_expired(now=when + datetime.timedelta(minutes=1)), 0)
        self.assertEqual(self._alerts().count(), 1)
        self.assertEqual(purge_expired(now=when + datetime.timedelta(days=1)), 0)
        self.assertEqual(self._alerts().count(), 2)

    def test_exactly_half_missing_is_not_a_wrong_folder(self):
        held = self._holds(4)
        for lost in held[:2]:
            (self.hold / lost.hold_path).unlink()
        self.assertEqual(purge_expired(now=held[-1].purge_after), 2)     # the last made is due last

    def test_more_than_half_missing_raises_and_deletes_nothing(self):
        make_admin('hold_most_missing')
        held = self._holds(3)
        for lost in held[:2]:
            (self.hold / lost.hold_path).unlink()
        with self.assertRaises(HoldError):
            purge_expired(now=held[-1].purge_after)  # the last made is due last
        self.assertTrue((self.hold / held[2].hold_path).exists())
        held[2].refresh_from_db()
        self.assertIsNone(held[2].purged_at)
        self.assertEqual(self._alerts().count(), 0)

    def test_missing_hold_root_raises(self):
        held, _ = self._held()
        shutil.rmtree(self.hold)
        with self.assertRaises(HoldError):
            purge_expired(now=held.purge_after)
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)

    def test_bad_hold_root_with_nothing_due_is_no_failure(self):
        with override_settings(LIFECYCLE_HOLD_ROOT=self.media):
            self.assertEqual(purge_expired(), 0)

    def test_stored_hold_path_outside_the_hold_root_is_never_deleted(self):
        held, _ = self._held()
        victim = self._put('victim.jpg')
        HeldFile.objects.filter(pk=held.pk).update(hold_path='../media/victim.jpg')
        with self.assertRaises(HoldError):
            purge_expired(now=held.purge_after)
        self.assertEqual(victim.read_bytes(), BYTES)

    def test_retention_step_calls_the_purge(self):
        with mock.patch.object(holding, 'purge_expired', return_value=4) as purge:
            self.assertEqual(runner.purge_held_files(), 4)
        purge.assert_called_once_with()


class TestSettingsTests(TestCase):
    def test_test_runs_do_not_use_the_real_hold_folder(self):
        root = Path(django_settings.LIFECYCLE_HOLD_ROOT).resolve()
        self.assertNotIn(Path(django_settings.BASE_DIR).resolve(), root.parents)
        self.assertNotIn(Path(django_settings.MEDIA_ROOT).resolve(), root.parents)


class NoUrlTests(HoldingCase):
    def _get(self, path, signed_as=None):
        request = RequestFactory().get('/media/' + path, sign_media_name(signed_as or path))
        return serve_media(request, path)

    def test_held_file_has_no_url(self):
        response = self._get(NAME)        # the same signed link works before the hold
        self.assertEqual(response.status_code, 200)
        response.file_to_stream.close()   # response.close() would signal request_finished and close the database
        held, _ = self._held()
        with self.assertRaises(Http404):
            self._get(NAME)
        with self.assertRaises(Http404):     # serve_media cleans `..` away, so this looks inside media
            self._get(f'../media_hold/{held.hold_path}', signed_as=f'media_hold/{held.hold_path}')
        self.assertNotIn(self.media, (self.hold / held.hold_path).resolve().parents)


class RestoreCommandTests(HoldingCase):
    def setUp(self):
        super().setUp()
        _, self.admin, _ = make_admin('hold_cmd_admin')

    def _call(self, *args):
        out = StringIO()
        call_command('lifecycle', *args, stdout=out)
        return out.getvalue()

    def test_restore_command(self):
        held, _ = self._held()
        output = self._call('restore', str(held.pk), '--user', 'hold_cmd_admin')
        self.assertEqual(self.file.read_bytes(), BYTES)
        self.assertNotIn('secret_name', output)
        held.refresh_from_db()
        self.assertEqual(held.restored_by, self.admin)

    def test_restore_command_needs_an_active_admin(self):
        held, _ = self._held()
        make_pharmacist('hold_cmd_pharmacist')
        for username in ('hold_cmd_pharmacist', 'nobody'):
            with self.assertRaises(CommandError, msg=username):
                self._call('restore', str(held.pk), '--user', username)
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        with self.assertRaises(CommandError):
            self._call('restore', str(held.pk), '--user', 'hold_cmd_admin')
        self.assertFalse(self.file.exists())

    def test_retrieve_command_writes_a_copy(self):
        held, _ = self._held()
        out = self.tmp / 'copy.jpg'
        output = self._call('retrieve', str(held.pk), '--user', 'hold_cmd_admin', '--out', str(out))
        self.assertEqual(out.read_bytes(), BYTES)
        self.assertNotIn('secret_name', output)
        self.assertIn(str(held.pk), output)
        self.assertTrue((self.hold / held.hold_path).exists())          # a copy; the held file stays
        self.assertTrue(AuditLog.objects.filter(action='lifecycle_file_retrieved', object_id=str(held.pk)).exists())

    def test_retrieve_command_refuses_overwrite_and_non_admins(self):
        held, _ = self._held()
        out = self.tmp / 'existing.jpg'
        out.write_bytes(b'keep me')
        with self.assertRaises(CommandError):
            self._call('retrieve', str(held.pk), '--user', 'hold_cmd_admin', '--out', str(out))
        self.assertEqual(out.read_bytes(), b'keep me')
        make_pharmacist('hold_cmd_pharmacist2')
        fresh = self.tmp / 'fresh.jpg'
        with self.assertRaises(CommandError):
            self._call('retrieve', str(held.pk), '--user', 'hold_cmd_pharmacist2', '--out', str(fresh))
        self.assertFalse(fresh.exists())
        self.assertFalse(AuditLog.objects.filter(action='lifecycle_file_retrieved').exists())

    def test_restore_refusal_is_a_command_error(self):
        held, _ = self._held()
        self.file.write_bytes(b'new upload')
        with self.assertRaises(CommandError):
            self._call('restore', str(held.pk), '--user', 'hold_cmd_admin')

    def _mark_lost(self, held, user='hold_cmd_admin', reason='lost in the disk move'):
        return self._call('mark-lost', str(held.pk), '--user', user, '--reason', reason)

    def test_mark_lost_closes_a_missing_file_with_audit(self):
        held, _ = self._held()
        (self.hold / held.hold_path).unlink()
        output = self._mark_lost(held)
        self.assertNotIn('secret_name', output)
        held.refresh_from_db()
        self.assertIsNotNone(held.purged_at)
        log = AuditLog.objects.get(action=holding.AUDIT_ACTION_LOST)
        self.assertEqual(log.old_data, {'purged_at': None})
        self.assertEqual(log.extra['reason'], 'lost in the disk move')
        self.assertEqual(purge_expired(now=held.purge_after), 0)

    def test_mark_lost_is_refused_while_the_file_exists(self):
        held, _ = self._held()
        with self.assertRaises(CommandError):
            self._mark_lost(held)
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)
        self.assertFalse(AuditLog.objects.filter(action=holding.AUDIT_ACTION_LOST).exists())

    def test_mark_lost_is_refused_when_the_hold_root_is_missing(self):
        held, _ = self._held()
        shutil.rmtree(self.hold)
        with self.assertRaises(CommandError):
            self._mark_lost(held)
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)

    def test_mark_lost_needs_an_active_admin_and_a_reason(self):
        held, _ = self._held()
        (self.hold / held.hold_path).unlink()
        make_pharmacist('hold_cmd_pharmacist')
        for username in ('hold_cmd_pharmacist', 'nobody'):
            with self.assertRaises(CommandError, msg=username):
                self._mark_lost(held, user=username)
        with self.assertRaises(CommandError):
            self._mark_lost(held, reason='   ')
        held.refresh_from_db()
        self.assertIsNone(held.purged_at)

    def test_mark_lost_is_refused_on_a_closed_record(self):
        held, _ = self._held()
        restore(held.pk, self.admin)
        with self.assertRaises(CommandError):
            self._mark_lost(held)
