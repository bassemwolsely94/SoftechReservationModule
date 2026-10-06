"""
apps/social/webhooks.py

Inbound webhook processors for social channels.

Meta Graph: ONE webhook serves both Facebook Messenger (object="page") and
Instagram DM (object="instagram") — entries are routed to ChannelAccounts by
page/IG id (provider_ref), auto-registering unknown pages exactly like the
WhatsApp webhook does (no message loss).

Telegram: one webhook per bot; the account is identified by the
X-Telegram-Bot-Api-Secret-Token header matched against the account's stored
webhook_secret credential.

NEVER raises — errors land in SocialWebhookLog.processing_error.
"""
import logging

from django.utils import timezone

logger = logging.getLogger('elrezeiky.social')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Meta Graph (Messenger + Instagram)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def process_meta_webhook(payload: dict) -> None:
    from apps.social.models import SocialWebhookLog

    log = SocialWebhookLog.objects.create(source='meta', payload=payload)
    try:
        channel = 'messenger' if payload.get('object') == 'page' else 'instagram'
        for entry in payload.get('entry', []):
            page_id = str(entry.get('id', ''))
            account = _resolve_meta_account(channel, page_id)
            if account is None:
                continue
            for event in entry.get('messaging', []):
                _handle_meta_message(event, account, page_id)
        log.processed = True
        log.save(update_fields=['processed'])
    except Exception as exc:
        log.processing_error = str(exc)
        log.save(update_fields=['processing_error', 'processed'])
        logger.error('Meta webhook processing error: %s', exc, exc_info=True)


def _resolve_meta_account(channel: str, page_id: str):
    if not page_id:
        return None
    from apps.omni.models import ChannelAccount

    account = ChannelAccount.objects.filter(
        channel=channel, provider_ref=page_id).first()
    if account is None:
        account = ChannelAccount.objects.create(
            channel=channel,
            name=f'صفحة جديدة {page_id} (غير مُسمّاة)',
            phone_or_handle=page_id,
            provider='meta_graph',
            provider_ref=page_id,
        )
        logger.warning('Meta webhook: auto-registered unknown %s page %s as account #%s',
                       channel, page_id, account.pk)
    account.touch_heartbeat('connected')
    return account


def _handle_meta_message(event: dict, account, page_id: str):
    from apps.social.models import SocialMessage, SocialThread

    message = event.get('message')
    if not message:
        return  # delivery/read/postback events — not messages (Phase 3 scope)

    mid = message.get('mid', '')
    if mid and SocialMessage.objects.filter(external_id=mid).exists():
        return  # Meta retries webhook delivery

    is_echo = bool(message.get('is_echo'))
    sender_id = str(event.get('sender', {}).get('id', ''))
    recipient_id = str(event.get('recipient', {}).get('id', ''))
    # For echoes (our page replying from another surface) the customer is the recipient
    user_id = recipient_id if is_echo else sender_id
    if not user_id:
        return

    thread, _ = SocialThread.objects.get_or_create(
        account=account, external_user_id=user_id)

    body = message.get('text', '') or ''
    msg_type, attachment_url = 'text', ''
    attachments = message.get('attachments') or []
    if attachments:
        att = attachments[0]
        att_type = att.get('type', 'other')
        msg_type = att_type if att_type in ('image', 'audio', 'video', 'file') else 'other'
        attachment_url = (att.get('payload') or {}).get('url', '') or ''
        if not body:
            body = f'[{msg_type}]'

    SocialMessage.objects.create(
        thread=thread,
        direction='outbound' if is_echo else 'inbound',
        message_type=msg_type,
        status='sent' if is_echo else 'received',
        body=body,
        external_id=mid,
        attachment_url=attachment_url[:1000],
    )

    now = timezone.now()
    updates = {
        'last_message_preview': body[:255],
        'last_message_at': now,
    }
    if not is_echo:
        updates['last_inbound_at'] = now
        updates['unread_count'] = thread.unread_count + 1
    SocialThread.objects.filter(pk=thread.pk).update(**updates)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Telegram
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def resolve_telegram_account(secret_header: str):
    """Match the bot by its webhook_secret credential (accounts are few)."""
    from apps.omni.models import ChannelAccount

    accounts = ChannelAccount.objects.filter(channel='telegram', is_active=True)
    for account in accounts:
        secret = account.get_credentials().get('webhook_secret', '')
        if secret and secret == secret_header:
            return account
    return None


def process_telegram_update(payload: dict, account) -> None:
    from apps.social.models import SocialMessage, SocialThread, SocialWebhookLog

    log = SocialWebhookLog.objects.create(source='telegram', payload=payload)
    try:
        message = payload.get('message') or payload.get('edited_message')
        if not message:
            log.processed = True
            log.save(update_fields=['processed'])
            return

        chat = message.get('chat', {})
        chat_id = str(chat.get('id', ''))
        if not chat_id:
            raise ValueError('telegram update without chat id')

        external_id = f"tg-{chat_id}-{message.get('message_id', '')}"
        if SocialMessage.objects.filter(external_id=external_id).exists():
            log.processed = True
            log.save(update_fields=['processed'])
            return

        sender = message.get('from', {})
        name = ' '.join(p for p in (sender.get('first_name'), sender.get('last_name')) if p) \
            or sender.get('username', '')

        body, msg_type = message.get('text', '') or message.get('caption', ''), 'text'
        for key, t in (('photo', 'image'), ('voice', 'audio'), ('audio', 'audio'),
                       ('video', 'video'), ('document', 'file'), ('sticker', 'sticker')):
            if key in message:
                msg_type = t
                if not body:
                    body = f'[{t}]'
                break

        thread, created = SocialThread.objects.get_or_create(
            account=account, external_user_id=chat_id,
            defaults={'display_name': name},
        )
        if name and thread.display_name != name:
            thread.display_name = name
            thread.save(update_fields=['display_name', 'updated_at'])

        SocialMessage.objects.create(
            thread=thread,
            direction='inbound',
            message_type=msg_type,
            status='received',
            body=body,
            external_id=external_id,
        )
        now = timezone.now()
        SocialThread.objects.filter(pk=thread.pk).update(
            last_message_preview=body[:255],
            last_message_at=now,
            last_inbound_at=now,
            unread_count=thread.unread_count + 1,
        )
        account.touch_heartbeat('connected')

        log.processed = True
        log.save(update_fields=['processed'])
    except Exception as exc:
        log.processing_error = str(exc)
        log.save(update_fields=['processing_error', 'processed'])
        logger.error('Telegram webhook processing error: %s', exc, exc_info=True)
