"""
apps/tests/test_social.py

CEP Phase 3 (doc 15) — social channels.

Tests covering:
  - Meta Graph webhook: routes Messenger by page id, auto-registers unknown
    pages, dedups by mid, echo → outbound, Instagram object → instagram channel
  - Telegram webhook: secret-token account resolution, message ingest, dedup
  - SocialMessage → omni TimelineEvent (one umbrella per thread, no phone match)
  - omni ReplyView routes to a social thread (mocked provider)
  - Provider registry resolves meta_graph + telegram_bot
"""
from unittest import mock

from django.test import TestCase

from apps.omni.models import ChannelAccount, Conversation, TimelineEvent
from apps.omni.providers import get_provider
from apps.omni.providers.meta_graph import MetaGraphProvider
from apps.omni.providers.telegram_bot import TelegramBotProvider
from apps.social.models import SocialMessage, SocialThread
from apps.social.webhooks import process_meta_webhook, process_telegram_update
from .factories import make_admin

META_URL = '/api/social/webhook/meta/'


def messenger_payload(page_id, sender_id='USER1', mid='m.1', text='مرحبا', is_echo=False):
    msg = {'mid': mid, 'text': text}
    if is_echo:
        msg['is_echo'] = True
    return {
        'object': 'page',
        'entry': [{
            'id': page_id,
            'messaging': [{
                'sender': {'id': 'PAGE' if is_echo else sender_id},
                'recipient': {'id': sender_id if is_echo else page_id},
                'message': msg,
            }],
        }],
    }


class MetaWebhookTests(TestCase):

    def test_routes_by_page_and_ingests(self):
        acc = ChannelAccount.objects.create(
            channel='messenger', name='صفحة الرزيقي', phone_or_handle='PAGE-1',
            provider='meta_graph', provider_ref='PAGE-1')
        process_meta_webhook(messenger_payload('PAGE-1', text='عايز دوا'))

        thread = SocialThread.objects.get(account=acc, external_user_id='USER1')
        msg = thread.messages.get()
        self.assertEqual(msg.direction, 'inbound')
        self.assertEqual(msg.body, 'عايز دوا')
        # Umbrella conversation created + timeline event
        self.assertIsNotNone(thread.omni_conversation_id)
        self.assertTrue(TimelineEvent.objects.filter(
            conversation=thread.omni_conversation,
            event_type='message_in', channel='messenger').exists())

    def test_auto_registers_unknown_page(self):
        self.assertEqual(ChannelAccount.objects.count(), 0)
        process_meta_webhook(messenger_payload('PAGE-NEW'))
        acc = ChannelAccount.objects.get(provider_ref='PAGE-NEW')
        self.assertEqual(acc.channel, 'messenger')
        self.assertEqual(acc.status, 'connected')

    def test_instagram_object_maps_channel(self):
        payload = messenger_payload('IG-1')
        payload['object'] = 'instagram'
        process_meta_webhook(payload)
        acc = ChannelAccount.objects.get(provider_ref='IG-1')
        self.assertEqual(acc.channel, 'instagram')

    def test_dedup_by_mid(self):
        ChannelAccount.objects.create(
            channel='messenger', name='p', phone_or_handle='PAGE-1',
            provider='meta_graph', provider_ref='PAGE-1')
        process_meta_webhook(messenger_payload('PAGE-1', mid='dup.1'))
        process_meta_webhook(messenger_payload('PAGE-1', mid='dup.1'))
        self.assertEqual(SocialMessage.objects.filter(external_id='dup.1').count(), 1)

    def test_echo_is_outbound(self):
        ChannelAccount.objects.create(
            channel='messenger', name='p', phone_or_handle='PAGE-1',
            provider='meta_graph', provider_ref='PAGE-1')
        process_meta_webhook(
            messenger_payload('PAGE-1', mid='echo.1', text='ردنا', is_echo=True))
        msg = SocialMessage.objects.get(external_id='echo.1')
        self.assertEqual(msg.direction, 'outbound')


class TelegramWebhookTests(TestCase):

    def setUp(self):
        self.account = ChannelAccount.objects.create(
            channel='telegram', name='بوت الرزيقي', phone_or_handle='@rezeiky_bot',
            provider='telegram_bot', provider_ref='')
        self.account.set_credentials({'token': 'BOT-TOKEN', 'webhook_secret': 'S3CRET'})
        self.account.save()

    def _update(self, chat_id='555', mid=1, text='سلام'):
        return {
            'update_id': 1,
            'message': {
                'message_id': mid,
                'chat': {'id': int(chat_id)},
                'from': {'first_name': 'أحمد', 'username': 'ahmed'},
                'text': text,
            },
        }

    def test_resolve_by_secret_and_ingest(self):
        from apps.social.webhooks import resolve_telegram_account
        self.assertEqual(resolve_telegram_account('S3CRET'), self.account)
        self.assertIsNone(resolve_telegram_account('WRONG'))

        process_telegram_update(self._update(), self.account)
        thread = SocialThread.objects.get(account=self.account, external_user_id='555')
        self.assertEqual(thread.display_name, 'أحمد')
        self.assertEqual(thread.messages.get().body, 'سلام')
        self.assertTrue(thread.window_open)  # telegram always open

    def test_dedup(self):
        process_telegram_update(self._update(mid=7), self.account)
        process_telegram_update(self._update(mid=7), self.account)
        self.assertEqual(
            SocialMessage.objects.filter(thread__account=self.account).count(), 1)

    def test_webhook_view_rejects_bad_secret(self):
        resp = self.client.post(
            '/api/social/webhook/telegram/', data='{}',
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='WRONG')
        self.assertEqual(resp.status_code, 403)


class ProviderRegistryTests(TestCase):

    def test_meta_graph_and_telegram_resolve(self):
        mg = ChannelAccount.objects.create(
            channel='messenger', name='p', phone_or_handle='P',
            provider='meta_graph', provider_ref='P')
        tg = ChannelAccount.objects.create(
            channel='telegram', name='b', phone_or_handle='B', provider='telegram_bot')
        self.assertIsInstance(get_provider(mg), MetaGraphProvider)
        self.assertIsInstance(get_provider(tg), TelegramBotProvider)


class SocialReplyTests(TestCase):

    def setUp(self):
        self.user, self.profile, self.client_api = make_admin('social_admin')
        self.account = ChannelAccount.objects.create(
            channel='telegram', name='بوت', phone_or_handle='@b',
            provider='telegram_bot')
        self.account.set_credentials({'token': 'T'})
        self.account.save()
        process_telegram_update({
            'message': {'message_id': 1, 'chat': {'id': 999},
                        'from': {'first_name': 'منى'}, 'text': 'عندكم بانادول؟'},
        }, self.account)
        self.thread = SocialThread.objects.get(external_user_id='999')

    def test_reply_routes_to_social(self):
        convo_id = self.thread.omni_conversation_id
        with mock.patch.object(
                TelegramBotProvider, 'send_message',
                return_value={'ok': True, 'result': {'message_id': 42}}) as send:
            resp = self.client_api.post(
                f'/api/omni/conversations/{convo_id}/reply/',
                {'body': 'أيوه متوفر'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['channel'], 'telegram')
        send.assert_called_once()
        # Outbound SocialMessage recorded + on timeline
        self.assertTrue(SocialMessage.objects.filter(
            thread=self.thread, direction='outbound', body='أيوه متوفر').exists())
