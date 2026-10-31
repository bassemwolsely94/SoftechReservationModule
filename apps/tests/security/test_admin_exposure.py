"""
N0 / H9 — Django admin exposure.

Django admin has no 2FA, and nginx used to let all of 10/8 (every ZeroTier member) reach it.
Now: the admin URL is mounted only when DJANGO_ADMIN_ENABLED (default: DEBUG; off in production),
and nginx allows only the addresses listed in a per-VPS include file.
"""
import importlib
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import clear_url_caches, resolve, Resolver404

import config.urls

_ROOT = Path(settings.BASE_DIR)


def _reload_urls():
    clear_url_caches()
    importlib.reload(config.urls)


class AdminMountTests(SimpleTestCase):

    def tearDown(self):
        # Other tests must see the urlconf for the real settings, whatever this test did.
        _reload_urls()

    def test_admin_404_when_disabled(self):
        with override_settings(DJANGO_ADMIN_ENABLED=False):
            _reload_urls()
            with self.assertRaises(Resolver404):
                resolve('/admin/')
            self.assertEqual(self.client.get('/admin/').status_code, 404)

    def test_admin_mounted_when_enabled(self):
        with override_settings(DJANGO_ADMIN_ENABLED=True):
            _reload_urls()
            self.assertEqual(resolve('/admin/').route, 'admin/')

    def test_setting_defaults_to_debug(self):
        # The test runner forces DEBUG=False after settings load, so check the source default.
        text = (_ROOT / 'config' / 'settings.py').read_text(encoding='utf-8')
        self.assertIn("DJANGO_ADMIN_ENABLED = config('DJANGO_ADMIN_ENABLED', default=DEBUG, cast=bool)", text)


class NginxAdminTests(SimpleTestCase):

    def _admin_block(self):
        text = (_ROOT / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        start = text.index('location /admin/')
        return text[start:text.index('}', start)]

    def test_nginx_admin_has_no_private_range_allow(self):
        block = self._admin_block()
        for rng in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'):
            self.assertNotIn(f'allow {rng}', block)
        self.assertIn('include /etc/nginx/elrezeiky-admin-allow.conf;', block)
        self.assertIn('include /etc/nginx/elrezeiky-proxy-headers.conf;', block)

    def test_allow_list_example_is_per_ip(self):
        text = (_ROOT / 'deploy' / 'nginx-admin-allow.conf.example').read_text(encoding='utf-8')
        self.assertIn('allow 127.0.0.1;', text)
        self.assertIn('deny all;', text)
        self.assertNotIn('/8;', text)
