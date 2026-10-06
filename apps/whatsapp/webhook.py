"""
apps/whatsapp/webhook.py

Meta WhatsApp Cloud API webhook processor.

Entry point: process_webhook(payload: dict) → None

Responsibilities:
  1. Parse inbound message events → create WAMessage + update WAConversation
  2. Parse status update events (sent/delivered/read) → update WAMessage.status
  3. Log every payload to WAWebhookLog (immutable audit)
  4. Extend WAConversation.window_expires_at on every inbound message
  5. Auto-match customer by caller phone number

NEVER raises — all errors are caught and stored in WAWebhookLog.processing_error.
"""
import logging
from django.utils import timezone

logger = logging.getLogger('elrezeiky.whatsapp')


def process_webhook(payload: dict) -> None:
    """
    Top-level webhook processor. Called from the view after signature verification.
    Logs raw payload first, then processes — even if processing fails, the log exists.
    """
    from apps.whatsapp.models import WAWebhookLog

    log = WAWebhookLog.objects.create(
        object_type=payload.get('object', ''),
        payload=payload,
    )

    try:
        _process(payload, log)
        log.processed = True
        log.save(update_fields=['processed'])
    except Exception as exc:
        log.processing_error = str(exc)
        log.save(update_fields=['processing_error', 'processed'])
        logger.error('WhatsApp webhook processing error: %s', exc, exc_info=True)


def _process(payload: dict, log) -> None:
    """Parse the Meta webhook payload and dispatch to handlers."""
    entries = payload.get('entry', [])
    for entry in entries:
        entry_id = entry.get('id', '')
        for change in entry.get('changes', []):
            value = change.get('value', {})
            phone_number_id = value.get('metadata', {}).get('phone_number_id', '')

            # Update log metadata
            log.entry_id = entry_id
            log.phone_number_id = phone_number_id

            # Route to the company number this webhook belongs to
            account = _resolve_account(phone_number_id, value)

            # Inbound messages
            for msg in value.get('messages', []):
                wa_msg = _handle_inbound_message(msg, value, phone_number_id, account)
                if wa_msg:
                    log.wa_message = wa_msg

            # Status updates (sent / delivered / read / failed)
            for status in value.get('statuses', []):
                _handle_status_update(status)


def _resolve_account(phone_number_id: str, value: dict):
    """
    ChannelAccount for this webhook's phone_number_id (multi-number routing).

    Unknown phone_number_id → auto-register a ChannelAccount so no message is
    ever lost; the new number surfaces on the accounts dashboard for an admin
    to name and assign. Returns None only when phone_number_id is missing
    (legacy/default single-number setups keep working with account=None).
    """
    if not phone_number_id:
        return None
    try:
        from apps.omni.models import ChannelAccount

        account = ChannelAccount.objects.filter(
            channel='whatsapp', provider_ref=phone_number_id,
        ).first()
        if account is None:
            display = value.get('metadata', {}).get('display_phone_number', '')
            account = ChannelAccount.objects.create(
                channel='whatsapp',
                name=f'رقم جديد {display or phone_number_id} (غير مُسمّى)',
                phone_or_handle=display or phone_number_id,
                provider='meta_cloud',
                provider_ref=phone_number_id,
            )
            logger.warning(
                'WhatsApp webhook: auto-registered unknown phone_number_id %s '
                'as ChannelAccount #%s — name and assign it in /omni/accounts',
                phone_number_id, account.pk,
            )
        account.touch_heartbeat('connected')
        return account
    except Exception as exc:
        logger.error('WhatsApp webhook: account resolution failed: %s', exc)
        return None


def _handle_inbound_message(msg: dict, value: dict, phone_number_id: str, account=None):
    """Create or update WAConversation + WAMessage for an inbound message."""
    from apps.whatsapp.models import WAConversation, WAMessage, WAMediaFile

    wa_id   = msg.get('from', '')
    wamid   = msg.get('id', '')
    msg_type = msg.get('type', 'text')
    timestamp = msg.get('timestamp')

    if not wa_id:
        return None

    # Duplicate detection — Meta retries webhook delivery; wamid is globally unique
    if wamid and WAMessage.objects.filter(wamid=wamid, direction='inbound').exists():
        logger.debug('Duplicate webhook delivery for wamid %s — skipped', wamid)
        return None

    # Get or create the thread for this (company number, customer) pair
    conversation, created = WAConversation.objects.get_or_create(
        account=account,
        wa_id=wa_id,
        defaults={'status': 'open'},
    )
    if created:
        logger.info('New WhatsApp conversation from %s on account %s',
                    wa_id, account.pk if account else 'default')

    # Extend 24-hour window
    conversation.refresh_window()

    # Build message body
    body = ''
    if msg_type == 'text':
        body = msg.get('text', {}).get('body', '')
    elif msg_type == 'location':
        loc = msg.get('location', {})
        body = f"📍 {loc.get('name', '')} ({loc.get('latitude')}, {loc.get('longitude')})"
    elif msg_type in ('image', 'document', 'audio', 'video', 'sticker'):
        body = f'[{msg_type}]'
    elif msg_type == 'reaction':
        body = msg.get('reaction', {}).get('emoji', '👍')

    # Handle media
    media_obj = None
    if msg_type in ('image', 'document', 'audio', 'video', 'sticker'):
        media_data = msg.get(msg_type, {})
        if media_data.get('id'):
            media_obj = WAMediaFile.objects.create(
                meta_media_id=media_data['id'],
                file_type=msg_type,
                mime_type=media_data.get('mime_type', ''),
                file_name=media_data.get('filename', ''),
                file_size=media_data.get('file_size', 0),
                sha256=media_data.get('sha256', ''),
            )

    wa_msg = WAMessage.objects.create(
        conversation=conversation,
        direction='inbound',
        message_type=msg_type,
        status='delivered',  # inbound = already delivered to us
        wamid=wamid,
        body=body,
        media=media_obj,
        sent_at=timezone.now(),
        delivered_at=timezone.now(),
    )

    # Update conversation preview
    preview = body[:255] if body else f'[{msg_type}]'
    WAConversation.objects.filter(pk=conversation.pk).update(
        last_message_preview=preview,
        last_message_at=timezone.now(),
        unread_count=conversation.unread_count + 1,
        status='open',
    )

    logger.debug('Inbound WhatsApp message from %s: %s', wa_id, preview[:50])
    return wa_msg


def _handle_status_update(status: dict) -> None:
    """Update WAMessage status from a delivery receipt event."""
    from apps.whatsapp.models import WAMessage

    wamid       = status.get('id', '')
    new_status  = status.get('status', '')

    if not wamid:
        return

    try:
        msg = WAMessage.objects.get(wamid=wamid)
    except WAMessage.DoesNotExist:
        logger.debug('Status update for unknown wamid: %s', wamid)
        return

    if new_status == 'delivered':
        msg.mark_delivered()
    elif new_status == 'read':
        msg.mark_read()
    elif new_status == 'failed':
        errors = status.get('errors', [{}])
        code   = str(errors[0].get('code', '')) if errors else ''
        detail = errors[0].get('title', '') if errors else ''
        msg.mark_failed(code=code, message=detail)
