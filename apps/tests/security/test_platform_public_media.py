"""
Platform & abuse — files served from the PUBLIC media folders (Batch 6, W-7).

`products/`, `image_candidates/` and `insurance/watermarks/` are served without a signed link
(product pictures are shared on WhatsApp and the portal). Before: the product-image upload trusted
the browser's content type and kept the client's file extension, and the product-media upload took
any file; the media server and nginx sandboxed a short deny-list of script types (.html, .svg, …)
and missed others (.shtml, .xht, .xsl …) — an uploaded page could run script on our origin.

Now: an upload into a public folder must BE what it claims (an image Pillow can read, a PDF, an
MP4 / WebM video) and is named by what it is, not by the client; and serving is an allow-list —
only known-safe types display inline, everything else is a sandboxed download (Django and nginx).
"""
import io
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.product_experience.models import ProductMedia
from apps.tests.factories import make_admin, make_item

PAGE = b'<html><body><script>fetch("/api/auth/me/")</script></body></html>'


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), 'red').save(buf, format='PNG')
    return buf.getvalue()


class _TempMedia(TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        o = override_settings(MEDIA_ROOT=self.root)
        o.enable()
        self.addCleanup(o.disable)
        _, self.admin, self.c = make_admin('w7_admin')
        self.item = make_item()


class PublicUploadTests(_TempMedia):

    def _image_upload(self, name, body, ctype='image/png'):
        return self.c.post(f'/api/images/products/{self.item.pk}/upload/',
                           {'file': SimpleUploadedFile(name, body, content_type=ctype)}, format='multipart')

    def _media_upload(self, name, body, media_type='image', ctype='image/png'):
        return self.c.post(f'/api/products/{self.item.softech_id}/media/upload/',
                           {'file': SimpleUploadedFile(name, body, content_type=ctype), 'media_type': media_type},
                           format='multipart')

    def test_a_page_posing_as_an_image_is_refused(self):
        self.assertEqual(self._image_upload('evil.html', PAGE).status_code, 400)
        self.assertEqual(self._media_upload('evil.shtml', PAGE).status_code, 400)
        self.assertEqual(self._media_upload('evil.pdf', PAGE, media_type='pdf', ctype='application/pdf').status_code, 400)
        self.assertFalse(ProductMedia.objects.exists())

    def test_a_real_image_is_named_by_what_it_is(self):
        self.assertEqual(self._image_upload('photo.html', _png()).status_code, 201)
        self.assertEqual(self._media_upload('photo.xht', _png()).status_code, 201)
        names = [m.file.name for m in ProductMedia.objects.all()]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(n.endswith('.png') for n in names), names)


class PublicServingTests(_TempMedia):

    def _put(self, rel, body):
        p = Path(self.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

    def test_only_safe_types_display_inline(self):
        for rel in ('products/IT001/media/a.shtml', 'products/IT001/media/a.xht',
                    'products/IT001/media/a.xsl', 'image_candidates/a.php'):
            self._put(rel, PAGE)
            r = self.client.get(f'/media/{rel}')
            self.assertEqual(r.get('Content-Security-Policy'), 'sandbox', rel)
            self.assertTrue(r.get('Content-Disposition', '').startswith('attachment'), rel)

    def test_a_product_picture_still_displays(self):
        self._put('products/IT001/media/a.png', _png())
        r = self.client.get('/media/products/IT001/media/a.png')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get('Content-Disposition', '').startswith('attachment'))
        self.assertIsNone(r.get('Content-Security-Policy'))

    def test_nginx_public_media_is_an_allow_list(self):
        conf = (Path(settings.BASE_DIR) / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        block = conf[conf.index('location ~ ^/media/(products'):conf.index('location /protected-media/')]
        outer = block.split('location ~*')[0]
        self.assertIn('Content-Security-Policy "sandbox"', outer)        # the default is a download
        self.assertIn('Content-Disposition "attachment"', outer)
        inline = re.search(r'location ~\* \\\.\(([^)]*)\)\$', block).group(1)
        self.assertFalse({'html', 'htm', 'svg', 'xml', 'js'} & set(re.split(r'[|?]', inline)), inline)
