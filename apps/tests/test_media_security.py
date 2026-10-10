"""
apps/tests/test_media_security.py

Uploaded files (prescriptions, insurance docs, payment proofs …) need a signed,
unexpired URL; product imagery stays public. See core/storage.py, core/media.py.
"""
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings

from core.storage import (
    SignedMediaStorage, is_public_media, media_signature, sign_media_name,
    verify_media_signature,
)

_TMP = tempfile.mkdtemp(prefix='media-test-')


@override_settings(MEDIA_ROOT=_TMP, MEDIA_ACCEL_REDIRECT=False)
class SignedMediaTests(SimpleTestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        self.private = default_storage.save('pos_orders/prescriptions/2026/10/rx.jpg',
                                            ContentFile(b'RX-IMAGE'))
        self.public = default_storage.save('products/123/media/p.jpg', ContentFile(b'PRODUCT'))

    def tearDown(self):
        for n in (self.private, self.public):
            default_storage.delete(n)

    def _get(self, url):
        parts = urlsplit(url)
        return self.client.get(parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()})

    # ── storage ────────────────────────────────────────────────────────────
    def test_default_storage_is_signed(self):
        self.assertIsInstance(default_storage, SignedMediaStorage)

    def test_private_url_is_signed_and_public_is_not(self):
        q = parse_qs(urlsplit(default_storage.url(self.private)).query)
        self.assertEqual(set(q), {'exp', 'sig'})
        self.assertEqual(urlsplit(default_storage.url(self.public)).query, '')

    def test_public_prefixes(self):
        for name in ('products/1/og/a.jpg', 'image_candidates/2026/1/a.jpg', 'insurance/watermarks/w.png'):
            self.assertTrue(is_public_media(name), name)
        for name in ('pos_orders/prescriptions/a.jpg', 'payments/screenshots/a.png',
                     'hr/receipts/a.jpg', 'reports/overstock.xlsx', 'insurance/claims/a.pdf'):
            self.assertFalse(is_public_media(name), name)

    def test_url_stable_within_the_hour(self):
        t = 1_800_000_000
        self.assertEqual(sign_media_name('a/b.jpg', now=t), sign_media_name('a/b.jpg', now=t + 60))

    def test_signature_checks(self):
        signed = sign_media_name('a/b.jpg')
        self.assertTrue(verify_media_signature('a/b.jpg', signed['exp'], signed['sig']))
        self.assertFalse(verify_media_signature('a/c.jpg', signed['exp'], signed['sig']))   # other file
        self.assertFalse(verify_media_signature('a/b.jpg', signed['exp'] + 3600, signed['sig']))  # extended
        self.assertFalse(verify_media_signature('a/b.jpg', 'x', signed['sig']))
        self.assertFalse(verify_media_signature('a/b.jpg', signed['exp'], 'ﻻ'))
        past = int(time.time()) - 10
        self.assertFalse(verify_media_signature('a/b.jpg', past, media_signature('a/b.jpg', past)))

    # ── serving ────────────────────────────────────────────────────────────
    def test_private_file_needs_signature(self):
        self.assertEqual(self.client.get(f'/media/{self.private}').status_code, 403)
        self.assertEqual(self.client.get(f'/media/{self.private}', {'exp': '9999999999', 'sig': 'x'}).status_code, 403)

    def test_signed_url_serves_file(self):
        r = self._get(default_storage.url(self.private))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'RX-IMAGE')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', r['Cache-Control'])

    def test_public_file_served_without_signature(self):
        r = self.client.get(f'/media/{self.public}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'PRODUCT')

    def test_traversal_and_missing(self):
        self.assertIn(self.client.get('/media/products/../../config/settings.py').status_code, (403, 404))
        self.assertEqual(self.client.get('/media/products/nope.jpg').status_code, 404)

    def test_script_capable_upload_is_sandboxed_download(self):
        name = default_storage.save('chatter/2026/10/evil.svg', ContentFile(b'<svg onload="alert(1)"/>'))
        try:
            r = self._get(default_storage.url(name))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Security-Policy'], 'sandbox')
            self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        finally:
            default_storage.delete(name)

    @override_settings(MEDIA_ACCEL_REDIRECT=True)
    def test_nginx_mode_hands_file_back_to_nginx(self):
        r = self._get(default_storage.url(self.private))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['X-Accel-Redirect'], f'/protected-media/{self.private}')
        self.assertEqual(r.content, b'')

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post(f'/media/{self.public}').status_code, 405)
