"""
apps/tests/test_omni.py

CEP Phase 0 (doc 15) — unified timeline core.

Tests covering:
  - resolve_conversation: customer match, phone-tail match, anonymous adoption
  - WAMessage post_save → TimelineEvent (message_in) + thread linking
  - Inbound message reopens a resolved umbrella conversation
  - CallLog post_save → TimelineEvent (call / call_missed) in SAME
    umbrella as the WhatsApp thread (one customer, one timeline)
  - Idempotent ingestion (no duplicate events on re-ingest)
  - TimelineEvent immutability (append-only)
  - Conversation API: list, filters, detail PATCH assignment audit event
  - Reply endpoint: 400 without WA thread / closed 24h window
  - All endpoints require auth
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.omni import services
from apps.omni.models import Conversation, TimelineEvent
from apps.whatsapp.models import WAConversation, WAMessage
from .factories import make_admin, make_anon_client, make_customer

CONV_URL = '/api/omni/conversations/'


def _timeline_url(pk):
    return f'/api/omni/conversations/{pk}/timeline/'


def _reply_url(pk):
    return f'/api/omni/conversations/{pk}/reply/'


def _make_wa_message(customer=None, wa_id='201012345678', direction='inbound',
                     body='مرحباً', window_open=True):
    wa_conv, _ = WAConversation.objects.get_or_create(wa_id=wa_id)
    if customer is not None and wa_conv.customer_id is None:
        wa_conv.customer = customer
    wa_conv.window_expires_at = (
        timezone.now() + timedelta(hours=23) if window_open
        else timezone.now() - timedelta(hours=1)
    )
    wa_conv.save()
    return WAMessage.objects.create(
        conversation=wa_conv, direction=direction, body=body,
    )


class ResolveConversationTests(TestCase):

    def test_creates_new_conversation_for_unknown_phone(self):
        convo = services.resolve_conversation(phone='201099887766', channel='voice')
        self.assertIsNone(convo.customer)
        self.assertEqual(convo.contact_phone, '201099887766')
        self.assertEqual(convo.created_from_channel, 'voice')

    def test_reuses_active_conversation_for_same_customer(self):
        customer = make_customer()
        c1 = services.resolve_conversation(customer=customer, channel='whatsapp')
        c2 = services.resolve_conversation(customer=customer, channel='voice')
        self.assertEqual(c1.pk, c2.pk)

    def test_matches_by_phone_tail_and_adopts_customer(self):
        # Anonymous conversation opened from a call (international format)
        anon = services.resolve_conversation(phone='201012345678', channel='voice')
        self.assertIsNone(anon.customer)
        # Later, the same phone matches a Customer (local format, same 9-digit tail)
        customer = make_customer(phone='01012345678')
        convo = services.resolve_conversation(customer=customer, phone='201012345678')
        self.assertEqual(convo.pk, anon.pk)
        convo.refresh_from_db()
        self.assertEqual(convo.customer_id, customer.pk)

    def test_closed_conversation_is_not_reused(self):
        customer = make_customer()
        c1 = services.resolve_conversation(customer=customer)
        c1.status = 'closed'
        c1.save(update_fields=['status'])
        c2 = services.resolve_conversation(customer=customer)
        self.assertNotEqual(c1.pk, c2.pk)


class IngestionTests(TestCase):

    def test_wa_message_signal_creates_timeline_event(self):
        customer = make_customer()
        msg = _make_wa_message(customer=customer)

        event = TimelineEvent.objects.get(
            object_id=msg.pk, content_type__model='wamessage')
        self.assertEqual(event.event_type, 'message_in')
        self.assertEqual(event.channel, 'whatsapp')
        self.assertEqual(event.summary, 'مرحباً')

        # Thread got linked to the umbrella
        msg.conversation.refresh_from_db()
        self.assertEqual(msg.conversation.omni_conversation_id, event.conversation_id)
        self.assertEqual(event.conversation.customer_id, customer.pk)
        self.assertIsNotNone(event.conversation.first_inbound_at)

    def test_inbound_message_reopens_resolved_conversation(self):
        customer = make_customer()
        first = _make_wa_message(customer=customer, body='أول رسالة')
        convo = first.conversation.omni_conversation
        convo.status = 'resolved'
        convo.save(update_fields=['status'])

        _make_wa_message(customer=customer, body='رسالة جديدة')
        convo.refresh_from_db()
        self.assertEqual(convo.status, 'open')

    def test_call_log_lands_in_same_umbrella_as_whatsapp(self):
        """One customer, many channels, ONE timeline."""
        customer = make_customer(phone='01012345678')
        msg = _make_wa_message(customer=customer)
        umbrella = msg.conversation.omni_conversation

        log = CallLog.objects.create(
            phone_number='01012345678', customer=customer,
            direction='inbound', status='answered',
            purpose='reservation', duration_seconds=95,
        )
        event = TimelineEvent.objects.get(
            object_id=log.pk, content_type__model='calllog')
        self.assertEqual(event.conversation_id, umbrella.pk)
        self.assertEqual(event.event_type, 'call')
        self.assertEqual(event.payload['duration_seconds'], 95)

    def test_missed_call_event_type(self):
        log = CallLog.objects.create(
            phone_number='01055554444', direction='inbound', status='no_answer',
        )
        event = TimelineEvent.objects.get(
            object_id=log.pk, content_type__model='calllog')
        self.assertEqual(event.event_type, 'call_missed')

    def test_ingestion_is_idempotent(self):
        msg = _make_wa_message()
        self.assertEqual(TimelineEvent.objects.count(), 1)
        # Re-ingest (as backfill_omni would on a re-run)
        self.assertIsNone(services.ingest_wa_message(msg))
        self.assertEqual(TimelineEvent.objects.count(), 1)

    def test_timeline_event_is_append_only(self):
        msg = _make_wa_message()
        event = TimelineEvent.objects.first()
        event.summary = 'تعديل ممنوع'
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()


class ConversationAPITests(TestCase):

    def setUp(self):
        self.user, self.profile, self.client_api = make_admin('omni_admin')
        self.customer = make_customer()
        self.msg = _make_wa_message(customer=self.customer)
        self.convo = self.msg.conversation.omni_conversation

    def test_requires_auth(self):
        anon = make_anon_client()
        self.assertEqual(anon.get(CONV_URL).status_code, 401)
        self.assertEqual(anon.get(_timeline_url(self.convo.pk)).status_code, 401)
        self.assertEqual(anon.post(_reply_url(self.convo.pk), {'body': 'x'}).status_code, 401)

    def test_list_and_filters(self):
        resp = self.client_api.get(CONV_URL)
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['customer_name'], self.customer.name)
        self.assertIsNotNone(results[0]['wa_thread'])

        # status filter
        resp = self.client_api.get(CONV_URL, {'status': 'closed'})
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 0)

        # search by customer name
        resp = self.client_api.get(CONV_URL, {'q': 'أحمد'})
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)

    def test_timeline_endpoint(self):
        resp = self.client_api.get(_timeline_url(self.convo.pk))
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['event_type'], 'message_in')
        self.assertEqual(results[0]['native_model'], 'whatsapp.wamessage')

    def test_patch_assignment_writes_audit_event(self):
        resp = self.client_api.patch(
            f'{CONV_URL}{self.convo.pk}/',
            {'assigned_to': self.profile.pk}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            TimelineEvent.objects.filter(
                conversation=self.convo, event_type='assignment').exists()
        )

    def test_reply_without_wa_thread_400(self):
        convo = services.resolve_conversation(phone='201077776666', channel='voice')
        resp = self.client_api.post(_reply_url(convo.pk), {'body': 'مرحبا'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_reply_with_closed_window_400(self):
        msg = _make_wa_message(wa_id='201066665555', window_open=False)
        convo = msg.conversation.omni_conversation
        resp = self.client_api.post(_reply_url(convo.pk), {'body': 'مرحبا'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('نافذة', resp.data['detail'])
