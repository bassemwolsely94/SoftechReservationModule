"""
Browser phone (WebRTC): admin sets an extension's SIP password (stored encrypted,
audited without the secret); only the extension's own agent receives it.
"""
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.pbx.models import AgentExtension
from .factories import make_admin, make_call_center

WSS = dict(PBX_WEBRTC_WSS_URL='wss://pbx.local:8089/ws', PBX_WEBRTC_SIP_DOMAIN='pbx.local')
CFG = '/api/pbx/webrtc/config/'
SET = '/api/pbx/extensions/webrtc/'


@override_settings(**WSS)
class WebRTCTests(TestCase):

    def setUp(self):
        _, _, self.admin = make_admin('rtc_admin')
        _, self.agent, self.agent_client = make_call_center('rtc_agent')
        _, other, self.other_client = make_call_center('rtc_other')
        AgentExtension.objects.create(extension='160', staff=self.agent, extension_type='agent')
        AgentExtension.objects.create(extension='170', staff=other, extension_type='agent')

    def test_password_encrypted_and_only_for_own_agent(self):
        r = self.admin.post(SET, {'extension': '160', 'enabled': True, 'sip_password': 's3cr3t!'}, format='json')
        self.assertEqual(r.status_code, 200)
        ext = AgentExtension.objects.get(extension='160')
        self.assertNotIn('s3cr3t!', str(ext.webrtc_credentials))            # encrypted at rest
        log = AuditLog.objects.filter(action='pbx_webrtc_changed').latest('id')
        self.assertNotIn('s3cr3t!', str(log.__dict__))                      # never in the audit trail

        cfg = self.agent_client.get(CFG)
        self.assertEqual(cfg['Cache-Control'], 'no-store')
        self.assertEqual((cfg.data['enabled'], cfg.data['password'], cfg.data['sip_uri']),
                         (True, 's3cr3t!', 'sip:160@pbx.local'))
        other = self.other_client.get(CFG).data                              # ext 170: not enabled
        self.assertEqual((other['enabled'], other['reason']), (False, 'not_enabled'))
        self.assertNotIn('password', other)

    def test_agents_cannot_set_passwords(self):
        r = self.agent_client.post(SET, {'extension': '170', 'enabled': True, 'sip_password': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_reasons(self):
        AgentExtension.objects.filter(extension='160').update(webrtc_enabled=True)
        self.assertEqual(self.agent_client.get(CFG).data['reason'], 'no_password')
        with self.settings(PBX_WEBRTC_WSS_URL=''):
            self.assertEqual(self.agent_client.get(CFG).data['reason'], 'not_configured')
        _, _, nobody = make_call_center('rtc_noext')
        self.assertEqual(nobody.get(CFG).data['reason'], 'no_extension')

    def test_keeping_password_when_only_toggling(self):
        self.admin.post(SET, {'extension': '160', 'enabled': True, 'sip_password': 'abc'}, format='json')
        self.admin.post(SET, {'extension': '160', 'enabled': True}, format='json')
        self.assertEqual(self.agent_client.get(CFG).data['password'], 'abc')
