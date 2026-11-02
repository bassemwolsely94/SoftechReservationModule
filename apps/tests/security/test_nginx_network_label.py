"""
N1 / Task 1 — nginx labels where each request arrived (internal tunnel vs public), so Django can
log it. The label is written by nginx only; the include OVERWRITES any client-sent value.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.tests.security.test_client_ip import _location_blocks, _PROXY_INCLUDE

_ROOT = Path(settings.BASE_DIR)


class NginxNetworkLabelTests(SimpleTestCase):

    def _map(self):
        text = (_ROOT / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        m = re.search(r'^map\s+\$server_addr\s+\$elr_network\s*\{(.*?)\}', text, re.M | re.S)
        self.assertIsNotNone(m, 'map $server_addr $elr_network block missing')
        # the map must sit at http level: before the first server block
        self.assertLess(m.start(), text.index('server {'))
        rows = {}
        for line in m.group(1).splitlines():
            line = line.split('#')[0].strip().rstrip(';').strip()
            if line:
                key, value = line.split()
                rows[key] = value
        return rows

    def test_map_labels_tunnel_addresses_internal(self):
        rows = self._map()
        self.assertEqual(rows.get('10.50.50.77'), 'internal')
        self.assertEqual(rows.get('10.0.0.77'), 'internal')
        self.assertEqual(rows.get('default'), 'external')

    def test_proxy_headers_overwrite_network_header(self):
        text = (_ROOT / 'deploy' / 'nginx-proxy-headers.conf').read_text(encoding='utf-8')
        self.assertIn('proxy_set_header X-ElR-Network $elr_network;', text)

    def test_every_proxied_location_gets_label(self):
        text = (_ROOT / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        proxied = [(h, b) for h, b in _location_blocks(text) if 'proxy_pass' in b]
        self.assertTrue(proxied)
        for header, body in proxied:
            self.assertIn(_PROXY_INCLUDE, body, header)
