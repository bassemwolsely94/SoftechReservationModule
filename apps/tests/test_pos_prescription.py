"""
apps/tests/test_pos_prescription.py — prescription-image upload for a POS order.

PG-only metadata (never a SOFTECH write). Foundation for OCR-Rx (Phase C): the stored
image is what an OCR pass reads.
"""
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.pos_orders.models import SoftechSalesOrder
from apps.catalog.models import Item
from apps.shortage.matching import find_best_matches
from apps.vision.models import OcrSample
from .factories import make_branch, make_user, make_item

# a minimal valid 1×1 PNG
_PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
        b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
        b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


def _order(**kw):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130',
        channel='cash', **kw)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PrescriptionUploadTests(TestCase):
    def setUp(self):
        _, _, self.client_api = make_user('rx_user', role='pharmacist')

    def _png(self, name='rx.png'):
        return SimpleUploadedFile(name, _PNG, content_type='image/png')

    def test_upload_saves_image(self):
        o = _order()
        r = self.client_api.post(f'/api/pos-orders/{o.id}/prescription/',
                                 {'prescription_image': self._png()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        o.refresh_from_db()
        self.assertTrue(bool(o.prescription_image))
        self.assertIn('prescriptions/', o.prescription_image.name)

    def test_no_file_rejected(self):
        o = _order()
        r = self.client_api.post(f'/api/pos-orders/{o.id}/prescription/', {}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_wrong_type_rejected(self):
        o = _order()
        bad = SimpleUploadedFile('x.pdf', b'%PDF-1.4', content_type='application/pdf')
        r = self.client_api.post(f'/api/pos-orders/{o.id}/prescription/',
                                 {'prescription_image': bad}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_locked_order_rejected(self):
        o = _order(status='pushed')   # pushed → is_locked property is True
        r = self.client_api.post(f'/api/pos-orders/{o.id}/prescription/',
                                 {'prescription_image': self._png()}, format='multipart')
        self.assertEqual(r.status_code, 409)

    def test_missing_order_404(self):
        r = self.client_api.post('/api/pos-orders/999999/prescription/',
                                 {'prescription_image': self._png()}, format='multipart')
        self.assertEqual(r.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PrescriptionOcrTests(TestCase):
    def setUp(self):
        _, _, self.client_api = make_user('ocr_user', role='pharmacist')
        self.item = make_item(name='AUGMENTIN 1GM 14 TABLETS', softech_id='AUG1')

    def _png(self):
        return SimpleUploadedFile('rx.png', _PNG, content_type='image/png')

    def test_ocr_returns_candidates(self):
        er = {'gemini': [{'readings': ['Augmentin'], 'strength': '1g', 'qty': 2}]}
        with patch('apps.vision.ocr.run_engines', return_value=er), \
             patch('apps.vision.ocr.build_consensus', return_value={}):
            r = self.client_api.post('/api/pos-orders/prescription-ocr/',
                                     {'image': self._png()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['lines']), 1)
        line = r.data['lines'][0]
        self.assertEqual(line['qty'], 2)
        self.assertIn('AUG1', [c['softech_id'] for c in line['candidates']])

    def test_ocr_no_file_rejected(self):
        r = self.client_api.post('/api/pos-orders/prescription-ocr/', {}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_ocr_unreadable_returns_empty(self):
        # every engine failed → no readings → empty
        with patch('apps.vision.ocr.run_engines', return_value={}):
            r = self.client_api.post('/api/pos-orders/prescription-ocr/',
                                     {'image': self._png()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['lines'], [])

    def test_teach_pins_alias(self):
        # after a human confirms a reading→item, that exact reading resolves INSTANTLY,
        # pinned at the top with learned=True (score 1.0) — the flywheel.
        raw = 'ogmentin fort'
        pre = find_best_matches(raw)
        self.assertFalse(any(m.get('learned') for m in pre))   # not learned yet
        r = self.client_api.post('/api/pos-orders/prescription-ocr/teach/',
                                 {'raw_name': raw, 'item_id': self.item.id})
        self.assertEqual(r.status_code, 200)
        top = find_best_matches(raw)[0]                        # now pinned by the learned alias
        self.assertEqual(top['item_softech_id'], 'AUG1')
        self.assertTrue(top.get('learned'))
        self.assertEqual(top['score'], 1.0)

    def test_teach_requires_fields(self):
        r = self.client_api.post('/api/pos-orders/prescription-ocr/teach/', {'raw_name': ''})
        self.assertEqual(r.status_code, 400)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class VoiceEntryTests(TestCase):
    def setUp(self):
        _, _, self.client_api = make_user('voice_user', role='pharmacist')
        self.item = make_item(name='AUGMENTIN 1GM 14 TABLETS', softech_id='AUG1')

    def _audio(self):
        return SimpleUploadedFile('voice.webm', b'\x1aE\xdf\xa3fake', content_type='audio/webm')

    def test_voice_returns_candidates(self):
        fake = [{'readings': ['Augmentin'], 'strength': '1g', 'qty': 1}]
        with patch('apps.pos_orders.views._voice_items_gemini', return_value=fake):
            r = self.client_api.post('/api/pos-orders/voice-entry/',
                                     {'audio': self._audio()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['lines']), 1)
        self.assertIn('AUG1', [c['softech_id'] for c in r.data['lines'][0]['candidates']])

    def test_voice_no_file_rejected(self):
        r = self.client_api.post('/api/pos-orders/voice-entry/', {}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_voice_unheard_returns_empty(self):
        with patch('apps.pos_orders.views._voice_items_gemini', return_value=[]):
            r = self.client_api.post('/api/pos-orders/voice-entry/',
                                     {'audio': self._audio()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['lines'], [])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class OcrCorpusTests(TestCase):
    """Phase 1 in-house OCR corpus — every OCR/voice event + confirmation is banked."""
    def setUp(self):
        _, _, self.client_api = make_user('corpus_user', role='pharmacist')
        self.item = make_item(name='AUGMENTIN 1GM 14 TABLETS', softech_id='AUG1')

    def test_ocr_banks_image_sample_and_teach_labels_it(self):
        png = SimpleUploadedFile('rx.png', _PNG, content_type='image/png')
        er = {'gemini': [{'readings': ['Augmentin'], 'strength': '1g', 'qty': 1}]}
        with patch('apps.vision.ocr.run_engines', return_value=er), \
             patch('apps.vision.ocr.build_consensus', return_value={}):
            r = self.client_api.post('/api/pos-orders/prescription-ocr/', {'image': png}, format='multipart')
        sid = r.data['sample_id']
        self.assertIsNotNone(sid)
        s = OcrSample.objects.get(pk=sid)
        self.assertEqual(s.module, 'pos_rx')
        self.assertEqual(s.media_type, 'image')
        self.assertTrue(bool(s.image))
        self.assertEqual(s.raw_readings, er['gemini'])
        self.assertEqual(s.engine_readings, er)
        self.assertFalse(s.is_labelled)
        # confirm → the sample gets the ground-truth label
        self.client_api.post('/api/pos-orders/prescription-ocr/teach/',
                             {'raw_name': 'Augmentin 1g', 'item_id': self.item.id, 'sample_id': sid})
        s.refresh_from_db()
        self.assertTrue(s.is_labelled)
        self.assertEqual(s.confirmations[0]['softech_id'], 'AUG1')

    def test_voice_banks_audio_sample(self):
        audio = SimpleUploadedFile('v.webm', b'\x1aE\xdf\xa3x', content_type='audio/webm')
        fake = [{'readings': ['Augmentin'], 'strength': '', 'qty': None}]
        with patch('apps.pos_orders.views._voice_items_gemini', return_value=fake):
            r = self.client_api.post('/api/pos-orders/voice-entry/', {'audio': audio}, format='multipart')
        s = OcrSample.objects.get(pk=r.data['sample_id'])
        self.assertEqual(s.module, 'pos_voice')
        self.assertEqual(s.media_type, 'audio')
        self.assertTrue(bool(s.audio))
