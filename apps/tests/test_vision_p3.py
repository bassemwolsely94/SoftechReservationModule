"""
apps/tests/test_vision_p3.py — P3 foundation: corpus → training dataset export, and the
in-house model inference slot (safe/no-op until a model is trained).
"""
import io
import json
import os
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.vision.models import OcrSample
from apps.vision.dataset import build_dataset, dataset_readiness
from apps.vision.ocr import run_engines

_PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
        b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
        b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DatasetExportTests(TestCase):
    def _sample(self, confs, name='a.png'):
        return OcrSample.objects.create(
            module='pos_rx', media_type='image',
            image=SimpleUploadedFile(name, _PNG, content_type='image/png'),
            confirmations=confs)

    def test_export_builds_image_text_manifest(self):
        self._sample([{'name': 'AUGMENTIN', 'item_id': 1, 'softech_id': 'AUG1'}])
        out = tempfile.mkdtemp()
        stats = build_dataset(out_dir=out)
        self.assertEqual(stats['exported'], 1)
        rows = [json.loads(l) for l in open(stats['manifest'], encoding='utf-8')]
        self.assertEqual(rows[0]['text'], ['AUGMENTIN'])
        self.assertTrue(os.path.exists(os.path.join(out, rows[0]['image'])))

    def test_unlabelled_not_exported(self):
        self._sample([], name='b.png')     # no confirmations → excluded from the dataset
        stats = build_dataset(out_dir=tempfile.mkdtemp())
        self.assertEqual(stats['exported'], 0)

    def test_readiness_counts_labelled_images(self):
        self._sample([{'name': 'X', 'item_id': 1}], name='c.png')
        self.assertEqual(dataset_readiness('pos_rx')['labelled_images'], 1)


class InhouseSlotTests(TestCase):
    def test_recognize_inhouse_none_without_model(self):
        from apps.vision.inhouse import recognize_inhouse, is_available
        self.assertIsNone(recognize_inhouse(b'imagebytes'))
        self.assertFalse(is_available())

    def test_run_engines_omits_inhouse_without_model(self):
        g = (['X'], 'g', '', [{'readings': ['X'], 'strength': '', 'qty': None}])
        with patch('apps.shortage.views._ocr_gemini', return_value=g), \
             patch('apps.shortage.views._ocr_easyocr', return_value=(None, None, None, None)):
            out = run_engines(io.BytesIO(b'fake'), api_key='k')
        self.assertIn('gemini', out)
        self.assertNotIn('inhouse', out)     # no trained model → in-house engine skipped
