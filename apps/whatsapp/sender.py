"""
apps/whatsapp/sender.py

WhatsApp outbound message sender — account-aware facade (doc 15 Phase 1).

Builds Meta Cloud API message payloads and sends them through the provider
resolved for a ChannelAccount (apps/omni/providers). All legacy call sites
(`WhatsAppSender()` with no account) send from the channel's default account,
falling back to env credentials — behaviour is unchanged for them.

Usage:
    from apps.whatsapp.sender import WhatsAppSender

    sender = WhatsAppSender()                    # default account (OTP, portal, campaigns…)
    sender = WhatsAppSender(account=account)     # a specific company number
    sender.send_text(wa_id='201001234567', body='مرحباً!')
    sender.send_template(wa_id='201001234567', template_name='otp_delivery',
                         variables=[{'type': 'text', 'text': '123456'}])

Configuration:
    Per-account: ChannelAccount.credentials {'token', 'phone_number_id'}
    Env fallback: WHATSAPP_TOKEN + WHATSAPP_PHONE_NUMBER_ID (+ _API_VERSION)
"""
import logging

from django.utils import timezone

logger = logging.getLogger('elrezeiky.whatsapp')


class WhatsAppSender:

    def __init__(self, account=None):
        if account is None:
            try:
                from apps.omni.models import ChannelAccount
                account = ChannelAccount.default_for('whatsapp')
            except Exception:
                account = None
        self.account = account

        from apps.omni.providers import get_provider
        self.provider = get_provider(account)

    @property
    def is_configured(self) -> bool:
        """Whether the resolved provider has credentials to actually send."""
        return self.provider.configured

    # ── Internal send ─────────────────────────────────────────────────────────

    def _post(self, payload: dict) -> dict:
        result = self.provider.send_message(payload)
        if self.account is not None:
            try:
                self.account.touch_heartbeat('connected')
            except Exception:
                pass
        return result

    def _base(self, wa_id: str) -> dict:
        return {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': _normalise_wa_id(wa_id),
        }

    # ── Public send methods ───────────────────────────────────────────────────

    def send_text(self, wa_id: str, body: str, preview_url: bool = False) -> dict:
        payload = {**self._base(wa_id), 'type': 'text',
                   'text': {'body': body, 'preview_url': preview_url}}
        result = self._post(payload)
        self._record_outbound(wa_id, 'text', body=body, result=result)
        return result

    def send_template(self, wa_id: str, template_name: str, language: str = 'ar',
                      variables: list | None = None) -> dict:
        components = []
        if variables:
            components.append({
                'type': 'body',
                'parameters': variables,
            })
        payload = {
            **self._base(wa_id),
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language},
                'components': components,
            },
        }
        result = self._post(payload)
        self._record_outbound(wa_id, 'template', body=template_name, result=result)
        return result

    def send_otp(self, wa_id: str, otp_display: str, template_name: str = 'otp_delivery') -> dict:
        """Send OTP via authentication template."""
        return self.send_template(
            wa_id=wa_id,
            template_name=template_name,
            variables=[{'type': 'text', 'text': otp_display}],
        )

    def send_document(self, wa_id: str, media_id: str,
                      caption: str = '', filename: str = '') -> dict:
        payload = {
            **self._base(wa_id),
            'type': 'document',
            'document': {'id': media_id, 'caption': caption, 'filename': filename},
        }
        result = self._post(payload)
        self._record_outbound(wa_id, 'document', body=caption, result=result)
        return result

    def send_image(self, wa_id: str, media_id: str, caption: str = '') -> dict:
        payload = {
            **self._base(wa_id),
            'type': 'image',
            'image': {'id': media_id, 'caption': caption},
        }
        result = self._post(payload)
        self._record_outbound(wa_id, 'image', body=caption, result=result)
        return result

    def mark_read(self, wamid: str) -> dict:
        """Send a read receipt back to Meta."""
        payload = {
            'messaging_product': 'whatsapp',
            'status': 'read',
            'message_id': wamid,
        }
        return self._post(payload)

    # ── Internal record helper ────────────────────────────────────────────────

    def _record_outbound(self, wa_id: str, msg_type: str,
                         body: str = '', result: dict | None = None):
        """Create WAConversation + WAMessage for the outbound send."""
        try:
            from apps.whatsapp.models import WAConversation, WAMessage
            conversation, _ = WAConversation.objects.get_or_create(
                account=self.account,
                wa_id=_normalise_wa_id(wa_id),
                defaults={'status': 'open'},
            )
            wamid = ''
            if result and 'messages' in result:
                wamid = result['messages'][0].get('id', '')

            WAMessage.objects.create(
                conversation=conversation,
                direction='outbound',
                message_type=msg_type,
                status='sent',
                wamid=wamid,
                body=body,
                sent_at=timezone.now(),
            )
            WAConversation.objects.filter(pk=conversation.pk).update(
                last_message_preview=body[:255] or f'[{msg_type}]',
                last_message_at=timezone.now(),
            )
        except Exception as exc:
            logger.warning('WhatsAppSender._record_outbound failed: %s', exc)


def _normalise_wa_id(phone: str) -> str:
    """Normalise phone to international format without + (e.g. '201001234567')."""
    clean = phone.strip().replace(' ', '').replace('-', '').replace('+', '')
    if clean.startswith('0') and len(clean) == 11:
        clean = '20' + clean[1:]
    return clean
