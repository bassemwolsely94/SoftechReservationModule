"""
PBX extension registration status (SIPpeers / PJSIP parsing, merge with mapping)
and the audited mapping endpoint.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.pbx import extensions
from apps.pbx.models import AgentExtension, CallSession
from .factories import make_admin, make_call_center, make_pharmacist


class FakeClient:
    def __init__(self, lists):
        self.lists = lists

    def action_list(self, fields, complete):
        return self.lists[fields['Action']]


SIP_PEERS = [
    {'Event': 'PeerEntry', 'ObjectName': '101', 'IPaddress': '10.0.0.5', 'IPport': '5060', 'Status': 'OK (12 ms)'},
    {'Event': 'PeerEntry', 'ObjectName': '102', 'IPaddress': '-none-', 'Status': 'UNKNOWN'},
    {'Event': 'PeerEntry', 'ObjectName': '103', 'IPaddress': '10.0.0.7', 'Status': 'OK (450 ms)'},
    {'Event': 'PeerEntry', 'ObjectName': '200', 'IPaddress': '10.0.0.9', 'Status': 'OK (5 ms)'},
]


class ParsingTests(TestCase):

    def test_sip_peers(self):
        r = extensions._sip_peers(FakeClient({'SIPpeers': SIP_PEERS}))
        self.assertEqual(r['101'], {'online': True, 'status': 'OK (12 ms)', 'ip': '10.0.0.5',
                                    'port': '5060', 'rtt_ms': 12, 'user_agent': ''})
        self.assertFalse(r['102']['online'])
        self.assertEqual(r['102']['ip'], '')

    def test_pjsip(self):
        r = extensions._pjsip(FakeClient({
            'PJSIPShowEndpoints': [
                {'Event': 'EndpointList', 'ObjectName': '301', 'DeviceState': 'Not in use'},
                {'Event': 'EndpointList', 'ObjectName': '302', 'DeviceState': 'Unavailable'}],
            'PJSIPShowContacts': [
                {'Event': 'ContactList', 'Endpoint': '301', 'Status': 'Reachable',
                 'Uri': 'sip:301@10.1.1.4:5062', 'RoundtripUsec': '23000', 'UserAgent': 'Zoiper'}],
        }))
        self.assertTrue(r['301']['online'])
        self.assertEqual((r['301']['ip'], r['301']['rtt_ms'], r['301']['user_agent']), ('10.1.1.4', 23, 'Zoiper'))
        self.assertFalse(r['302']['online'])


class MergeTests(TestCase):

    def setUp(self):
        _, self.agent, _ = make_call_center('ext_agent')
        AgentExtension.objects.create(extension='101', staff=self.agent, extension_type='agent')
        _, other, _ = make_call_center('ext_off')
        AgentExtension.objects.create(extension='102', staff=other, extension_type='agent')
        AgentExtension.objects.create(extension='999', extension_type='agent')   # not in PBX
        self.regs = extensions._sip_peers(FakeClient({'SIPpeers': SIP_PEERS}))

    def _status(self):
        with mock.patch.object(extensions, 'fetch_registrations', return_value=(self.regs, 'SIP')):
            return extensions.extension_status()

    def test_merge_and_problems(self):
        CallSession.objects.create(unique_id='u1', state='answered', caller_number='010',
                                   agent=AgentExtension.objects.get(extension='101'),
                                   started_at=timezone.now())
        data = self._status()
        rows = {r['extension']: r for r in data['rows']}
        self.assertTrue(rows['101']['online'] and rows['101']['on_call'])
        self.assertIsNone(rows['101']['problem'])
        self.assertIn('غير مسجّل', rows['102']['problem'])           # mapped but phone off
        self.assertIn('بطيئة', rows['103']['problem'])               # slow, unmapped
        self.assertIn('غير مرتبطة', rows['200']['problem'])          # online, unmapped
        self.assertIn('غير موجودة', rows['999']['problem'])          # not in PBX
        self.assertEqual(data['summary']['unmapped'], 2)
        self.assertEqual(AgentExtension.objects.get(extension='101').last_ip, '10.0.0.5')

    def test_pbx_unreachable_keeps_last_known(self):
        self._status()  # persists last_status/last_ip
        with mock.patch.object(extensions, 'fetch_registrations', side_effect=OSError('timed out')):
            data = extensions.extension_status()
        self.assertIn('timed out', data['error'])
        row = next(r for r in data['rows'] if r['extension'] == '101')
        self.assertEqual(row['ip'], '10.0.0.5')
        self.assertIsNone(row['problem'])     # no false "missing from PBX" while offline


class MappingApiTests(TestCase):

    def setUp(self):
        _, _, self.admin = make_admin('ext_admin')
        _, self.agent, self.agent_client = make_call_center('ext_cc')

    def test_map_moves_staff_and_audits(self):
        from apps.audit.models import AuditLog
        AgentExtension.objects.create(extension='101', staff=self.agent)
        r = self.admin.post('/api/pbx/extensions/map/',
                            {'extension': '105', 'staff_id': self.agent.pk, 'extension_type': 'agent'},
                            format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['moved_from'], '101')
        self.assertIsNone(AgentExtension.objects.get(extension='101').staff)
        self.assertEqual(AgentExtension.objects.get(extension='105').staff, self.agent)
        self.assertTrue(AuditLog.objects.filter(action='pbx_extension_mapped').exists())

        r = self.admin.post('/api/pbx/extensions/map/', {'extension': '105', 'staff_id': None}, format='json')
        self.assertIsNone(AgentExtension.objects.get(extension='105').staff)

    def test_non_supervisors_cannot_map_or_edit(self):
        ext = AgentExtension.objects.create(extension='110')
        self.assertEqual(self.agent_client.post('/api/pbx/extensions/map/',
                         {'extension': '110', 'staff_id': self.agent.pk}, format='json').status_code, 403)
        self.assertEqual(self.agent_client.patch(f'/api/pbx/agents/{ext.pk}/',
                         {'staff': self.agent.pk}, format='json').status_code, 403)
        self.assertEqual(self.agent_client.post('/api/pbx/agents/',
                         {'extension': '111'}, format='json').status_code, 403)
        self.assertEqual(self.agent_client.get('/api/pbx/agents/').status_code, 200)   # reads stay open
        _, _, ph = make_pharmacist('ext_ph')
        self.assertEqual(ph.get('/api/pbx/extensions/status/').status_code, 403)

    def test_validation(self):
        self.assertEqual(self.admin.post('/api/pbx/extensions/map/', {'extension': ''},
                                         format='json').status_code, 400)
        self.assertEqual(self.admin.post('/api/pbx/extensions/map/',
                                         {'extension': '1', 'extension_type': 'bogus'},
                                         format='json').status_code, 400)
