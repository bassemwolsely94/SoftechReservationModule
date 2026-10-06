"""
apps/tests/test_vision_ocr.py — P2 recognition chain: Gemini → in-house EasyOCR →
Tesseract, with the winning engine reported for the corpus.
"""
import io
from unittest.mock import patch
from django.test import TestCase

from apps.vision.ocr import recognize, run_engines, build_consensus
from apps.vision.models import OcrSample
from .factories import make_item, make_user


class RecognizeChainTests(TestCase):
    def _img(self):
        return io.BytesIO(b'fake-image-bytes')

    def test_gemini_wins_when_available(self):
        g = (['Augmentin 1g'], 'gemini/x', '', [{'readings': ['Augmentin'], 'strength': '1g', 'qty': 1}])
        with patch('apps.shortage.views._ocr_gemini', return_value=g):
            readings, engine = recognize(self._img(), api_key='key')
        self.assertEqual(engine, 'gemini')
        self.assertEqual(readings[0]['readings'], ['Augmentin'])

    def test_falls_to_inhouse_easyocr(self):
        with patch('apps.shortage.views._ocr_gemini', return_value=(None, None, None, None)), \
             patch('apps.shortage.views._ocr_easyocr', return_value=(['Panadol', 'Aerius'], 'easyocr', 'raw', None)):
            readings, engine = recognize(self._img(), api_key='key')
        self.assertEqual(engine, 'easyocr')
        self.assertEqual([r['readings'][0] for r in readings], ['Panadol', 'Aerius'])

    def test_no_api_key_skips_gemini(self):
        with patch('apps.shortage.views._ocr_easyocr', return_value=(['X'], 'easyocr', 'r', None)):
            readings, engine = recognize(self._img(), api_key='')
        self.assertEqual(engine, 'easyocr')

    def test_all_fail_returns_empty(self):
        with patch('apps.shortage.views._ocr_gemini', return_value=(None, None, None, None)), \
             patch('apps.shortage.views._ocr_easyocr', return_value=(None, None, None, None)), \
             patch('apps.shortage.views._clean_ocr_lines', return_value=[]):
            readings, engine = recognize(self._img(), api_key='key')
        self.assertEqual(readings, [])
        self.assertEqual(engine, '')


class ParallelEnsembleTests(TestCase):
    def _img(self):
        return io.BytesIO(b'fake')

    def test_run_engines_runs_all_available(self):
        g = (['Augmentin'], 'g', '', [{'readings': ['Augmentin'], 'strength': '', 'qty': None}])
        e = (['Panadol'], 'easyocr', 'raw', None)
        with patch('apps.shortage.views._ocr_gemini', return_value=g), \
             patch('apps.shortage.views._ocr_easyocr', return_value=e):
            out = run_engines(self._img(), api_key='key')
        self.assertIn('gemini', out)
        self.assertIn('easyocr', out)

    def test_consensus_maps_item_to_agreeing_engines(self):
        it = make_item(name='AUGMENTIN 1GM 14 TABLETS', softech_id='AUG1')
        er = {'gemini':  [{'readings': ['Augmentin'], 'strength': '', 'qty': None}],
              'easyocr': [{'readings': ['Augmentin'], 'strength': '', 'qty': None}]}
        cons = build_consensus(er)
        self.assertIn(it.id, cons)
        self.assertEqual(cons[it.id], ['easyocr', 'gemini'])


class AccuracyEndpointTests(TestCase):
    def setUp(self):
        _, _, self.client_api = make_user('acc_user', role='admin')
        self.item = make_item(name='AUGMENTIN 1GM 14 TABLETS', softech_id='AUG1')
        self.other = make_item(name='PANADOL EXTRA 24 TABLETS', softech_id='PAN1')

    def test_per_engine_recall(self):
        OcrSample.objects.create(
            module='pos_rx', engine='gemini',
            engine_readings={
                'gemini':  [{'readings': ['Augmentin'], 'strength': '', 'qty': None}],   # → AUG1 (confirmed)
                'easyocr': [{'readings': ['Panadol'], 'strength': '', 'qty': None}],      # → PAN1 (not confirmed)
            },
            confirmations=[{'item_id': self.item.id, 'softech_id': 'AUG1', 'name': 'x'}])
        r = self.client_api.get('/api/vision/corpus-accuracy/')
        self.assertEqual(r.status_code, 200)
        by = {x['engine']: x for x in r.data['results']}
        self.assertEqual(by['gemini']['recall'], 1.0)     # Gemini resolved the confirmed item
        self.assertEqual(by['easyocr']['recall'], 0.0)    # in-house resolved a different item
