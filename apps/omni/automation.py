"""
apps/omni/automation.py

No-code automation engine (doc 15 Phase 4).

run_automations(event) is called from services.add_event() after every
TimelineEvent. It evaluates active rules whose trigger matches the event's
type, checks their conditions, and executes their actions in order. Each
firing is logged immutably as an AutomationRun.

Guardrails:
  - Never raises into the caller (a broken rule must not break messaging).
  - Skips events the engine itself produced (event_type 'automation_action',
    'note', 'assignment', 'status_change') to prevent feedback loops.
  - auto_reply respects the channel send window and only fires on inbound.
"""
import logging

from django.utils import timezone

logger = logging.getLogger('elrezeiky.omni.automation')

# Events the engine must never react to (its own output + internal bookkeeping)
_NON_TRIGGER_EVENTS = {
    'automation_action', 'note', 'assignment', 'status_change', 'sla_breach',
    'message_out',
}


def run_automations(event) -> None:
    if event.event_type in _NON_TRIGGER_EVENTS:
        return
    try:
        from apps.omni.models import AutomationRule
        rules = AutomationRule.objects.filter(
            trigger=event.event_type, is_active=True).order_by('order', 'id')
        for rule in rules:
            fired = _evaluate_rule(rule, event)
            if fired and rule.stop_processing:
                break
    except Exception:
        logger.exception('automation: run failed for event #%s', event.pk)


def _evaluate_rule(rule, event) -> bool:
    conversation = event.conversation
    try:
        matched = _conditions_match(rule.conditions or {}, event, conversation)
    except Exception:
        logger.exception('automation: condition error in rule #%s', rule.pk)
        matched = False

    if not matched:
        return False

    actions_run, error = [], ''
    for action in (rule.actions or []):
        try:
            label = _run_action(action, event, conversation)
            if label:
                actions_run.append(label)
        except Exception as exc:
            error += f'{action.get("type", "?")}: {exc}; '
            logger.exception('automation: action %s failed in rule #%s',
                             action.get('type'), rule.pk)

    from apps.omni.models import AutomationRule, AutomationRun
    AutomationRun.objects.create(
        rule=rule, event=event, conversation=conversation,
        matched=True, actions_run=actions_run, error=error,
    )
    AutomationRule.objects.filter(pk=rule.pk).update(
        run_count=rule.run_count + 1, last_run_at=timezone.now())
    return True


# ── Conditions ────────────────────────────────────────────────────────────────

def _conditions_match(cond: dict, event, conversation) -> bool:
    if 'channel' in cond and event.channel != cond['channel']:
        return False

    if 'text_contains' in cond:
        keywords = cond['text_contains']
        if isinstance(keywords, str):
            keywords = [keywords]
        haystack = (event.summary or '').lower()
        if not any(str(k).lower() in haystack for k in keywords):
            return False

    if cond.get('customer_vip'):
        cust = conversation.customer
        if not (cust and getattr(cust, 'segment', '') == 'vip'):
            return False

    if 'priority' in cond and conversation.priority != cond['priority']:
        return False

    if cond.get('unassigned') and conversation.assigned_to_id is not None:
        return False

    if 'sentiment' in cond:
        if (event.payload or {}).get('sentiment') != cond['sentiment']:
            return False

    return True


# ── Actions ─────────────────────────────────────────────────────────────────

def _run_action(action: dict, event, conversation) -> str:
    atype = action.get('type', '')

    if atype == 'set_priority':
        conversation.priority = action.get('priority', 'high')
        conversation.save(update_fields=['priority', 'updated_at'])
        return f'set_priority={conversation.priority}'

    if atype == 'set_status':
        conversation.status = action.get('status', 'pending')
        conversation.save(update_fields=['status', 'updated_at'])
        return f'set_status={conversation.status}'

    if atype == 'add_tag':
        tag = action.get('tag', '')
        prefix = f'[{tag}] '
        if tag and prefix not in (conversation.subject or ''):
            conversation.subject = (prefix + (conversation.subject or ''))[:255]
            conversation.save(update_fields=['subject', 'updated_at'])
        return f'add_tag={tag}'

    if atype == 'assign_role':
        from apps.users.models import StaffProfile
        role = action.get('role', 'supervisor')
        staff = StaffProfile.objects.filter(role=role, is_active=True).order_by('id').first()
        if staff and conversation.assigned_to_id is None:
            conversation.assigned_to = staff
            conversation.save(update_fields=['assigned_to', 'updated_at'])
            return f'assign_role={role}→{staff.pk}'
        return ''

    if atype == 'notify_role':
        from apps.notifications.models import Notification
        role = action.get('role', 'supervisor')
        text = action.get('text', 'إجراء آلي على محادثة')
        who = (conversation.customer.name if conversation.customer_id
               else conversation.contact_phone or 'عميل')
        Notification.send_to_roles(
            roles=[role], notification_type='omni_automation',
            title=f'⚙️ أتمتة: {text}',
            body=f'المحادثة #{conversation.pk} — {who}',
            dedup_key=f'omni-auto-{conversation.pk}-{text}', dedup_once=True,
        )
        return f'notify_role={role}'

    if atype == 'add_note':
        from apps.omni import services
        services.add_event(
            conversation, 'automation_action',
            summary=f'⚙️ {action.get("text", "")}'[:255],
        )
        return 'add_note'

    if atype == 'auto_reply':
        return _auto_reply(action, event, conversation)

    logger.warning('automation: unknown action type %r', atype)
    return ''


def _auto_reply(action: dict, event, conversation) -> str:
    """Send a canned reply on the triggering inbound message's channel."""
    if event.event_type != 'message_in':
        return ''
    text = action.get('text', '')
    if not text:
        return ''

    # WhatsApp
    wa = conversation.wa_threads.order_by('-last_message_at').first()
    if wa is not None and event.channel == 'whatsapp':
        if not wa.window_open:
            return 'auto_reply_skipped(window_closed)'
        from apps.whatsapp.sender import WhatsAppSender
        WhatsAppSender(account=wa.account).send_text(wa_id=wa.wa_id, body=text)
        return 'auto_reply(whatsapp)'

    # Social (Messenger / Instagram / Telegram)
    social = (conversation.social_threads.select_related('account')
              .order_by('-last_message_at').first())
    if social is not None and event.channel == social.account.channel:
        if not social.window_open:
            return 'auto_reply_skipped(window_closed)'
        from apps.social.sender import send_social_text
        send_social_text(social, text)
        return f'auto_reply({social.account.channel})'

    return 'auto_reply_skipped(no_channel)'
