"""
Tests for the pluggable OCR engine registry (apps.invoices.engines) and the
registry-driven dispatch in ocr.extract_structured_images.

Registry mutations are snapshotted/restored so tests don't leak into each other or
into the real built-in registrations.
"""
from django.test import SimpleTestCase

from apps.invoices import engines, ocr


class _Reg:
    """Snapshot/restore the global engine registry around a test."""
    def __enter__(self):
        self._saved = dict(engines._ENGINES)
        return self

    def __exit__(self, *a):
        engines._ENGINES.clear()
        engines._ENGINES.update(self._saved)


def _spec(name, kind, prio, avail, result='RESULT'):
    return engines.EngineSpec(name, kind, prio, lambda: avail,
                              lambda p, v, h: ({'engine': name, 'lines': [result]} if result else None))


class RegistryTests(SimpleTestCase):

    def test_builtins_registered_free_first(self):
        specs = engines.all_engine_specs()
        names = [s.name for s in specs]
        self.assertEqual(names[:3], ['tesseract', 'paddleocr', 'easyocr'])   # free, by priority
        self.assertEqual([s.name for s in specs if s.kind == 'api'], ['gemini', 'mistral', 'vlm'])
        # free block precedes api block
        kinds = [s.kind for s in specs]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: k != 'free'))

    def test_register_and_get(self):
        with _Reg():
            engines.register_engine(_spec('zzz', 'free', 99, True))
            self.assertIsNotNone(engines.get_engine('zzz'))
            self.assertIsNone(engines.get_engine('nope'))

    def test_best_free_engine_picks_lowest_priority_available(self):
        with _Reg():
            engines._ENGINES.clear()
            engines.register_engine(_spec('slow', 'free', 30, True))
            engines.register_engine(_spec('fast', 'free', 10, True))
            engines.register_engine(_spec('down', 'free', 5, False))   # unavailable
            self.assertEqual(engines.best_free_engine(), 'fast')

    def test_resolve_engine_auto_prefers_api_then_free(self):
        with _Reg():
            engines._ENGINES.clear()
            engines.register_engine(_spec('freeeng', 'free', 10, True))
            engines.register_engine(_spec('apieng', 'api', 10, True))
            self.assertEqual(engines.resolve_engine('auto'), 'apieng')
        with _Reg():
            engines._ENGINES.clear()
            engines.register_engine(_spec('freeeng', 'free', 10, True))
            self.assertEqual(engines.resolve_engine('auto'), 'freeeng')

    def test_resolve_engine_explicit_registered_name_wins(self):
        with _Reg():
            engines._ENGINES.clear()
            engines.register_engine(_spec('freeeng', 'free', 10, True))
            engines.register_engine(_spec('apieng', 'api', 10, True))
            self.assertEqual(engines.resolve_engine('freeeng'), 'freeeng')

    def test_available_lists_filter_by_availability(self):
        with _Reg():
            engines._ENGINES.clear()
            engines.register_engine(_spec('up', 'free', 10, True))
            engines.register_engine(_spec('down', 'free', 20, False))
            engines.register_engine(_spec('api_up', 'api', 10, True))
            self.assertEqual([s.name for s in engines.available_free_specs()], ['up'])
            self.assertEqual([s.name for s in engines.available_api_specs()], ['api_up'])
            self.assertCountEqual(engines.available_engines(), ['up', 'api_up'])


class DispatchTests(SimpleTestCase):

    def test_explicit_engine_routes_to_its_run(self):
        with _Reg():
            engines.register_engine(_spec('fakeeng', 'free', 50, True, result='LINE'))
            out = ocr.extract_structured_images(['p1.png'], engine='fakeeng')
            self.assertEqual(out, {'engine': 'fakeeng', 'lines': ['LINE']})

    def test_unknown_engine_falls_back_to_auto(self):
        # an unknown name must not crash — it falls through to auto, which runs the
        # best free engine. Scoring is stubbed so the free result is accepted as-is.
        saved = (engines.score_extraction, engines.recall_ok, engines.confidence_ok)
        engines.score_extraction = lambda d: 1.0
        engines.recall_ok = lambda d: True
        engines.confidence_ok = lambda d: True
        try:
            with _Reg():
                engines._ENGINES.clear()
                engines.register_engine(_spec('freeeng', 'free', 10, True, result='X'))
                out = ocr.extract_structured_images(['p1.png'], engine='does-not-exist')
                self.assertEqual(out, {'engine': 'freeeng', 'lines': ['X']})
        finally:
            engines.score_extraction, engines.recall_ok, engines.confidence_ok = saved


class MistralGatingTests(SimpleTestCase):

    def test_mistral_unavailable_without_key(self):
        # no MISTRAL_API_KEY in the test env → spec reports unavailable, never called
        self.assertFalse(ocr._mistral_available())
        self.assertIsNone(ocr._mistral_images(['p1.png']))


class PaddleSidecarTests(SimpleTestCase):

    def test_paddleocr_available_when_sidecar_url_set(self):
        from django.test import override_settings
        with override_settings(PADDLE_OCR_URL='http://127.0.0.1:8077/boxes'):
            self.assertTrue(engines._paddleocr_available())
            self.assertEqual(engines._paddle_url(), 'http://127.0.0.1:8077/boxes')

    def test_paddle_http_boxes_empty_without_url(self):
        from django.test import override_settings
        with override_settings(PADDLE_OCR_URL=''):
            self.assertEqual(engines._paddle_http_boxes(object()), [])
