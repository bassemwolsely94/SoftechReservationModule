"""
Data lifecycle Stage 4, Task 1: new photos are shrunk on upload, and only the listed fields.

Invoice scans and OCR sample images must stay byte for byte (they are the evidence and the training data).
"""
import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.callcenter.models import CallLog, CallLogAttachment
from apps.data_lifecycle import register, uploads
from apps.invoices.models import SupplierInvoice
from apps.reservations.models import Reservation, ReservationImage
from apps.tasks.models import OperationalTask, TaskAttachment
from apps.vision.models import OcrSample
from core.upload_safety import shrink_image

from .factories import make_branch


def _jpeg(size=(4000, 3000), exif_orientation=None, quality=95):
    # noise so the big file is genuinely large and a resize is genuinely smaller
    img = Image.effect_noise(size, 60).convert('RGB')
    buf = io.BytesIO()
    kwargs = {'format': 'JPEG', 'quality': quality}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs['exif'] = exif.tobytes()
    img.save(buf, **kwargs)
    return buf.getvalue()


def _gif_two_frames():
    frames = [Image.new('P', (3000, 3000), 0), Image.new('P', (3000, 3000), 1)]
    buf = io.BytesIO()
    frames[0].save(buf, format='GIF', save_all=True, append_images=frames[1:])
    return buf.getvalue()


class UploadShrinkCase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        settings = override_settings(MEDIA_ROOT=self.tmp)
        settings.enable()
        self.addCleanup(settings.disable)
        self.branch = make_branch()

    def _reservation(self):
        return Reservation.objects.create(branch=self.branch, contact_phone='01000000000', contact_name='x',
                                          manual_item_name='x')

    def _stored(self, field_file):
        with field_file.storage.open(field_file.name, 'rb') as fh:
            return fh.read()

    def _reservation_image(self, data, name='a.jpg'):
        obj = ReservationImage(reservation=self._reservation())
        obj.image = SimpleUploadedFile(name, data, content_type='image/jpeg')
        obj.save()
        return obj

    def _task_attachment(self, data, name='a.jpg'):
        task = OperationalTask.objects.create(title='t')
        obj = TaskAttachment(task=task)
        obj.file = SimpleUploadedFile(name, data)
        obj.save()
        return obj

    def _call_attachment(self, data, name):
        log = CallLog.objects.create(phone_number='01000000000', direction='inbound')
        obj = CallLogAttachment(call_log=log)
        obj.file = SimpleUploadedFile(name, data)
        obj.save()
        return obj

    def test_prescription_photo_shrinks_to_2000(self):
        data = _jpeg()
        obj = self._reservation_image(data)
        stored = self._stored(obj.image)
        self.assertEqual(max(Image.open(io.BytesIO(stored)).size), 2000)
        self.assertLess(len(stored), len(data))

    def test_chat_photo_shrinks_to_1600(self):
        data = _jpeg()
        obj = self._task_attachment(data)
        stored = self._stored(obj.file)
        self.assertEqual(max(Image.open(io.BytesIO(stored)).size), 1600)
        self.assertLess(len(stored), len(data))

    def test_invoice_scan_unchanged_byte_for_byte(self):
        data = _jpeg()
        inv = SupplierInvoice(branch=self.branch)
        inv.source_image = SimpleUploadedFile('scan.jpg', data)
        inv.save()
        self.assertEqual(self._stored(inv.source_image), data)
        sample = OcrSample(module='pos_rx')
        sample.image = SimpleUploadedFile('s.jpg', data)
        sample.save()
        self.assertEqual(self._stored(sample.image), data)

    def test_small_photo_unchanged(self):
        data = _jpeg((1200, 900))
        obj = self._reservation_image(data)
        self.assertEqual(self._stored(obj.image), data)

    def test_not_an_image_unchanged(self):
        for name, data in (('a.pdf', b'%PDF-1.4\n' + b'x' * 5000), ('b.bin', bytes(range(256)) * 40),
                           ('c.gif', _gif_two_frames())):
            with self.subTest(name=name):
                obj = self._call_attachment(data, name)
                self.assertEqual(self._stored(obj.file), data)

    def test_exif_orientation_applied(self):
        data = _jpeg(exif_orientation=6)
        obj = self._reservation_image(data)
        self.assertEqual(Image.open(io.BytesIO(self._stored(obj.image))).size, (1500, 2000))

    def test_shrink_image_returns_none_when_left_alone(self):
        self.assertIsNone(shrink_image(b'junk', 2000))
        self.assertIsNone(shrink_image(_jpeg((1200, 900)), 2000))

    def test_icc_profile_survives_shrink(self):
        from PIL import ImageCms
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        buf = io.BytesIO()
        Image.effect_noise((3000, 2400), 60).convert('RGB').save(buf, format='JPEG', quality=95, icc_profile=profile)
        out = shrink_image(buf.getvalue(), 2000)
        self.assertIsNotNone(out)
        self.assertEqual(Image.open(io.BytesIO(out)).info.get('icc_profile'), profile)

    def test_cmyk_jpeg_returns_none(self):
        buf = io.BytesIO()
        Image.new('CMYK', (2400, 2200), (10, 20, 30, 40)).save(buf, format='JPEG')
        self.assertIsNone(shrink_image(buf.getvalue(), 2000))

    def test_multiframe_mpo_is_shrunk_as_jpeg(self):
        frames = [Image.effect_noise((3000, 2400), 60).convert('RGB') for _ in range(2)]
        buf = io.BytesIO()
        try:
            frames[0].save(buf, format='MPO', save_all=True, append_images=frames[1:])
        except Exception as exc:
            self.skipTest(f'this Pillow cannot write MPO: {exc}')
        data = buf.getvalue()
        if Image.open(io.BytesIO(data)).format != 'MPO':
            self.skipTest('Pillow wrote a plain JPEG, not an MPO')
        out = shrink_image(data, 2000)
        self.assertIsNotNone(out)
        im = Image.open(io.BytesIO(out))
        self.assertEqual((im.format, max(im.size)), ('JPEG', 2000))

    def test_shrink_list_is_classified(self):
        classified = register.classified_file_fields()
        for key in uploads.SHRINK_LONGEST_SIDE:
            self.assertIn(key, classified)
            self.assertFalse(key.startswith(('invoices.', 'vision.')))

    def test_fieldfile_save_sites_not_shrink_listed(self):
        # these paths use FieldFile.save() and skip pre_save, so listing them would be a silent no-op
        for key in ('images.ImageCandidate.local_file', 'product_experience.ProductMedia.file',
                    'product_experience.ProductMedia.thumbnail', 'invoices.SupplierInvoice.source_image'):
            self.assertNotIn(key, uploads.SHRINK_LONGEST_SIDE)
