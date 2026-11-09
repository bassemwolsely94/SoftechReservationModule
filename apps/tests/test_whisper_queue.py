"""
Nightly Whisper queue: enqueue rules, window, pause/stop, retries, learning prompt,
controls + corrections API. faster-whisper itself is mocked.
"""
from datetime import time as dtime, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter import whisper
from apps.callcenter.models import CallLog, CallTranscript, WhisperQueueControl
from apps.pbx.models import CallSession, CdrCall
from .factories import make_admin, make_call_center, make_pharmacist

ON = dict(WHISPER_ENABLED=True, WHISPER_MIN_SECONDS=20)
_seq = iter(range(1, 100000))


def _call(**kw):
    d = dict(phone_number='01012345678', status='answered', duration_seconds=90,
             recording_url='http://issabel/r/a.wav')
    d.update(kw)
    return CallLog.objects.create(**d)


def _cdr(**kw):
    n = next(_seq)
    d = dict(cdr_key=f'k{n}', unique_id=f'1791792391.{n}', call_at=timezone.now(),
             direction='inbound', status='answered', customer_number='01012345678',
             billable_seconds=90, duration_seconds=95,
             recording_file=f'/var/spool/asterisk/monitor/2026/11/09/exten-{n}.wav')
    d.update(kw)
    return CdrCall.objects.create(**d)


def _audio(*a, **k):
    return b'AUDIO', 'audio/wav'


@override_settings(**ON)
class EnqueueTests(TestCase):

    def test_rules(self):
        self.assertTrue(whisper.enqueue_cdr(_cdr()))
        self.assertFalse(whisper.enqueue_cdr(_cdr(billable_seconds=5)))
        self.assertFalse(whisper.enqueue_cdr(_cdr(status='no_answer')))
        self.assertFalse(whisper.enqueue_cdr(_cdr(recording_file='')))
        self.assertFalse(whisper.enqueue_cdr(_cdr(is_transfer=True)))
        c = _cdr()
        whisper.enqueue_cdr(c)
        self.assertFalse(whisper.enqueue_cdr(c))       # idempotent
        self.assertEqual(CallTranscript.objects.filter(engine='whisper').count(), 2)

    def test_recent_window_and_call_log_link(self):
        log = _call()
        c = _cdr()
        CallSession.objects.create(unique_id=c.unique_id, caller_number='010', call_log=log,
                                   started_at=timezone.now())
        _cdr(call_at=timezone.now() - timedelta(days=5))       # too old for 48h
        self.assertEqual(whisper.enqueue_recent_cdr(), 1)
        t = CallTranscript.objects.get(engine='whisper')
        self.assertEqual((t.cdr_call_id, t.call_log_id), (c.pk, log.pk))
        self.assertEqual(whisper.enqueue_recent_cdr(), 0)

    @override_settings(WHISPER_ENABLED=False)
    def test_disabled(self):
        self.assertFalse(whisper.enqueue_cdr(_cdr()))
        self.assertEqual(whisper.enqueue_recent_cdr(), 0)


@override_settings(**ON)
class RunnerTests(TestCase):

    def setUp(self):
        for _ in range(3):
            whisper.enqueue_cdr(_cdr())

    def _run(self, transcribe=None, **kw):
        with mock.patch('apps.pbx.recordings.load_cdr_audio', side_effect=_audio), \
             mock.patch.object(whisper, 'transcribe_audio',
                               side_effect=transcribe or (lambda *a: ('نص المكالمة', 60.0))):
            return whisper.run_queue(**kw)

    def test_processes_all_when_forced(self):
        r = self._run(ignore_window=True)
        self.assertEqual(r, {'processed': 3, 'stopped': 'queue_empty'})
        self.assertEqual(CallTranscript.objects.filter(status='done').count(), 3)
        self.assertEqual(WhisperQueueControl.get().run_note, 'اكتمل الطابور')

    def test_outside_window_does_nothing(self):
        c = WhisperQueueControl.get()
        now = timezone.localtime()
        c.window_start = (now + timedelta(hours=2)).time().replace(second=0, microsecond=0)
        c.window_end = (now + timedelta(hours=3)).time().replace(second=0, microsecond=0)
        c.save()
        self.assertEqual(self._run()['stopped'], 'outside_window')

    def test_paused(self):
        WhisperQueueControl.objects.update_or_create(pk=1, defaults={'paused': True})
        self.assertEqual(self._run(ignore_window=True)['stopped'], 'paused')
        self.assertEqual(CallTranscript.objects.filter(status='pending').count(), 3)

    def test_stop_mid_run_leaves_rest_for_later(self):
        def stop_after_first(*a):
            WhisperQueueControl.objects.filter(pk=1).update(stop_requested=True)
            return 'نص', 30.0
        r = self._run(transcribe=stop_after_first, ignore_window=True)
        self.assertEqual(r['processed'], 1)
        self.assertEqual(r['stopped'], 'stop_requested')
        self.assertEqual(CallTranscript.objects.filter(status='pending').count(), 2)
        self.assertFalse(WhisperQueueControl.get().stop_requested)   # reset for next night

    def test_window_closing_skips_long_call(self):
        c = WhisperQueueControl.get()
        now = timezone.localtime()
        c.window_start = (now - timedelta(hours=1)).time()
        c.window_end = (now + timedelta(minutes=1)).time()
        c.save()
        CdrCall.objects.update(billable_seconds=3600)
        self.assertEqual(self._run()['stopped'], 'window_closed')
        self.assertEqual(CallTranscript.objects.filter(status='pending').count(), 3)

    def test_failure_retries_then_fails(self):
        def boom(*a):
            raise RuntimeError('decode error')
        self._run(transcribe=boom, ignore_window=True)
        # one attempt per night, then back in the queue
        self.assertEqual(set(CallTranscript.objects.values_list('attempts', 'status')), {(1, 'pending')})
        for _ in range(CallTranscript.MAX_ATTEMPTS - 1):
            self._run(transcribe=boom, ignore_window=True, max_items=None)
        self.assertEqual(CallTranscript.objects.filter(status='failed').count(), 3)

    def test_crashed_running_rows_requeued(self):
        CallTranscript.objects.filter(pk=CallTranscript.objects.first().pk).update(status='running')
        self.assertEqual(self._run(ignore_window=True)['processed'], 3)


class WindowTests(TestCase):

    def test_window_crossing_midnight(self):
        c = WhisperQueueControl(window_start=dtime(23, 0), window_end=dtime(3, 0))
        at = lambda h: timezone.make_aware(timezone.datetime(2026, 10, 12, h, 30))
        self.assertTrue(whisper.in_window(c, at(23)))
        self.assertTrue(whisper.in_window(c, at(1)))
        self.assertFalse(whisper.in_window(c, at(12)))


@override_settings(WHISPER_EXTRA_TERMS=['كونكور'])
class LearningTests(TestCase):

    def test_prompt_uses_corrected_words(self):
        t = CallTranscript.objects.create(call_log=_call(), engine='whisper', status='done',
                                          text='عايز دوا الضغط اموكلان')
        t.corrected_text = 'عايز دواء الضغط أملوديبين'
        t.save()
        prompt = whisper.build_vocabulary_prompt()
        self.assertIn('كونكور', prompt)
        self.assertIn('أملوديبين', prompt)
        self.assertNotIn('الضغط', prompt)       # unchanged words aren't hints


@override_settings(**ON)
class ApiTests(TestCase):

    def test_controls_admin_only_and_audited(self):
        from apps.audit.models import AuditLog
        _, _, ph = make_pharmacist('wh_ph')
        self.assertEqual(ph.post('/api/callcenter/whisper/control/', {'action': 'pause'}).status_code, 403)
        _, _, admin = make_admin('wh_admin')
        r = admin.post('/api/callcenter/whisper/control/',
                       {'action': 'pause', 'window_start': '01:30', 'model_size': 'small'}, format='json')
        self.assertEqual(r.status_code, 200)
        c = WhisperQueueControl.get()
        self.assertTrue(c.paused)
        self.assertEqual(c.window_start, dtime(1, 30))
        self.assertTrue(AuditLog.objects.filter(action='whisper_control_changed').exists())
        self.assertEqual(admin.post('/api/callcenter/whisper/control/',
                                    {'model_size': 'huge'}, format='json').status_code, 400)

    def test_status_and_correction(self):
        _, agent, client = make_call_center('wh_cc')
        t = CallTranscript.objects.create(call_log=_call(), engine='whisper', status='done', text='نص')
        cdr_only = CallTranscript.objects.create(cdr_call=_cdr(), engine='whisper', status='done',
                                                 text='من سجل السنترال', finished_at=timezone.now())
        CallTranscript.objects.create(call_log=t.call_log, engine='gemini', status='done', text='نص جيميناي')
        rows = {r['id']: r for r in client.get('/api/callcenter/whisper/').data['recent']}
        self.assertEqual(rows[t.pk]['gemini_text'], 'نص جيميناي')
        self.assertEqual(rows[cdr_only.pk]['whisper_text'], 'من سجل السنترال')
        self.assertEqual(rows[cdr_only.pk]['duration_seconds'], 90)

        r = client.post(f'/api/callcenter/transcripts/{t.pk}/correct/',
                        {'corrected_text': 'النص الصحيح'}, format='json')
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.corrected_by, agent)
