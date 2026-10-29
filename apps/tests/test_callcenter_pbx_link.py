"""
One CallLog per PBX call: the agent's save merges with the PBX session's log.
"""
from django.test import TestCase
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.pbx.models import AgentExtension, CallSession
from .factories import make_call_center

URL = '/api/callcenter/calls/'


class CallLogPbxLinkTests(TestCase):

    def setUp(self):
        _, self.profile, self.client_api = make_call_center('cc_link')
        self.ext = AgentExtension.objects.create(extension='301', staff=self.profile,
                                                 extension_type='agent')

    def _session(self, number='01012345678', **kw):
        defaults = dict(unique_id=f'u-{number}-{timezone.now().timestamp()}',
                        direction='inbound', state='answered', caller_number=number,
                        agent=self.ext, started_at=timezone.now(),
                        answered_at=timezone.now())
        defaults.update(kw)
        return CallSession.objects.create(**defaults)

    def _save(self, **kw):
        body = dict(phone_number='01012345678', purpose='complaint',
                    status='answered', notes='العميل يشتكي من التأخير')
        body.update(kw)
        return self.client_api.post(URL, body, format='json')

    def test_save_after_hangup_merges_into_pbx_log(self):
        s = self._session(recording_url='http://issabel/r/1.wav')
        s.complete()
        pbx_log = CallLog.objects.get(pbx_session=s)
        self.assertEqual(pbx_log.source, 'pbx')

        resp = self._save(phone_number='+201012345678')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['id'], pbx_log.pk)
        self.assertEqual(CallLog.objects.count(), 1)
        pbx_log.refresh_from_db()
        self.assertEqual(pbx_log.source, 'merged')
        self.assertEqual(pbx_log.purpose, 'complaint')
        self.assertEqual(pbx_log.recording_url, 'http://issabel/r/1.wav')

    def test_save_during_call_then_hangup_keeps_one_log(self):
        s = self._session()
        resp = self._save(pbx_session_id=s.pk, status='callback')
        self.assertEqual(resp.status_code, 201)
        s.refresh_from_db()
        self.assertEqual(s.call_log_id, resp.data['id'])

        s.recording_path = '/var/spool/asterisk/monitor/x.wav'
        s.complete()
        self.assertEqual(CallLog.objects.count(), 1)
        log = CallLog.objects.get()
        self.assertEqual(log.source, 'merged')
        self.assertEqual(log.status, 'callback')        # agent's choice kept
        self.assertEqual(log.notes, 'العميل يشتكي من التأخير')

    def test_no_match_creates_manual_log(self):
        self._session(number='01099999999').complete()
        resp = self._save()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(CallLog.objects.get(pk=resp.data['id']).source, 'manual')
        self.assertEqual(CallLog.objects.count(), 2)

    def test_second_save_does_not_overwrite_merged_log(self):
        self._session().complete()
        first = self._save().data['id']
        second = self._save(notes='مكالمة أخرى').data['id']
        self.assertNotEqual(first, second)
        self.assertEqual(CallLog.objects.get(pk=first).notes, 'العميل يشتكي من التأخير')

    def test_other_agents_session_is_not_claimed(self):
        _, other, _ = make_call_center('cc_other')
        other_ext = AgentExtension.objects.create(extension='302', staff=other)
        self._session(agent=other_ext).complete()
        resp = self._save()
        self.assertEqual(CallLog.objects.get(pk=resp.data['id']).source, 'manual')
