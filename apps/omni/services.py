"""
apps/omni/services.py

Conversation resolution + event ingestion (the emit facade).

Every channel app and ERP module enters the unified timeline through
these functions — this is the single seam where a message broker could
later replace in-process calls (see doc 15 §2.4).

Public API:
    resolve_conversation(customer=..., phone=..., channel=..., branch=...)
    add_event(conversation, event_type, ...)
    emit(event_type, obj, *, customer=None, phone='', channel='', ...)
    ingest_wa_message(msg)
    ingest_call_log(log)
"""
import logging

from django.db import transaction
from django.utils import timezone

from apps.omni.models import ChannelAccount, Conversation, TimelineEvent

logger = logging.getLogger('elrezeiky.omni')


def _phone_tail(phone: str) -> str:
    """Last 9 digits — same matching convention as WAConversation/CallSession."""
    return (phone or '').strip().replace(' ', '')[-9:]


def resolve_conversation(*, customer=None, phone: str = '',
                         channel: str = '', branch=None) -> Conversation:
    """
    Find the active umbrella conversation for a contact, or create one.

    Priority: match by customer → match by phone tail → create new.
    "Active" = open / pending / snoozed (Conversation.ACTIVE_STATUSES).
    """
    qs = Conversation.objects.filter(status__in=Conversation.ACTIVE_STATUSES)

    convo = None
    if customer is not None:
        convo = qs.filter(customer=customer).order_by('-last_activity_at').first()
    if convo is None and phone:
        tail = _phone_tail(phone)
        if tail:
            convo = (
                qs.filter(contact_phone__endswith=tail)
                .order_by('-last_activity_at')
                .first()
            )
            # Adopt the customer on a previously-anonymous conversation
            if convo and customer is not None and convo.customer_id is None:
                convo.customer = customer
                convo.save(update_fields=['customer', 'updated_at'])

    if convo is None:
        convo = Conversation.objects.create(
            customer=customer,
            contact_phone=phone or (customer.phone if customer else ''),
            created_from_channel=channel,
            branch=branch,
        )
    return convo


def add_event(conversation: Conversation, event_type: str, *,
              channel: str = '', account: ChannelAccount | None = None,
              obj=None, summary: str = '', actor=None,
              occurred_at=None, payload: dict | None = None) -> TimelineEvent:
    """Append one TimelineEvent and refresh the conversation's list-view cache."""
    event = TimelineEvent.objects.create(
        conversation=conversation,
        event_type=event_type,
        channel=channel,
        account=account,
        native=obj,
        summary=summary[:255],
        actor=actor,
        occurred_at=occurred_at or timezone.now(),
        payload=payload or {},
    )

    update_fields = ['last_activity_at', 'last_event_preview', 'updated_at']
    conversation.last_activity_at = event.occurred_at
    conversation.last_event_preview = summary[:255]
    if event_type == 'message_in':
        if conversation.first_inbound_at is None:
            conversation.first_inbound_at = event.occurred_at
            update_fields.append('first_inbound_at')
        # An inbound message reopens a resolved/closed umbrella
        if conversation.status not in Conversation.ACTIVE_STATUSES:
            conversation.status = 'open'
            update_fields.append('status')
    conversation.save(update_fields=update_fields)

    _run_automations(event)
    return event


def _run_automations(event):
    """Fire the no-code automation engine — never breaks ingestion."""
    try:
        from apps.omni.automation import run_automations
        run_automations(event)
    except Exception:
        logger.exception('omni: automation dispatch failed for event #%s', event.pk)


def emit(event_type: str, obj, *, customer=None, phone: str = '',
         channel: str = '', account: ChannelAccount | None = None,
         summary: str = '', actor=None, occurred_at=None,
         payload: dict | None = None,
         attach_only: bool = False) -> TimelineEvent | None:
    """
    Generic entry point for ERP modules.

    attach_only=True → only append if the contact already has an ACTIVE
    conversation (ERP events should enrich live conversations, not spawn
    empty ones for every invoice in the system).
    """
    try:
        if attach_only:
            qs = Conversation.objects.filter(status__in=Conversation.ACTIVE_STATUSES)
            convo = None
            if customer is not None:
                convo = qs.filter(customer=customer).order_by('-last_activity_at').first()
            if convo is None and phone:
                tail = _phone_tail(phone)
                convo = (
                    qs.filter(contact_phone__endswith=tail)
                    .order_by('-last_activity_at').first()
                    if tail else None
                )
            if convo is None:
                return None
        else:
            convo = resolve_conversation(customer=customer, phone=phone, channel=channel)

        return add_event(
            convo, event_type,
            channel=channel, account=account, obj=obj,
            summary=summary, actor=actor,
            occurred_at=occurred_at, payload=payload,
        )
    except Exception:
        # The timeline must never break the operation that emitted the event
        logger.exception('omni.emit failed for %s %r', event_type, obj)
        return None


def _already_ingested(obj) -> bool:
    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(type(obj))
    return TimelineEvent.objects.filter(content_type=ct, object_id=obj.pk).exists()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Channel ingestion — WhatsApp
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def ingest_wa_message(msg) -> TimelineEvent | None:
    """
    Envelope a whatsapp.WAMessage into the unified timeline.
    Links the WAConversation thread to its umbrella on first contact.
    Idempotent (used by both the live signal and backfill_omni).
    """
    if _already_ingested(msg):
        return None

    wa_conv = msg.conversation

    with transaction.atomic():
        convo = wa_conv.omni_conversation
        if convo is None:
            convo = resolve_conversation(
                customer=wa_conv.customer,
                phone=wa_conv.wa_id,
                channel='whatsapp',
            )
            wa_conv.omni_conversation = convo
            wa_conv.save(update_fields=['omni_conversation', 'updated_at'])

        body = msg.body or f'[{msg.get_message_type_display()}]'
        return add_event(
            convo,
            'message_in' if msg.direction == 'inbound' else 'message_out',
            channel='whatsapp',
            account=getattr(wa_conv, 'account', None),
            obj=msg,
            summary=body,
            actor=msg.sent_by,
            occurred_at=msg.created_at,
            payload={
                'message_type': msg.message_type,
                'status': msg.status,
                'wa_conversation_id': wa_conv.pk,
                'has_media': msg.media_id is not None,
            },
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Channel ingestion — Social (Messenger / Instagram / Telegram)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def ingest_social_message(msg) -> TimelineEvent | None:
    """
    Envelope a social.SocialMessage into the unified timeline.

    Social identities carry no phone number, so the umbrella is linked
    strictly through the thread (never phone matching). Idempotent.
    """
    if _already_ingested(msg):
        return None

    thread = msg.thread
    account = thread.account

    with transaction.atomic():
        convo = thread.omni_conversation
        if convo is None:
            convo = Conversation.objects.create(
                created_from_channel=account.channel,
                subject=thread.display_name or '',
                branch=account.branch,
            )
            thread.omni_conversation = convo
            thread.save(update_fields=['omni_conversation', 'updated_at'])

        body = msg.body or f'[{msg.get_message_type_display()}]'
        return add_event(
            convo,
            'message_in' if msg.direction == 'inbound' else 'message_out',
            channel=account.channel,
            account=account,
            obj=msg,
            summary=body,
            actor=msg.sent_by,
            occurred_at=msg.created_at,
            payload={
                'message_type': msg.message_type,
                'status': msg.status,
                'social_thread_id': thread.pk,
                'attachment_url': msg.attachment_url,
                'display_name': thread.display_name,
            },
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Channel ingestion — Voice (callcenter.CallLog covers AMI + manual logs)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def ingest_call_log(log) -> TimelineEvent | None:
    """Envelope a callcenter.CallLog into the unified timeline. Idempotent."""
    if _already_ingested(log):
        return None

    missed = log.status in ('no_answer', 'busy')
    minutes, seconds = divmod(log.duration_seconds or 0, 60)
    duration = f'{minutes}:{seconds:02d}' if log.duration_seconds else ''
    parts = [log.get_direction_display(), log.get_purpose_display()]
    if duration:
        parts.append(duration)
    summary = ' — '.join(p for p in parts if p)

    convo = resolve_conversation(
        customer=log.customer,
        phone=log.phone_number,
        channel='voice',
        branch=log.branch,
    )
    return add_event(
        convo,
        'call_missed' if missed else 'call',
        channel='voice',
        obj=log,
        summary=summary,
        actor=log.handled_by,
        occurred_at=log.called_at,
        payload={
            'direction': log.direction,
            'status': log.status,
            'purpose': log.purpose,
            'duration_seconds': log.duration_seconds,
            'recording_url': log.recording_url or '',
        },
    )
