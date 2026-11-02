"""
Platform & abuse — server-side fetches of URLs people can set (Batch 6, W-6).

Before: a call's `recording_url` (call-centre editable) and a PBX session's recording URL were
fetched with `requests.get` — any scheme requests speaks, any host including 127.0.0.1, the LAN and
the cloud metadata address 169.254.169.254, redirects followed, the whole body read into memory.
The image downloader used urllib, which also opens `file://` paths on the server.

Now: `core.safe_fetch` — http / https only; every address the host resolves to must be public
(the PBX host configured in PBX_RECORDINGS_URL_BASE is the one allowed LAN host); redirects are
followed by hand (≤ 3) and each hop is checked again; the body is streamed under a size cap.
"""
import os
import socket
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

PUBLIC = '93.184.216.34'


def _resolve(mapping):
    """socket.getaddrinfo stand-in: hostname → IP (literal IPs resolve to themselves)."""
    def fake(host, *a, **k):
        ip = mapping.get(host, host)
        fam = socket.AF_INET6 if ':' in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, '', (ip, 80))]
    return fake


class _Resp:
    def __init__(self, status=200, body=b'x' * 4000, headers=None, chunks=None):
        self.status_code, self.headers = status, headers or {'Content-Type': 'audio/wav'}
        self._chunks = chunks if chunks is not None else [body]

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    @property
    def content(self):
        return b''.join(self._chunks)

    def close(self):
        pass


def _call(url):
    return SimpleNamespace(pk=1, pbx_session=None, recording_url=url)


class RecordingFetchTests(SimpleTestCase):

    def _audio(self, url, responses, mapping=None):
        from apps.omni.transcription import _resolve_call_audio
        get = mock.MagicMock(side_effect=list(responses))
        with mock.patch('requests.get', get), \
                mock.patch('socket.getaddrinfo', _resolve(mapping or {})):
            return _resolve_call_audio(_call(url)), get

    def test_private_and_metadata_addresses_are_not_fetched(self):
        for url in ('http://169.254.169.254/latest/meta-data/', 'http://127.0.0.1:8000/api/',
                    'http://10.0.0.5/rec.wav', 'http://[::1]/rec.wav', 'http://intranet.local/rec.wav'):
            (data, _), get = self._audio(url, [_Resp()], {'intranet.local': '192.168.1.9'})
            self.assertTrue(data is None, url)
            get.assert_not_called()

    def test_other_schemes_are_not_fetched(self):
        (data, _), get = self._audio('file:///etc/passwd', [_Resp()])
        self.assertTrue(data is None)
        get.assert_not_called()

    def test_a_redirect_to_a_private_address_is_not_followed(self):
        hop = _Resp(status=302, headers={'Location': 'http://169.254.169.254/latest/meta-data/'})
        (data, _), get = self._audio('http://rec.example/a.wav', [hop, _Resp()], {'rec.example': PUBLIC})
        self.assertTrue(data is None)
        self.assertEqual(get.call_count, 1)

    def test_the_download_is_capped(self):
        huge = _Resp(chunks=[b'x' * (1 << 20)] * 70)       # 70 MB > the 60 MB recording cap (as SFTP)
        (data, _), _ = self._audio('http://rec.example/a.wav', [huge], {'rec.example': PUBLIC})
        self.assertTrue(data is None)

    def test_a_public_recording_is_fetched(self):
        (data, mime), _ = self._audio('http://rec.example/a.wav', [_Resp()], {'rec.example': PUBLIC})
        self.assertEqual((len(data), mime), (4000, 'audio/wav'))

    @override_settings(PBX_RECORDINGS_URL_BASE='http://pbx.office:8088/rec/')
    def test_the_configured_pbx_host_may_be_on_the_lan(self):
        (data, _), _ = self._audio('http://pbx.office:8088/rec/x.wav', [_Resp()], {'pbx.office': '192.168.1.20'})
        self.assertIsNotNone(data)


class ImageDownloaderTests(SimpleTestCase):

    def _png(self):
        return b'\x89PNG\r\n\x1a\n' + b'0' * 3000

    def test_file_urls_are_refused(self):
        from apps.images.downloader import download_image
        fd, path = tempfile.mkstemp(suffix='.png')
        os.write(fd, self._png()); os.close(fd)
        self.addCleanup(os.remove, path)
        self.assertTrue(download_image('file:///' + path.replace('\\', '/')) is None)

    def test_private_hosts_are_refused(self):
        from apps.images.downloader import download_image
        fake = mock.MagicMock()
        fake.__enter__.return_value = SimpleNamespace(headers={'Content-Type': 'image/png'},
                                                      read=mock.MagicMock(side_effect=[self._png(), b'']))
        get = mock.MagicMock(return_value=_Resp(body=self._png(), headers={'Content-Type': 'image/png'}))
        with mock.patch('urllib.request.urlopen', return_value=fake), mock.patch('requests.get', get), \
                mock.patch('socket.getaddrinfo', _resolve({})):
            self.assertTrue(download_image('http://10.0.0.5/a.png') is None)
        get.assert_not_called()
