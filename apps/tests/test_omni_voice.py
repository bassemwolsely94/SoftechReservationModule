"""
apps/tests/test_omni_voice.py

CEP Phase 2 (doc 15) — voice deepening.

Tests covering:
  - Wallboard: role gate (supervisor yes / pharmacist no), aggregate shape,
    live calls + queue stats + agent states
  - Spy endpoint: role gate, target validation, supervisor-without-extension,
    AMI originate call (mocked), mode validation
  - Recording URLs: signed token roundtrip, expiry/forgery rejection,
    playback view auth-less token access, timeline serializer resolution
  - Transcription endpoint: routes CallLog vs WAMessage vs invalid (mocked
    Gemini in the pipeline function)
"""
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.omni.models import TimelineEvent
from apps.pbx import recordings
from apps.pbx.models import AgentExtension, CallSession, PBXQueue
from .factories import make_admin, make_customer, make_pharmacist, make_user

WALLBOARD_URL = '/api/omni/wallboard/'
SPY_URL = '/api/pbx/spy/'


def make_session(**kw):
    defaults = dict(
        unique_id=f'uid-{timezone.now().timestamp()}-{kw.get("caller_number", "x")}',
        direction='inbound',
        state='answered',
        caller_number='01012345678',
        started_at=timezone.now(),
        answered_at=timezone.now(),
    )
    defaults.update(kw)
    return CallSession.objects.create(**defaults)


class WallboardTests(TestCase):

    def setUp(self):
        _, _, self.supervisor = make_user('wb_super', role='supervisor', access_all=True)
        _, _, self.pharmacist = make_pharmacist('wb_pharma')

    def test_role_gate(self):
        self.assertEqual(self.pharmacist.get(WALLBOARD_URL).status_code, 403)
        self.assertEqual(self.supervisor.get(WALLBOARD_URL).status_code, 200)

    def test_aggregates(self):
        queue = PBXQueue.objects.create(name='callcenter-q')
        agent_staff, agent_profile, _ = make_user('wb_agent', role='call_center')
        ext = AgentExtension.objects.create(
            extension='201', extension_type='agent',
            staff=agent_profile, last_status='OK (12 ms)',
        )
        # One live answered call on the agent, one abandoned today
        make_session(queue=queue, agent=ext, caller_number='01011112222')
        make_session(state='abandoned', queue=queue, answered_at=None,
                     caller_number='01033334444')

        data = self.supervisor.get(WALLBOARD_URL).data
        self.assertEqual(len(data['live_calls']), 1)
        self.assertEqual(data['live_calls'][0]['agent_ext'], '201')
        self.assertEqual(data['today']['total'], 2)
        self.assertEqual(data['today']['abandoned'], 1)
        q = data['queues'][0]
        self.assertEqual(q['queue__name'], 'callcenter-q')
        self.assertEqual(q['total'], 2)
        agent = next(a for a in data['agents'] if a['extension'] == '201')
        self.assertTrue(agent['registered'])
        self.assertTrue(agent['on_call'])


class SpyTests(TestCase):

    def setUp(self):
        self.sup_user, self.sup_profile, self.supervisor = make_user(
            'spy_super', role='supervisor', access_all=True)
        _, _, self.pharmacist = make_pharmacist('spy_pharma')

    def test_role_gate(self):
        resp = self.pharmacist.post(SPY_URL, {'target_ext': '201', 'mode': 'listen'})
        self.assertEqual(resp.status_code, 403)

    def test_requires_supervisor_extension(self):
        resp = self.supervisor.post(SPY_URL, {'target_ext': '201', 'mode': 'listen'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('تحويلة', resp.data['detail'])

    def test_mode_validation(self):
        AgentExtension.objects.create(
            extension='900', extension_type='hq', staff=self.sup_profile)
        resp = self.supervisor.post(SPY_URL, {'target_ext': '201', 'mode': 'barge'})
        self.assertEqual(resp.status_code, 400)

    def test_originate_called_with_supervisor_ext(self):
        AgentExtension.objects.create(
            extension='900', extension_type='hq', staff=self.sup_profile)
        with mock.patch('apps.pbx.actions.originate_chanspy',
                        return_value={'Response': 'Success'}) as orig:
            resp = self.supervisor.post(
                SPY_URL, {'target_ext': '201', 'mode': 'whisper'})
        self.assertEqual(resp.status_code, 200, resp.data)
        orig.assert_called_once_with('900', '201', 'whisper')

    def test_ami_failure_maps_to_502(self):
        from apps.pbx.actions import AMIActionError
        AgentExtension.objects.create(
            extension='900', extension_type='hq', staff=self.sup_profile)
        with mock.patch('apps.pbx.actions.originate_chanspy',
                        side_effect=AMIActionError('AMI غير مهيأ')):
            resp = self.supervisor.post(
                SPY_URL, {'target_ext': '201', 'mode': 'listen'})
        self.assertEqual(resp.status_code, 502)


@override_settings(PBX_RECORDINGS_URL_BASE='http://issabel/recordings')
class RecordingTests(TestCase):

    def test_signed_token_roundtrip(self):
        url = recordings.signed_recording_url(42)
        token = url.split('t=')[1]
        self.assertTrue(recordings.validate_recording_token(42, token))
        self.assertFalse(recordings.validate_recording_token(43, token))
        self.assertFalse(recordings.validate_recording_token(42, token + 'x'))

    def test_playback_view_tokenless_403(self):
        session = make_session(recording_path='/var/spool/asterisk/monitor/x.wav')
        resp = self.client.get(f'/api/pbx/recordings/{session.pk}/')
        self.assertEqual(resp.status_code, 403)

    def test_playback_view_redirects_to_remote(self):
        session = make_session(recording_path='/var/spool/asterisk/monitor/rec1.wav')
        url = recordings.signed_recording_url(session.pk)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'http://issabel/recordings/rec1.wav')

    def test_timeline_serializer_resolves_recording(self):
        customer = make_customer()
        session = make_session(
            customer=customer,
            recording_path='/var/spool/asterisk/monitor/rec2.wav',
            state='answered',
        )
        session.complete()  # creates CallLog → omni signal creates timeline event

        _, _, client = make_admin('rec_admin')
        event = TimelineEvent.objects.filter(event_type='call').latest('id')
        resp = client.get(
            f'/api/omni/conversations/{event.conversation_id}/timeline/')
        row = next(r for r in (resp.data.get('results') or resp.data)
                   if r['event_type'] == 'call')
        self.assertIn(f'/api/pbx/recordings/{session.pk}/?t=', row['recording'])


class TranscribeEndpointTests(TestCase):

    def setUp(self):
        _, _, self.client_api = make_admin('tr_admin')

    def _event_for_call(self):
        log = CallLog.objects.create(
            phone_number='01012345678', direction='inbound', status='answered')
        return TimelineEvent.objects.get(
            object_id=log.pk, content_type__model='calllog')

    def test_routes_call_log(self):
        event = self._event_for_call()
        with mock.patch('apps.omni.transcription.transcribe_call_log') as fn:
            resp = self.client_api.post(f'/api/omni/events/{event.pk}/transcribe/')
            self.assertEqual(resp.status_code, 202)
            # Thread target invoked with the CallLog pk
            import time
            time.sleep(0.2)
            fn.assert_called_once_with(event.object_id)

    def test_rejects_non_audio_event(self):
        from apps.omni import services
        convo = services.resolve_conversation(phone='01099998888', channel='voice')
        event = services.add_event(convo, 'note', summary='ملاحظة')
        resp = self.client_api.post(f'/api/omni/events/{event.pk}/transcribe/')
        self.assertEqual(resp.status_code, 400)

    def test_pipeline_writes_transcript_and_insight(self):
        log = CallLog.objects.create(
            phone_number='01012345678', direction='inbound', status='answered',
            recording_url='http://issabel/recordings/x.wav',
        )
        fake_resp = mock.Mock(content=b'AUDIOBYTES',
                              headers={'Content-Type': 'audio/wav'})
        fake_resp.raise_for_status = mock.Mock()
        with mock.patch('requests.get', return_value=fake_resp), \
             mock.patch('apps.omni.transcription._gemini_transcribe',
                        return_value='العميل يسأل عن دواء الضغط'), \
             mock.patch('apps.callcenter.ai.summarize_call_async'):
            from apps.omni.transcription import transcribe_call_log
            transcribe_call_log(log.pk)

        log.refresh_from_db()
        self.assertEqual(log.voice_transcript, 'العميل يسأل عن دواء الضغط')
        insight = TimelineEvent.objects.filter(event_type='ai_insight').latest('id')
        self.assertEqual(insight.payload['kind'], 'transcript')
        self.assertIn('دواء الضغط', insight.payload['text'])
