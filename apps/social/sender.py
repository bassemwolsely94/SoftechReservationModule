"""
apps/social/sender.py

Outbound sends for social threads — builds the provider-specific payload and
records the SocialMessage (which flows into the omni timeline via signal).
"""
import logging

from django.utils import timezone

logger = logging.getLogger('elrezeiky.social')


def send_social_text(thread, body: str, sent_by=None) -> 'object':
    """
    Send a text reply on a social thread through its account's provider.
    Returns the created SocialMessage. Raises ProviderError on send failure.
    """
    from apps.omni.providers import get_provider
    from apps.social.models import SocialMessage, SocialThread

    account = thread.account
    provider = get_provider(account)

    if account.channel in ('messenger', 'instagram'):
        payload = {
            'recipient': {'id': thread.external_user_id},
            'messaging_type': 'RESPONSE',
            'message': {'text': body},
        }
    elif account.channel == 'telegram':
        payload = {'chat_id': thread.external_user_id, 'text': body}
    else:
        from apps.omni.providers.base import ProviderError
        raise ProviderError(f'قناة {account.channel} لا تدعم الإرسال بعد')

    result = provider.send_message(payload)

    external_id = str(
        result.get('message_id', '')                                  # Meta
        or (result.get('result') or {}).get('message_id', '')         # Telegram
    )
    msg = SocialMessage.objects.create(
        thread=thread,
        direction='outbound',
        message_type='text',
        status='sent',
        body=body,
        external_id=external_id,
        sent_by=sent_by,
    )
    SocialThread.objects.filter(pk=thread.pk).update(
        last_message_preview=body[:255],
        last_message_at=timezone.now(),
    )
    try:
        account.touch_heartbeat('connected')
    except Exception:
        pass
    return msg
