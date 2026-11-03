"""
AMI bridge event correlation. Issabel's AMI 1.3 sends no Linkedid; events used to be
matched on linked_id='' and so updated EVERY open call at once. Each event must now touch
only its own call. Event payloads are shaped like the live PBX AMI 1.3 events (numbers and names are synthetic).
"""
from asgiref.sync import async_to_sync
from django.test import TransactionTestCase
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.customers.models import Customer
from apps.pbx import ami_bridge as bridge
from apps.pbx.models import AgentExtension, CallSession


def run(handler, event):
    async_to_sync(handler)(event)


class CorrelationTests(TransactionTestCase):

    def setUp(self):
        bridge._active_sessions.clear()
        AgentExtension.objects.create(extension='goip4', extension_type='gateway')
        self.ext15 = AgentExtension.objects.create(extension='15', extension_type='agent')
        AgentExtension.objects.create(extension='170', extension_type='branch')
        bridge._load_extension_registry()
        self.customer = Customer.objects.create(name='عميل', phone='01000000201', softech_pic='P-1')

    def _incoming(self, uid, number):
        run(bridge._on_newchannel, {'Event': 'Newchannel', 'Uniqueid': uid, 'Channel': 'SIP/goip4-00001fdd',
                                    'CallerIDNum': number, 'Exten': '101'})
        return CallSession.objects.get(unique_id=uid)

    def test_answer_touches_only_its_own_call(self):
        a = self._incoming('1.1', '01000000101')
        b = self._incoming('1.2', '01000000102')
        run(bridge._on_agent_connect, {'Event': 'AgentConnect', 'Queue': '101', 'Member': 'SIP/15',
                                       'Uniqueid': '1.1', 'MemberName': 'Agent Fifteen'})
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.state, a.agent_id), ('answered', self.ext15.id))
        self.assertIsNotNone(a.answered_at)
        self.assertEqual(b.state, 'ringing')
        self.assertIsNone(b.answered_at)

    def test_abandon_touches_only_its_own_call(self):
        a = self._incoming('2.1', '01000000101')
        b = self._incoming('2.2', '01000000102')
        run(bridge._on_queue_abandon, {'Event': 'QueueCallerAbandon', 'Queue': '101', 'Uniqueid': '2.1'})
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.state, 'abandoned')
        self.assertNotIn(b.state, bridge.TERMINAL_STATES)

    def test_agent_called_does_not_assign_agent(self):
        a = self._incoming('3.1', '01000000101')
        run(bridge._on_agent_called, {'Event': 'AgentCalled', 'Queue': '101', 'Uniqueid': '3.1',
                                      'AgentCalled': 'Local/18@from-queue/n'})
        a.refresh_from_db()
        self.assertIsNone(a.agent_id)

    def test_unanswered_inbound_hangup_is_abandoned_not_answered(self):
        self._incoming('4.1', '01000000101')
        run(bridge._on_hangup, {'Event': 'Hangup', 'Uniqueid': '4.1', 'Cause-txt': 'Normal Clearing'})
        s = CallSession.objects.get(unique_id='4.1')
        self.assertEqual(s.state, 'abandoned')
        self.assertEqual(CallLog.objects.get(pbx_session=s).status, 'no_answer')

    def test_outbound_call_gets_customer_number_agent_and_answer(self):
        run(bridge._on_newchannel, {'Event': 'Newchannel', 'Uniqueid': '5.1', 'Channel': 'SIP/15-00001c7e',
                                    'CallerIDNum': '15', 'Exten': ''})
        s = CallSession.objects.get(unique_id='5.1')
        self.assertEqual((s.direction, s.agent_id), ('outbound', self.ext15.id))
        run(bridge._on_dial, {'Event': 'Dial', 'SubEvent': 'Begin', 'UniqueID': '5.1',
                              'Channel': 'SIP/15-00001c7e', 'Destination': 'SIP/goip4-00001c7f',
                              'Dialstring': 'goip4/8201000000201', 'DestUniqueID': '5.2'})
        run(bridge._on_bridge, {'Event': 'Bridge', 'Bridgestate': 'Link', 'Uniqueid1': '5.1', 'Uniqueid2': '5.2'})
        run(bridge._on_hangup, {'Event': 'Hangup', 'Uniqueid': '5.1', 'Cause-txt': 'Normal Clearing'})
        s.refresh_from_db()
        self.assertEqual((s.caller_number, s.state, s.customer_id), ('01000000201', 'completed', self.customer.id))
        log = CallLog.objects.get(pbx_session=s)
        self.assertEqual((log.direction, log.status, log.phone_number), ('outbound', 'answered', '01000000201'))
        self.assertEqual(log.called_at, s.started_at)

    def test_outbound_to_internal_extension_is_not_a_crm_call(self):
        run(bridge._on_newchannel, {'Event': 'Newchannel', 'Uniqueid': '6.1', 'Channel': 'SIP/15-00001fe8',
                                    'CallerIDNum': '15', 'Exten': ''})
        run(bridge._on_dial, {'Event': 'Dial', 'SubEvent': 'Begin', 'UniqueID': '6.1',
                              'Destination': 'SIP/170-00001fe9', 'Dialstring': '170'})
        run(bridge._on_hangup, {'Event': 'Hangup', 'Uniqueid': '6.1', 'Cause-txt': 'Normal Clearing'})
        self.assertEqual(CallSession.objects.get(unique_id='6.1').direction, 'internal')
        self.assertFalse(CallLog.objects.exists())

    def test_unanswered_outbound_extension_never_matches_a_customer(self):
        Customer.objects.create(name='رقم ينتهي بـ15', phone='01000000015', softech_pic='P-15')
        run(bridge._on_newchannel, {'Event': 'Newchannel', 'Uniqueid': '7.1', 'Channel': 'SIP/15-1',
                                    'CallerIDNum': '15', 'Exten': ''})
        run(bridge._on_hangup, {'Event': 'Hangup', 'Uniqueid': '7.1', 'Cause-txt': 'Normal Clearing'})
        self.assertIsNone(CallSession.objects.get(unique_id='7.1').customer_id)

    def test_noise_events_are_not_persisted(self):
        from apps.pbx.models import PBXEvent
        run(bridge.handle_event, {'Event': 'VarSet', 'Uniqueid': '8.1', 'Variable': 'X', 'Value': '1'})
        run(bridge.handle_event, {'Event': 'Newexten', 'Uniqueid': '8.1', 'Application': 'Set'})
        run(bridge.handle_event, {'Event': 'Dial', 'SubEvent': 'Begin', 'UniqueID': '8.1'})
        self.assertEqual(list(PBXEvent.objects.values_list('event_type', flat=True)), ['Dial'])
