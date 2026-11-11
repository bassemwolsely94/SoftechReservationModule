"""
Omni timeline: branch scope (same as the conversation list), type filter, latest-N.
"""
from unittest import mock

from django.test import TestCase

from apps.omni import services
from .factories import make_admin, make_customer


class TimelineScopeTests(TestCase):

    def setUp(self):
        self.user, _, self.client_api = make_admin('tl_admin')
        self.convo = services.resolve_conversation(customer=make_customer(), channel='whatsapp')
        for i in range(12):
            services.add_event(self.convo, 'message_in' if i % 2 else 'message_out', summary=f'رسالة {i}')
        services.add_event(self.convo, 'note', summary='ملاحظة داخلية')
        self.url = f'/api/omni/conversations/{self.convo.pk}/timeline/'

    def _rows(self, resp):
        return resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data

    def test_latest_messages_only(self):
        rows = self._rows(self.client_api.get(self.url, {'types': 'message_in,message_out', 'latest': 8}))
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]['summary'], 'رسالة 11')            # newest first
        self.assertTrue(all(r['event_type'].startswith('message') for r in rows))

    def test_conversation_outside_branch_scope_shows_nothing(self):
        from core import branch_scope
        with mock.patch.object(branch_scope, 'branch_ids', return_value=[987654]):
            rows = self._rows(self.client_api.get(self.url))
        self.assertEqual(len(rows), 0)
