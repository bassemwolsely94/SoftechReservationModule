"""
Data lifecycle Stage 4, Task 2: a file follows its record into the holding folder.

When staff delete a record or replace its file, the old file is not destroyed on the spot: it waits 30 days in
the holding folder with who and when, then is purged. A shared file is never moved, a rolled-back delete moves
nothing, and a hold that fails never breaks the user's request.
"""
import datetime
import io
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.data_lifecycle import holding
from apps.data_lifecycle.display import removed_dates
from apps.data_lifecycle.holding import FILE_REPLACED, HOLD_DAYS, RECORD_DELETED, HoldError
from apps.data_lifecycle.models import HeldFile
from apps.pos_orders.models import SoftechSalesOrder
from apps.reservations.models import Reservation, ReservationImage
from apps.tests.factories import make_branch, make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

RES_URL = '/api/reservations/'
SECRET = 'patient_secret_name'

# Every remaining direct file deletion outside the lifecycle app, with the reason it may stay.
# The four staff deletions (reservations, callcenter, tasks, product_experience) now go through the signal.
DIRECT_DELETE_ALLOWLIST = {}
DIRECT_DELETE_PATTERN = re.compile(r'\.delete\(save=|default_storage\.delete\(')


def _png(colour=(255, 0, 0)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), colour).save(buf, format='PNG')
    return buf.getvalue()


@override_settings(RBAC_ENFORCEMENT='log')
class FollowCase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media = self.tmp / 'media'
        self.hold = self.tmp / 'media_hold'
        self.media.mkdir()
        over = override_settings(MEDIA_ROOT=self.media, LIFECYCLE_HOLD_ROOT=self.hold)
        over.enable()
        self.addCleanup(over.disable)
        seed_code_matrix()
        self.addCleanup(module_access.clear_cache)
        self.branch = make_branch()
        self.item = make_item('باراسيتامول متابعة', 'LF01')
        self.pharm_user, self.pharm, _ = make_user('follow_pharm', role='pharmacist', branch=self.branch)
        _, self.admin, self.admin_c = make_user('follow_admin', role='admin', access_all=True)

    def _reservation(self):
        return Reservation.objects.create(item=self.item, branch=self.branch, contact_name='زبون',
                                          contact_phone='01000000001', created_by=self.pharm)

    def _image(self, res, data=None):
        return ReservationImage.objects.create(
            reservation=res, image=SimpleUploadedFile(f'{SECRET}.png', data or _png(), content_type='image/png'))

    def _on_disk(self, name):
        return self.media / name

    def _hold_files(self):
        return [p for p in self.hold.rglob('*') if p.is_file()] if self.hold.exists() else []


class DeleteTests(FollowCase):
    def test_deleted_prescription_held_with_who_and_when(self):
        res = self._reservation()
        img = self._image(res)
        name, data = img.image.name, self._on_disk(img.image.name).read_bytes()
        client = bearer_client(self.pharm_user)          # the real JWT path, as in production
        with self.captureOnCommitCallbacks(execute=True):
            r = client.delete(f'{RES_URL}{res.pk}/images/{img.pk}/delete/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(self._on_disk(name).exists())
        held = HeldFile.objects.get()
        self.assertEqual(held.rule_key, 'record_deleted')
        self.assertEqual(held.deleted_by, self.pharm)
        self.assertEqual(held.primary_model, 'reservations.ReservationImage')
        self.assertEqual(held.primary_pk, str(img.pk))
        self.assertEqual(held.primary_field, 'image')
        self.assertEqual(held.original_path, name)
        self.assertEqual(held.purge_after, held.moved_at + datetime.timedelta(days=HOLD_DAYS))
        self.assertEqual((self.hold / held.hold_path).read_bytes(), data)

    def test_purged_after_30_days_with_row_gone(self):
        img = self._image(self._reservation())
        with self.captureOnCommitCallbacks(execute=True):
            img.delete()
        held = HeldFile.objects.get()
        self.assertEqual(holding.purge_expired(now=held.moved_at + datetime.timedelta(days=29)), 0)
        self.assertTrue((self.hold / held.hold_path).exists())
        self.assertEqual(holding.purge_expired(now=held.moved_at + datetime.timedelta(days=31)), 1)
        held.refresh_from_db()
        self.assertIsNotNone(held.purged_at)
        self.assertFalse((self.hold / held.hold_path).exists())

    def test_rollback_moves_nothing(self):
        img = self._image(self._reservation())
        name = img.image.name
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    img.delete()
                    raise RuntimeError('rolled back')
        self.assertTrue(self._on_disk(name).exists())
        self.assertFalse(HeldFile.objects.exists())

    def test_shared_path_not_moved(self):
        res = self._reservation()
        img = self._image(res)
        ReservationImage.objects.create(reservation=res, image=img.image.name)
        with self.captureOnCommitCallbacks(execute=True):
            img.delete()
        self.assertTrue(self._on_disk(img.image.name).exists())
        self.assertFalse(HeldFile.objects.exists())

    def test_hold_failure_does_not_break_delete(self):
        res = self._reservation()
        img = self._image(res)
        name = img.image.name
        client = bearer_client(self.pharm_user)
        with override_settings(LIFECYCLE_HOLD_ROOT=self.media / 'hold'), \
                self.assertLogs('elrezeiky.sync', 'WARNING') as logs, \
                self.captureOnCommitCallbacks(execute=True):
            r = client.delete(f'{RES_URL}{res.pk}/images/{img.pk}/delete/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ReservationImage.objects.filter(pk=img.pk).exists())
        self.assertTrue(self._on_disk(name).exists())
        self.assertFalse(HeldFile.objects.exists())
        text = '\n'.join(logs.output)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(Path(name).name, text)
        self.assertIn('record_deleted', text)

    def test_cascade_delete_holds_children(self):
        res = self._reservation()
        first, second = self._image(res), self._image(res, _png((0, 255, 0)))
        names = {first.image.name, second.image.name}
        with self.captureOnCommitCallbacks(execute=True):
            res.delete()
        held = HeldFile.objects.filter(rule_key=RECORD_DELETED)
        self.assertEqual({h.original_path for h in held}, names)
        self.assertEqual({h.primary_pk for h in held}, {str(first.pk), str(second.pk)})
        for name in names:
            self.assertFalse(self._on_disk(name).exists())


class ReplaceTests(FollowCase):
    def _order(self):
        return SoftechSalesOrder.objects.create(branch=self.branch, softech_branchcode='130', store_code='130',
                                                softech_pic='130HD9668')

    def _upload(self, order, colour):
        f = SimpleUploadedFile(f'{SECRET}.png', _png(colour), content_type='image/png')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.admin_c.post(f'/api/pos-orders/{order.pk}/prescription/', {'prescription_image': f},
                                  format='multipart')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r))
        order.refresh_from_db()
        return order.prescription_image.name

    def test_replaced_pos_prescription_held(self):
        order = self._order()
        first = self._upload(order, (255, 0, 0))
        first_bytes = self._on_disk(first).read_bytes()
        self.assertFalse(HeldFile.objects.exists())
        second = self._upload(order, (0, 0, 255))
        self.assertNotEqual(first, second)
        held = HeldFile.objects.get()
        self.assertEqual(held.rule_key, 'file_replaced')
        self.assertEqual(held.deleted_by, self.admin)
        self.assertEqual(held.original_path, first)
        self.assertEqual(held.primary_model, 'pos_orders.SoftechSalesOrder')
        self.assertEqual(held.primary_field, 'prescription_image')
        self.assertEqual((self.hold / held.hold_path).read_bytes(), first_bytes)
        self.assertFalse(self._on_disk(first).exists())
        self.assertTrue(self._on_disk(second).exists())

    def test_stale_full_save_does_not_hold_live_file(self):
        order = self._order()
        first = self._upload(order, (255, 0, 0))
        stale = SoftechSalesOrder.objects.get(pk=order.pk)      # loaded before the next replacement
        second = self._upload(order, (0, 0, 255))               # holds `first`
        self.assertEqual(HeldFile.objects.get().original_path, first)
        with self.captureOnCommitCallbacks(execute=True):
            stale.save()                                        # a full save that changed no file field
        self.assertTrue(self._on_disk(second).exists())
        self.assertFalse(HeldFile.objects.filter(original_path=second).exists())
        self.assertEqual(HeldFile.objects.count(), 1)

    def test_change_after_save_is_still_held(self):
        # the note is refreshed after a save, so a later change on the same instance is seen
        order = self._order()
        order.prescription_image = SimpleUploadedFile(f'{SECRET}.png', _png(), content_type='image/png')
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        first = order.prescription_image.name
        self.assertFalse(HeldFile.objects.exists())
        order.prescription_image = None
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        self.assertEqual(HeldFile.objects.get().original_path, first)

    def test_staff_clear_shows_no_retention_note(self):
        order = self._order()
        self._upload(order, (255, 0, 0))
        order.prescription_image = None
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        self.assertEqual(HeldFile.objects.get().rule_key, FILE_REPLACED)
        order.refresh_from_db()
        self.assertFalse(order.prescription_image)
        self.assertEqual(removed_dates([order], ['prescription_image']), {})


class RestoreAndRetrieveTests(FollowCase):
    def _held(self):
        img = self._image(self._reservation())
        data = self._on_disk(img.image.name).read_bytes()
        with self.captureOnCommitCallbacks(execute=True):
            img.delete()
        return HeldFile.objects.get(), data

    def test_restore_refused_for_staff_hold(self):
        held, data = self._held()
        with self.assertRaises(HoldError) as caught:
            holding.restore(held.pk, self.admin)
        self.assertIn('استرجاع', str(caught.exception))
        held.refresh_from_db()
        self.assertIsNone(held.restored_at)
        self.assertEqual((self.hold / held.hold_path).read_bytes(), data)
        self.assertFalse(self._on_disk(held.original_path).exists())

    def test_retrieve_returns_bytes_and_audits(self):
        held, data = self._held()
        got, name = holding.retrieve(held.pk, self.admin)
        self.assertEqual(got, data)
        self.assertEqual(name, Path(held.original_path).name)
        self.assertTrue(AuditLog.objects.filter(action='lifecycle_file_retrieved', object_id=str(held.pk)).exists())
        self.assertTrue((self.hold / held.hold_path).exists())     # a copy; the held file stays

        (self.hold / held.hold_path).write_bytes(b'changed')
        with self.assertRaises(HoldError):
            holding.retrieve(held.pk, self.admin)
        (self.hold / held.hold_path).unlink()
        with self.assertRaises(HoldError):
            holding.retrieve(held.pk, self.admin)
        HeldFile.objects.filter(pk=held.pk).update(purged_at=held.moved_at)
        with self.assertRaises(HoldError):
            holding.retrieve(held.pk, self.admin)


class NoDirectDeleteTests(TestCase):
    def test_no_direct_file_delete_left(self):
        root = Path(settings.BASE_DIR) / 'apps'
        hits = []
        for path in root.rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            parts = rel.split('/')
            if 'tests' in parts or 'migrations' in parts or parts[0] == 'data_lifecycle':
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
                if DIRECT_DELETE_PATTERN.search(line):
                    hits.append(f'{rel}:{number}')
        unexplained = [h for h in hits if h.split(':')[0] not in DIRECT_DELETE_ALLOWLIST]
        self.assertEqual(unexplained, [], 'a direct file deletion bypasses the holding folder')
        for reason in DIRECT_DELETE_ALLOWLIST.values():
            self.assertTrue(reason.strip())
