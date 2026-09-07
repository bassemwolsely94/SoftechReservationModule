"""
apps/campaigns/dispatcher.py

WhatsApp Campaign dispatch engine.

Converts a WhatsAppCampaign into WAConversation + WAMessageQueue items,
then drains the queue by calling WhatsAppSender.

Two-phase design:
  Phase 1 — enqueue():  resolve target audience → CampaignMessage + WAMessageQueue rows
  Phase 2 — drain():    pick pending WAMessageQueue rows → call Cloud API → update status

Usage (called from the campaign view after approval):
    from apps.campaigns.dispatcher import CampaignDispatcher
    CampaignDispatcher(campaign).enqueue()

Usage (called from APScheduler every minute):
    from apps.campaigns.dispatcher import drain_queue
    drain_queue()
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.campaigns')

# Max messages per drain() call (rate-limit WhatsApp Cloud API)
DRAIN_BATCH = 50


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CampaignDispatcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CampaignDispatcher:

    def __init__(self, campaign):
        self.campaign = campaign

    def enqueue(self) -> int:
        """
        Resolve target audience, create CampaignMessage + WAMessageQueue rows.
        Returns count of messages enqueued.
        Returns 0 and logs a warning if campaign is not in 'approved' state.
        """
        from apps.campaigns.models import WhatsAppCampaign, CampaignMessage
        from apps.whatsapp.models import WAConversation, WAMessageQueue

        if self.campaign.status not in ('approved', 'scheduled'):
            logger.warning(
                'CampaignDispatcher.enqueue: campaign %d status=%s — skipped',
                self.campaign.pk, self.campaign.status,
            )
            return 0

        customers = self._resolve_audience()
        if not customers:
            logger.info('Campaign %d: no matching customers', self.campaign.pk)
            return 0

        count = 0
        for customer in customers:
            if not customer.phone:
                continue
            try:
                message_text = self.campaign.render_message(customer)
                whatsapp_url = self.campaign.build_whatsapp_url(customer.phone, message_text)

                # CampaignMessage row (existing model)
                cm, _ = CampaignMessage.objects.get_or_create(
                    campaign=self.campaign,
                    customer=customer,
                    defaults={
                        'phone_number':  customer.phone,
                        'customer_name': customer.name,
                        'message_text':  message_text,
                        'whatsapp_url':  whatsapp_url,
                        'status':        'pending',
                    },
                )
                if cm.status not in ('pending',):
                    continue  # already sent or skipped

                # Get or create WAConversation for this phone
                from apps.whatsapp.sender import _normalise_wa_id
                wa_id = _normalise_wa_id(customer.phone)
                conversation, _ = WAConversation.objects.get_or_create(
                    wa_id=wa_id,
                    defaults={'customer': customer, 'status': 'open'},
                )

                # WAMessageQueue row — priority 3 (campaign)
                WAMessageQueue.objects.get_or_create(
                    conversation=conversation,
                    message_type='text',
                    body=message_text,
                    status='pending',
                    defaults={
                        'priority': 3,
                        'next_attempt_at': timezone.now(),
                    },
                )
                count += 1
            except Exception as exc:
                logger.warning('Campaign %d: enqueue error for customer %d: %s',
                               self.campaign.pk, customer.pk, exc)

        # Update campaign state
        self.campaign.status = 'running'
        self.campaign.messages_queued = count
        self.campaign.queued_at = timezone.now()
        self.campaign.estimated_reach = count
        self.campaign.save(update_fields=[
            'status', 'messages_queued', 'queued_at', 'estimated_reach', 'updated_at'
        ])

        logger.info('Campaign %d: %d messages enqueued', self.campaign.pk, count)
        return count

    def _resolve_audience(self):
        """
        Apply campaign.target_filter to return a Customer queryset.
        Supported filter keys:
          segment, chronic_category, last_purchase_days_max,
          last_purchase_days_min, item_id, branch_id, min_ltv
        """
        from apps.customers.models import Customer

        f = self.campaign.target_filter or {}
        qs = Customer.objects.filter(is_guest=False).exclude(phone='')

        if f.get('segment'):
            segments = f['segment'] if isinstance(f['segment'], list) else [f['segment']]
            qs = qs.filter(segment__in=segments)

        if f.get('chronic_category'):
            qs = qs.filter(health_profile__chronic_conditions__icontains=f['chronic_category'])

        now = timezone.now()
        if f.get('last_purchase_days_max'):
            cutoff = now - timedelta(days=int(f['last_purchase_days_max']))
            qs = qs.filter(purchase_history__invoice_date__gte=cutoff).distinct()

        if f.get('last_purchase_days_min'):
            cutoff = now - timedelta(days=int(f['last_purchase_days_min']))
            qs = qs.exclude(purchase_history__invoice_date__gte=cutoff).distinct()

        if f.get('item_id'):
            qs = qs.filter(
                purchase_history__lines__item_id=f['item_id']
            ).distinct()

        if f.get('branch_id'):
            qs = qs.filter(preferred_branch_id=f['branch_id'])

        if f.get('min_ltv'):
            from django.db.models import Sum
            from django.db.models.functions import Coalesce
            from decimal import Decimal
            qs = qs.annotate(
                ltv=Coalesce(Sum('purchase_history__total_amount'), Decimal('0'))
            ).filter(ltv__gte=Decimal(str(f['min_ltv'])))

        return qs.select_related('preferred_branch')[:10_000]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# drain_queue — called by APScheduler every minute
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def drain_queue():
    """
    Send up to DRAIN_BATCH pending WAMessageQueue items via WhatsApp Cloud API.
    Updates WAMessageQueue.status and linked CampaignMessage.status.
    Called by APScheduler — never raises.
    """
    from apps.whatsapp.models import WAMessageQueue, WAMessage, WAConversation
    from apps.whatsapp.sender import WhatsAppSender

    try:
        sender = WhatsAppSender()
        if not sender.is_configured:
            return  # WhatsApp not configured — skip silently

        pending = list(
            WAMessageQueue.objects
            .filter(
                status='pending',
                next_attempt_at__lte=timezone.now(),
                attempts__lt=models_F('max_attempts'),
            )
            .select_related('conversation')
            .order_by('priority', 'next_attempt_at')[:DRAIN_BATCH]
        )

        sent = failed = 0
        for item in pending:
            item.status = 'processing'
            item.save(update_fields=['status'])

            try:
                result = sender.send_text(
                    wa_id=item.conversation.wa_id,
                    body=item.body,
                )
                wamid = result.get('messages', [{}])[0].get('id', '')

                # Create WAMessage record
                msg = WAMessage.objects.create(
                    conversation=item.conversation,
                    direction='outbound',
                    message_type='text',
                    status='sent',
                    wamid=wamid,
                    body=item.body,
                    sent_at=timezone.now(),
                )
                item.status = 'sent'
                item.wa_message = msg
                item.save(update_fields=['status', 'wa_message_id'])

                # Sync CampaignMessage if one exists for this conversation
                _sync_campaign_message(item.conversation, 'sent')
                sent += 1

            except Exception as exc:
                item.attempts += 1
                item.last_error = str(exc)[:500]
                if item.attempts >= item.max_attempts:
                    item.status = 'failed'
                    _sync_campaign_message(item.conversation, 'failed', str(exc))
                else:
                    item.status = 'pending'
                    item.next_attempt_at = timezone.now() + timedelta(minutes=5 * item.attempts)
                item.save(update_fields=['status', 'attempts', 'last_error', 'next_attempt_at'])
                failed += 1
                logger.warning('WAMessageQueue drain failed for item %d: %s', item.pk, exc)

        if sent or failed:
            logger.info('WAMessageQueue drain: sent=%d failed=%d', sent, failed)

    except Exception as exc:
        logger.error('drain_queue error: %s', exc, exc_info=True)


def _sync_campaign_message(conversation, status: str, error: str = ''):
    """Update CampaignMessage status for the customer linked to this conversation."""
    try:
        from apps.campaigns.models import CampaignMessage
        if not conversation.customer_id:
            return
        cm = CampaignMessage.objects.filter(
            customer_id=conversation.customer_id,
            status='pending',
        ).first()
        if not cm:
            return
        if status == 'sent':
            cm.mark_sent()
        elif status == 'failed':
            cm.mark_failed(error)
    except Exception:
        pass


# Lazy import to avoid circular at module level
def models_F(field):
    from django.db.models import F
    return F(field)
