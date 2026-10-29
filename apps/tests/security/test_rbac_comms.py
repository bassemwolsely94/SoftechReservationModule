"""
Authorization — call center, omni-channel inbox, PBX, WhatsApp and campaigns follow the matrix
(Batch 4, Z-8b; owner decision 2026-10-28, map by screen).

Before (RBAC log mode = production): any logged-in role — salesperson and delivery included —
could read every WhatsApp and omni-channel conversation and reply on them, read call logs and
cases of their branch, see the live PBX calls, and create or edit a channel account (its phone
number / token); any role, call center included, could approve, reject or queue (= send) a
WhatsApp campaign; /api/callcenter/ served its router index.

Now: call center / omni / PBX / WhatsApp = the `callcenter` module (the WhatsApp inbox sits with
the call center screens, not campaigns); campaigns = `campaigns`, approve / reject / queue need
approve; omni channel-account edits are admin / supervisor. Call quality scoring keeps its own
role check (quality manager included); a user's own PBX extension stays readable by everyone.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import sweep

MISSING = '987654321'


class CommsSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes={'callcenter', 'omni', 'pbx', 'whatsapp', 'campaigns'})
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class CommsTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _call(self, role, method, path, data=None):
        c = bearer_client(make_user(f'z8b_{role}', role=role)[0])
        with Tripwire():
            return getattr(c, method)(path, data or {}, format='json') if method != 'get' else c.get(path)

    def test_salesperson_cannot_read_whatsapp_conversations(self):
        self.assertEqual(self._call('salesperson', 'get', '/api/whatsapp/conversations/').status_code, 403)

    def test_salesperson_cannot_read_omni_conversations(self):
        self.assertEqual(self._call('salesperson', 'get', '/api/omni/conversations/').status_code, 403)

    def test_pharmacist_cannot_read_call_logs(self):
        self.assertEqual(self._call('pharmacist', 'get', '/api/callcenter/calls/').status_code, 403)

    def test_delivery_cannot_watch_live_calls(self):
        self.assertEqual(self._call('delivery', 'get', '/api/pbx/live/').status_code, 403)

    def test_call_center_cannot_approve_a_campaign(self):
        self.assertEqual(self._call('call_center', 'post', f'/api/campaigns/{MISSING}/approve/').status_code, 403)

    def test_call_center_cannot_edit_a_channel_account(self):
        self.assertEqual(self._call('call_center', 'patch', f'/api/omni/accounts/{MISSING}/', {'name': 'x'}).status_code, 403)

    def test_call_center_still_works_its_inboxes(self):
        self.assertEqual(self._call('call_center', 'get', '/api/callcenter/calls/').status_code, 200)
        self.assertEqual(self._call('call_center', 'get', '/api/whatsapp/conversations/').status_code, 200)

    def test_supervisor_still_approves_campaigns(self):
        self.assertEqual(self._call('supervisor', 'post', f'/api/campaigns/{MISSING}/approve/').status_code, 404)

    def test_quality_manager_still_scores_calls(self):
        self.assertEqual(self._call('quality_manager', 'get', f'/api/callcenter/calls/{MISSING}/quality/').status_code, 404)

    def test_everyone_still_reads_their_own_extension(self):
        self.assertNotEqual(self._call('salesperson', 'get', '/api/pbx/my-extension/').status_code, 403)
