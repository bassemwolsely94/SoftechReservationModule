"""
Issabel recordings: date-folder paths, CDR lookup fallback, SFTP source order.
"""
from datetime import datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter import whisper
from apps.callcenter.models import CallLog
from apps.pbx import recordings
from apps.pbx.models import CallSession

ROOT = '/var/spool/asterisk/monitor'
SFTP = dict(PBX_RECORDINGS_SFTP_HOST='192.168.1.155', PBX_RECORDINGS_SFTP_USER='rec',
            PBX_RECORDINGS_SFTP_PASSWORD='x', PBX_RECORDINGS_DIR='', PBX_RECORDINGS_URL_BASE='')


def _session(**kw):
    d = dict(unique_id='1791792391.16990', direction='inbound', state='completed',
             caller_number='01012345678', started_at=timezone.now())
    d.update(kw)
    return CallSession.objects.create(**d)


class RelativePathTests(TestCase):

    def test_full_cdr_path_keeps_date_folders(self):
        self.assertEqual(recordings.relative_path(f'{ROOT}/2026/10/12/exten-160-153.wav'),
                         '2026/10/12/exten-160-153.wav')

    def test_bare_name_gets_date_from_calldate(self):
        self.assertEqual(recordings.relative_path('exten-15-170.wav', datetime(2026, 10, 12, 9, 54)),
                         '2026/10/12/exten-15-170.wav')

    def test_file_directly_in_root_stays(self):
        self.assertEqual(recordings.relative_path(f'{ROOT}/rec1.wav', datetime(2026, 1, 1)), 'rec1.wav')

    def test_traversal_rejected(self):
        self.assertEqual(recordings.relative_path('../../etc/passwd'), '')
        self.assertEqual(recordings.relative_path('/etc/passwd'), 'passwd')   # name only, inside root


class SourceTests(TestCase):

    def test_cdr_fills_missing_path(self):
        s = _session()
        with mock.patch.object(recordings, 'lookup_cdr_recording', return_value='2026/10/12/a.wav'):
            self.assertTrue(recordings.ensure_recording(s))
        s.refresh_from_db()
        self.assertEqual(s.recording_path, '2026/10/12/a.wav')

    @override_settings(**SFTP)
    def test_sftp_used_with_relative_path(self):
        s = _session(recording_path='2026/10/12/a.wav')
        with mock.patch.object(recordings, 'fetch_sftp', return_value=b'WAV') as fetch:
            audio, mime = recordings.load_session_audio(s)
        fetch.assert_called_once_with('2026/10/12/a.wav')
        self.assertEqual(audio, b'WAV')
        self.assertIn(mime, ('audio/wav', 'audio/x-wav'))

    @override_settings(**SFTP)
    def test_playback_streams_from_sftp(self):
        s = _session(recording_path='2026/10/12/a.wav')
        with mock.patch.object(recordings, 'fetch_sftp', return_value=b'WAV'):
            resp = self.client.get(recordings.signed_recording_url(s.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'WAV')


@override_settings(WHISPER_ENABLED=True, WHISPER_MIN_SECONDS=20)
class EnqueuePbxWithoutRecordingTests(TestCase):

    def test_pbx_call_queued_before_recording_known(self):
        s = _session()
        log = CallLog.objects.create(phone_number='01012345678', status='answered', duration_seconds=60)
        s.call_log = log
        s.save()
        log.refresh_from_db()
        self.assertTrue(whisper.enqueue(log))
