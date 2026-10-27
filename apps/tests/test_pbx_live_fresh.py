"""
/api/pbx/live/?fresh=1 — the POS call screen-pop must never show a call whose hang-up was
lost: nothing while the AMI bridge is down, and nothing older than 12 h even when it is up.
Without the flag (PBX live board) every non-completed session is still listed.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.pbx.models import CallSession, PBXBridgeStatus
from .factories import make_admin


class LiveFreshTests(TestCase):
    def setUp(self):
        _, _, self.client = make_admin('pbx_fresh_admin')
        now = timezone.now()
        self.old = CallSession.objects.create(unique_id='old.1', direction='inbound', state='answered',
                                              caller_number='01129227888', destination_ext='201')
        CallSession.objects.filter(pk=self.old.pk).update(started_at=now - timedelta(days=100))
        self.new = CallSession.objects.create(unique_id='new.1', direction='inbound', state='ringing',
                                              caller_number='01000000000', destination_ext='201')

    def ids(self, url):
        return {r['id'] for r in self.client.get(url).data}

    def test_board_still_lists_every_open_session(self):
        self.assertEqual(self.ids('/api/pbx/live/'), {self.old.id, self.new.id})

    def test_fresh_is_empty_while_bridge_is_down(self):
        self.assertEqual(self.ids('/api/pbx/live/?fresh=1'), set())
        PBXBridgeStatus.record(state='disconnected', last_heartbeat_at=timezone.now() - timedelta(hours=3))
        self.assertEqual(self.ids('/api/pbx/live/?fresh=1'), set())

    def test_fresh_drops_stale_calls_when_bridge_alive(self):
        PBXBridgeStatus.record(state='connected', last_heartbeat_at=timezone.now())
        self.assertEqual(self.ids('/api/pbx/live/?fresh=1'), {self.new.id})
