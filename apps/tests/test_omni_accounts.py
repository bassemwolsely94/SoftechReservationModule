"""
apps/tests/test_omni_accounts.py

CEP Phase 1 (doc 15) — multi-account WhatsApp + provider layer.

Tests covering:
  - Credential encryption: roundtrip, plaintext never stored, legacy tolerance
  - Provider resolution: per-account / env fallback / stub providers fail loudly
  - Webhook routing: phone_number_id → ChannelAccount; separate threads per
    company number for the SAME customer; both threads share ONE umbrella
  - Unknown phone_number_id auto-registers a ChannelAccount (no message loss)
  - Webhook duplicate delivery (same wamid) is skipped
  - Sender records outbound on the account's thread; default account resolution
  - API: credentials never serialized; credentials_input write path encrypts
  - Account stats in serializer
"""
from unittest import mock

from django.test import TestCase

from apps.omni import crypto
from apps.omni.models import ChannelAccount, Conversation
from apps.omni.providers import get_provider
from apps.omni.providers.base import ProviderError
from apps.omni.providers.meta_cloud import MetaCloudProvider
from apps.omni.providers.stubs import AndroidBridgeProvider
from apps.whatsapp.models import WAConversation, WAMessage
from apps.whatsapp.webhook import process_webhook
from .factories import make_admin, make_customer

ACCOUNTS_URL = '/api/omni/accounts/'


def make_account(name='رقم المركز', phone='201000000001', ref='PNID-1', **kw):
    return ChannelAccount.objects.create(
        channel='whatsapp', name=name, phone_or_handle=phone,
        provider='meta_cloud', provider_ref=ref, **kw,
    )


def webhook_payload(phone_number_id, from_wa='201012345678', wamid='wamid.X1',
                    text='مرحبا'):
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'id': 'ENTRY1',
            'changes': [{
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {
                        'phone_number_id': phone_number_id,
                        'display_phone_number': '20100000000X',
                    },
                    'messages': [{
                        'from': from_wa,
                        'id': wamid,
                        'type': 'text',
                        'timestamp': '1700000000',
                        'text': {'body': text},
                    }],
                },
                'field': 'messages',
            }],
        }],
    }


class CryptoTests(TestCase):

    def test_roundtrip(self):
        data = {'token': 'EAAG-secret', 'phone_number_id': '123'}
        stored = crypto.encrypt_credentials(data)
        self.assertEqual(list(stored.keys()), ['_enc'])
        self.assertNotIn('EAAG-secret', str(stored))
        self.assertEqual(crypto.decrypt_credentials(stored), data)

    def test_empty_and_legacy(self):
        self.assertEqual(crypto.encrypt_credentials({}), {})
        self.assertEqual(crypto.decrypt_credentials({}), {})
        # Legacy plaintext rows pass through
        self.assertEqual(crypto.decrypt_credentials({'token': 'x'}), {'token': 'x'})

    def test_model_helpers_never_store_plaintext(self):
        acc = make_account()
        acc.set_credentials({'token': 'super-secret'})
        acc.save()
        acc.refresh_from_db()
        self.assertNotIn('super-secret', str(acc.credentials))
        self.assertEqual(acc.get_credentials()['token'], 'super-secret')


class ProviderTests(TestCase):

    def test_per_account_credentials_win_over_env(self):
        acc = make_account()
        acc.set_credentials({'token': 'acc-token', 'phone_number_id': 'acc-pnid'})
        acc.save()
        with self.settings(WHATSAPP_TOKEN='env-token', WHATSAPP_PHONE_NUMBER_ID='env-pnid'):
            p = get_provider(acc)
        self.assertIsInstance(p, MetaCloudProvider)
        self.assertEqual(p.token, 'acc-token')
        self.assertEqual(p.phone_id, 'acc-pnid')

    def test_env_fallback_for_account_without_credentials(self):
        acc = make_account(ref='PNID-ENV')
        with self.settings(WHATSAPP_TOKEN='env-token', WHATSAPP_PHONE_NUMBER_ID='env-pnid'):
            p = get_provider(acc)
            self.assertEqual(p.token, 'env-token')
            # provider_ref wins over env phone id for a real account
            self.assertEqual(p.phone_id, 'PNID-ENV')

    def test_none_account_uses_env(self):
        with self.settings(WHATSAPP_TOKEN='env-token', WHATSAPP_PHONE_NUMBER_ID='env-pnid'):
            p = get_provider(None)
            self.assertEqual(p.phone_id, 'env-pnid')

    def test_unconfigured_raises_provider_error(self):
        with self.settings(WHATSAPP_TOKEN='', WHATSAPP_PHONE_NUMBER_ID=''):
            p = get_provider(None)
            with self.assertRaises(ProviderError):
                p.send_message({'type': 'text'})

    def test_android_bridge_fails_loudly(self):
        acc = make_account(name='جوال فرع', ref='BR-1')
        acc.provider = 'android_bridge'
        acc.save()
        p = get_provider(acc)
        self.assertIsInstance(p, AndroidBridgeProvider)
        with self.assertRaises(ProviderError):
            p.send_message({})


class WebhookRoutingTests(TestCase):

    def test_routes_by_phone_number_id(self):
        acc1 = make_account('رقم المركز 1', '201000000001', 'PNID-1')
        acc2 = make_account('رقم فرع المعادي', '201000000002', 'PNID-2')

        # Same customer writes to BOTH company numbers
        process_webhook(webhook_payload('PNID-1', wamid='wamid.A'))
        process_webhook(webhook_payload('PNID-2', wamid='wamid.B'))

        threads = WAConversation.objects.filter(wa_id='201012345678')
        self.assertEqual(threads.count(), 2)
        self.assertEqual(
            {t.account_id for t in threads}, {acc1.pk, acc2.pk},
        )

    def test_two_threads_one_umbrella(self):
        """Doc 15 core promise survives multi-account: ONE customer timeline."""
        make_account('رقم 1', '201000000001', 'PNID-1')
        make_account('رقم 2', '201000000002', 'PNID-2')
        make_customer(phone='01012345678')  # matches wa_id tail

        process_webhook(webhook_payload('PNID-1', wamid='wamid.A'))
        process_webhook(webhook_payload('PNID-2', wamid='wamid.B'))

        umbrellas = {
            t.omni_conversation_id
            for t in WAConversation.objects.filter(wa_id='201012345678')
        }
        self.assertEqual(len(umbrellas), 1)
        convo = Conversation.objects.get(pk=umbrellas.pop())
        self.assertEqual(convo.events.filter(event_type='message_in').count(), 2)

    def test_unknown_phone_number_id_auto_registers_account(self):
        self.assertEqual(ChannelAccount.objects.count(), 0)
        process_webhook(webhook_payload('PNID-NEW', wamid='wamid.N'))

        acc = ChannelAccount.objects.get(provider_ref='PNID-NEW')
        self.assertEqual(acc.channel, 'whatsapp')
        self.assertIn('غير مُسمّى', acc.name)
        self.assertEqual(acc.status, 'connected')  # heartbeat touched
        self.assertEqual(
            WAConversation.objects.get(wa_id='201012345678').account_id, acc.pk)

    def test_duplicate_wamid_skipped(self):
        make_account(ref='PNID-1')
        process_webhook(webhook_payload('PNID-1', wamid='wamid.DUP'))
        process_webhook(webhook_payload('PNID-1', wamid='wamid.DUP'))
        self.assertEqual(
            WAMessage.objects.filter(wamid='wamid.DUP').count(), 1)

    def test_webhook_heartbeat(self):
        acc = make_account(ref='PNID-1')
        acc.status = 'disconnected'
        acc.save()
        process_webhook(webhook_payload('PNID-1'))
        acc.refresh_from_db()
        self.assertEqual(acc.status, 'connected')
        self.assertIsNotNone(acc.last_heartbeat_at)


class SenderAccountTests(TestCase):

    def _fake_send(self):
        return mock.patch.object(
            MetaCloudProvider, 'send_message',
            return_value={'messages': [{'id': 'wamid.OUT1'}]},
        )

    def test_outbound_recorded_on_account_thread(self):
        from apps.whatsapp.sender import WhatsAppSender
        acc = make_account(ref='PNID-1')
        acc.set_credentials({'token': 't', 'phone_number_id': 'PNID-1'})
        acc.save()

        with self._fake_send():
            WhatsAppSender(account=acc).send_text('201012345678', 'أهلاً')

        thread = WAConversation.objects.get(wa_id='201012345678')
        self.assertEqual(thread.account_id, acc.pk)
        msg = thread.messages.get()
        self.assertEqual(msg.direction, 'outbound')
        self.assertEqual(msg.wamid, 'wamid.OUT1')
        acc.refresh_from_db()
        self.assertIsNotNone(acc.last_heartbeat_at)

    def test_default_account_resolution(self):
        from apps.whatsapp.sender import WhatsAppSender
        make_account('عادي', '201000000001', 'PNID-1')
        default = make_account('الافتراضي', '201000000002', 'PNID-2', is_default=True)

        with self._fake_send():
            WhatsAppSender().send_text('201012345678', 'OTP')

        thread = WAConversation.objects.get(wa_id='201012345678')
        self.assertEqual(thread.account_id, default.pk)


class AccountAPITests(TestCase):

    def setUp(self):
        self.user, self.profile, self.client_api = make_admin('omni_acc_admin')

    def test_credentials_never_serialized(self):
        acc = make_account()
        acc.set_credentials({'token': 'top-secret'})
        acc.save()
        resp = self.client_api.get(ACCOUNTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('top-secret', str(resp.data))
        row = (resp.data.get('results') or resp.data)[0]
        self.assertNotIn('credentials', row.keys())        # raw field excluded
        self.assertNotIn('credentials_input', row.keys())  # write-only
        self.assertTrue(row['has_credentials'])

    def test_create_with_credentials_input_encrypts(self):
        resp = self.client_api.post(ACCOUNTS_URL, {
            'channel': 'whatsapp',
            'name': 'واتساب فرع مدينة نصر 1',
            'phone_or_handle': '201000000009',
            'provider': 'meta_cloud',
            'provider_ref': 'PNID-9',
            'credentials_input': {'token': 'branch-token', 'phone_number_id': 'PNID-9'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        acc = ChannelAccount.objects.get(provider_ref='PNID-9')
        self.assertNotIn('branch-token', str(acc.credentials))
        self.assertEqual(acc.get_credentials()['token'], 'branch-token')

    def test_stats_in_response(self):
        acc = make_account(ref='PNID-1')
        thread = WAConversation.objects.create(account=acc, wa_id='201012345678',
                                               unread_count=3)
        WAMessage.objects.create(conversation=thread, direction='inbound', body='هاي')
        resp = self.client_api.get(f'{ACCOUNTS_URL}{acc.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['stats']['threads'], 1)
        self.assertEqual(resp.data['stats']['inbound_today'], 1)
        self.assertEqual(resp.data['stats']['unread'], 3)
