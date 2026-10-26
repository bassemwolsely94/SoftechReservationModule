"""
Tests for Gemini key rotation + per-(key,model) quota cooldown (apps.invoices.ocr).

The free tier is 20 req/day/model/project; a 2nd key doubles it, and a 429'd pair
must be cooled instead of re-hit every call. The genai client is faked so none of
this touches the network.
"""
import types as _t

from django.test import SimpleTestCase

from apps.invoices import ocr


def _fake_factory(behavior, calls):
    """Return a _genai_client replacement whose generate_content consults
    ``behavior`` ({(key, model): '429'|'err'|'ok'}) and records every call."""
    def make(key):
        class _Models:
            def generate_content(self, model, contents, **kw):
                calls.append((key, model))
                b = behavior.get((key, model), 'ok')
                if b == '429':
                    raise RuntimeError('429 RESOURCE_EXHAUSTED "retryDelay": "60"')
                if b == 'err':
                    raise RuntimeError('500 boom')
                return _t.SimpleNamespace(text='{"lines":[]}')

        class _Client:
            models = _Models()
        return _Client()
    return make


class GeminiRotationTests(SimpleTestCase):

    def setUp(self):
        self._orig_client = ocr._genai_client
        self._orig_keys = ocr._gemini_keys
        ocr._gemini_cooldown.clear()
        ocr._gemini_keys = lambda: ['K1', 'K2']

    def tearDown(self):
        ocr._genai_client = self._orig_client
        ocr._gemini_keys = self._orig_keys
        ocr._gemini_cooldown.clear()

    def _patch(self, behavior):
        self.calls = []
        ocr._genai_client = _fake_factory(behavior, self.calls)

    def test_falls_to_next_model_and_cools_the_429_pair(self):
        self._patch({('K1', ocr._GEMINI_MODELS[0]): '429'})
        resp, used = ocr._gemini_generate(['x'])
        self.assertIsNotNone(resp)
        self.assertEqual(used, f'key#1/{ocr._GEMINI_MODELS[1]}')
        self.assertGreater(ocr._gemini_cooldown.get((0, ocr._GEMINI_MODELS[0]), 0), 0)

    def test_rotates_to_second_key_when_first_key_exhausted(self):
        self._patch({('K1', m): '429' for m in ocr._GEMINI_MODELS})
        resp, used = ocr._gemini_generate(['x'])
        self.assertIsNotNone(resp)
        self.assertEqual(used, f'key#2/{ocr._GEMINI_MODELS[0]}')
        # every K1 pair got cooled
        for m in ocr._GEMINI_MODELS:
            self.assertGreater(ocr._gemini_cooldown.get((0, m), 0), 0)

    def test_cooled_pair_is_skipped_not_called(self):
        import time
        ocr._gemini_cooldown[(0, ocr._GEMINI_MODELS[0])] = time.time() + 1000
        self._patch({})            # everything would succeed if called
        resp, used = ocr._gemini_generate(['x'])
        self.assertIsNotNone(resp)
        self.assertNotIn(('K1', ocr._GEMINI_MODELS[0]), self.calls)   # skipped
        self.assertEqual(used, f'key#1/{ocr._GEMINI_MODELS[1]}')

    def test_non_quota_error_does_not_cool(self):
        self._patch({('K1', ocr._GEMINI_MODELS[0]): 'err'})
        ocr._gemini_generate(['x'])
        self.assertNotIn((0, ocr._GEMINI_MODELS[0]), ocr._gemini_cooldown)

    def test_all_cooled_returns_none(self):
        import time
        for ki in (0, 1):
            for m in ocr._GEMINI_MODELS:
                ocr._gemini_cooldown[(ki, m)] = time.time() + 1000
        self._patch({})
        resp, used = ocr._gemini_generate(['x'])
        self.assertIsNone(resp)
        self.assertEqual(self.calls, [])          # nothing hit the API

    def test_no_keys_returns_none(self):
        ocr._gemini_keys = lambda: []
        self._patch({})
        self.assertEqual(ocr._gemini_generate(['x']), (None, None))
