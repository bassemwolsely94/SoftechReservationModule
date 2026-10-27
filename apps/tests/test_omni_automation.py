"""
apps/tests/test_omni_automation.py

CEP Phase 4 + 5 (doc 15) — automation engine, AI assist, analytics.

Tests covering:
  - Engine: keyword match fires actions (priority/tag/note), VIP condition,
    channel condition, no-match skips, feedback-loop guard, AutomationRun log,
    stop_processing, auto_reply on inbound WA (mocked sender)
  - Seed command
  - AI assist endpoint (mocked Gemini)
  - Analytics endpoint: role gate, channel/day aggregates, conversion rate
"""
from unittest import mock

from django.test import TestCase

from apps.omni import services
from apps.omni.models import AutomationRule, AutomationRun, Conversation, TimelineEvent
from apps.whatsapp.models import WAConversation, WAMessage
from .factories import make_admin, make_customer, make_pharmacist


def make_rule(**kw):
    defaults = dict(
        name='rule', trigger='message_in', conditions={}, actions=[], is_active=True)
    defaults.update(kw)
    return AutomationRule.objects.create(**defaults)


def fire_message(text='مرحبا', channel='whatsapp', customer=None, wa_id='201012345678'):
    """Create an inbound WA message → emits a message_in TimelineEvent."""
    conv, _ = WAConversation.objects.get_or_create(wa_id=wa_id)
    if customer and conv.customer_id is None:
        conv.customer = customer
        conv.save()
    return WAMessage.objects.create(conversation=conv, direction='inbound', body=text)


class EngineTests(TestCase):

    def test_keyword_match_runs_actions(self):
        make_rule(
            conditions={'text_contains': ['شكوى']},
            actions=[
                {'type': 'set_priority', 'priority': 'urgent'},
                {'type': 'add_tag', 'tag': 'شكوى'},
            ])
        fire_message('عندي شكوى على الخدمة')

        convo = Conversation.objects.latest('id')
        self.assertEqual(convo.priority, 'urgent')
        self.assertIn('[شكوى]', convo.subject)
        run = AutomationRun.objects.latest('id')
        self.assertTrue(run.matched)
        self.assertIn('set_priority=urgent', run.actions_run)

    def test_no_keyword_match_skips(self):
        make_rule(conditions={'text_contains': ['شكوى']},
                  actions=[{'type': 'set_priority', 'priority': 'urgent'}])
        fire_message('السلام عليكم')
        convo = Conversation.objects.latest('id')
        self.assertEqual(convo.priority, 'normal')
        self.assertFalse(AutomationRun.objects.exists())

    def test_vip_condition(self):
        vip = make_customer(name='باشا', phone='01011112222')
        vip.segment = 'vip'
        vip.save(update_fields=['segment'])
        make_rule(conditions={'customer_vip': True},
                  actions=[{'type': 'add_tag', 'tag': 'VIP'}])

        fire_message('اهلا', customer=vip, wa_id='201011112222')
        convo = Conversation.objects.latest('id')
        self.assertIn('[VIP]', convo.subject)

    def test_channel_condition_filters(self):
        make_rule(conditions={'channel': 'voice'},
                  actions=[{'type': 'set_priority', 'priority': 'high'}])
        fire_message('اهلا')  # whatsapp — should NOT fire
        self.assertFalse(AutomationRun.objects.exists())

    def test_feedback_loop_guard(self):
        # A rule that adds a note must not re-trigger on its own note event
        make_rule(trigger='message_in',
                  actions=[{'type': 'add_note', 'text': 'ملاحظة آلية'}])
        fire_message('اهلا')
        # Exactly one run (the automation_action event is not a trigger)
        self.assertEqual(AutomationRun.objects.count(), 1)

    def test_stop_processing(self):
        make_rule(name='first', order=1, stop_processing=True,
                  actions=[{'type': 'add_tag', 'tag': 'A'}])
        make_rule(name='second', order=2,
                  actions=[{'type': 'add_tag', 'tag': 'B'}])
        fire_message('اهلا')
        convo = Conversation.objects.latest('id')
        self.assertIn('[A]', convo.subject)
        self.assertNotIn('[B]', convo.subject)

    def test_auto_reply_sends_on_whatsapp(self):
        make_rule(conditions={'text_contains': ['سعر']},
                  actions=[{'type': 'auto_reply', 'text': 'سعر المنتج 50 جنيه'}])
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as Sender:
            instance = Sender.return_value
            instance.send_text.return_value = {'messages': [{'id': 'x'}]}
            # window must be open for auto_reply
            conv, _ = WAConversation.objects.get_or_create(wa_id='201012345678')
            from django.utils import timezone
            from datetime import timedelta
            conv.window_expires_at = timezone.now() + timedelta(hours=1)
            conv.save()
            WAMessage.objects.create(conversation=conv, direction='inbound',
                                     body='ايه سعر الدوا؟')
            instance.send_text.assert_called_once()

    def test_disabled_rule_does_not_fire(self):
        make_rule(is_active=False, actions=[{'type': 'set_priority', 'priority': 'urgent'}])
        fire_message('اهلا')
        self.assertFalse(AutomationRun.objects.exists())


class SeedCommandTests(TestCase):

    def test_seed(self):
        from django.core.management import call_command
        call_command('seed_omni_automations')
        self.assertEqual(AutomationRule.objects.count(), 4)
        # idempotent
        call_command('seed_omni_automations')
        self.assertEqual(AutomationRule.objects.count(), 4)


class AIAssistTests(TestCase):

    def setUp(self):
        self.user, self.profile, self.client_api = make_admin('ai_admin')

    def test_assist_endpoint(self):
        fire_message('عايز اعرف سعر بانادول')
        convo = Conversation.objects.latest('id')
        fake = {
            'summary': 'العميل يسأل عن سعر بانادول',
            'intent': 'تسعير', 'urgency': 2,
            'suggested_replies': ['سعر بانادول 15 جنيه', 'تحت أمرك', 'هل تريد الحجز؟'],
        }
        with mock.patch('apps.omni.ai.assist_conversation', return_value=fake):
            resp = self.client_api.post(f'/api/omni/conversations/{convo.pk}/ai-assist/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['suggested_replies']), 3)
        self.assertEqual(resp.data['intent'], 'تسعير')

    def test_assist_empty_conversation_400(self):
        convo = services.resolve_conversation(phone='01099998888', channel='voice')
        resp = self.client_api.post(f'/api/omni/conversations/{convo.pk}/ai-assist/')
        self.assertEqual(resp.status_code, 400)


class AnalyticsTests(TestCase):

    def setUp(self):
        _, _, self.supervisor = make_admin('an_admin')
        _, _, self.pharmacist = make_pharmacist('an_pharma')

    def test_role_gate(self):
        self.assertEqual(self.pharmacist.get('/api/omni/analytics/').status_code, 403)

    def test_aggregates(self):
        cust = make_customer()
        fire_message('اهلا', customer=cust)
        convo = Conversation.objects.latest('id')
        # An outbound + an ERP reservation event for conversion
        services.add_event(convo, 'message_out', channel='whatsapp',
                           summary='رد', actor=None)
        services.add_event(convo, 'erp_reservation', summary='حجز #1')

        data = self.supervisor.get('/api/omni/analytics/', {'days': 30}).data
        channels = {c['channel'] for c in data['by_channel']}
        self.assertIn('whatsapp', channels)
        self.assertEqual(data['conversion']['to_reservation'], 1)
        self.assertGreaterEqual(data['conversion']['conversations'], 1)
        self.assertTrue(len(data['by_day']) >= 1)
