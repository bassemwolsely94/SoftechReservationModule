"""
apps/campaigns/views.py

WhatsApp Campaign API:
  - CRUD on campaigns (draft only editable)
  - Audience preview (estimate reach without creating messages)
  - Approval workflow: request-approval → approve / reject → queue → (run externally)
  - Message list + per-message status update (webhook simulation)
"""
import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.customers.models import Customer, PurchaseHistory
from apps.users.models import StaffProfile

from .models import WhatsAppCampaign, CampaignMessage
from .serializers import (
    WhatsAppCampaignListSerializer,
    WhatsAppCampaignDetailSerializer,
    CampaignMessageSerializer,
    AudiencePreviewSerializer,
    ApproveSerializer,
    RejectSerializer,
    QueueSerializer,
    MessageStatusSerializer,
)

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_staff(request):
    """Return StaffProfile for the authenticated user, or None."""
    try:
        return StaffProfile.objects.get(user=request.user)
    except StaffProfile.DoesNotExist:
        return None


def _build_audience_qs(target_filter: dict):
    """
    Apply target_filter dict to Customer queryset.
    Returns a queryset of matching Customer objects.

    Supported keys (all optional):
      segment                  str | list[str]  — vip/loyal/at_risk/dormant/churned/new/regular
      churn_segment            str | list[str]  — low/medium/high/critical
      min_churn_score          float            — e.g. 0.4
      max_churn_score          float            — e.g. 0.7
      chronic_category         str   — LEGACY: free-text match on chronic_conditions field
      has_condition            str   — e.g. 'diabetes','hypertension' → uses CustomerHealthProfile
      has_conditions           list[str]  — match customers with ANY of these conditions
      last_purchase_days_max   int   — bought within last N days
      last_purchase_days_min   int   — NOT bought in last N days (churn targeting)
      item_id                  int   — ever bought this item
      branch_id                int   — preferred branch
      min_ltv                  float — minimum lifetime value
      has_whatsapp             bool  — only customers with whatsapp_phone set
    """
    qs = Customer.objects.filter(is_guest=False)

    # ── RFM Segment ──────────────────────────────────────────────────────────
    segment = target_filter.get('segment')
    if segment:
        if isinstance(segment, list):
            qs = qs.filter(segment__in=segment)
        else:
            qs = qs.filter(segment=segment)

    # ── Churn segment (new) ───────────────────────────────────────────────────
    churn_segment = target_filter.get('churn_segment')
    if churn_segment:
        if isinstance(churn_segment, list):
            qs = qs.filter(churn_segment__in=churn_segment)
        else:
            qs = qs.filter(churn_segment=churn_segment)

    min_churn = target_filter.get('min_churn_score')
    if min_churn is not None:
        qs = qs.filter(churn_score__gte=float(min_churn))

    max_churn = target_filter.get('max_churn_score')
    if max_churn is not None:
        qs = qs.filter(churn_score__lte=float(max_churn))

    # ── Structured health conditions (new — uses CustomerHealthProfile) ───────
    has_condition = target_filter.get('has_condition', '').strip()
    if has_condition:
        field_name = f'health_profile__has_{has_condition}'
        try:
            qs = qs.filter(**{field_name: True})
        except Exception:
            # If field doesn't exist, fall back silently
            pass

    has_conditions = target_filter.get('has_conditions', [])
    if has_conditions and isinstance(has_conditions, list):
        condition_q = Q()
        for cond in has_conditions:
            field_name = f'health_profile__has_{cond}'
            try:
                condition_q |= Q(**{field_name: True})
            except Exception:
                pass
        if condition_q:
            qs = qs.filter(condition_q)

    # ── LEGACY: free-text chronic_conditions (kept for backward compat) ───────
    chronic_category = target_filter.get('chronic_category', '').strip()
    if chronic_category:
        qs = qs.filter(
            Q(chronic_conditions__icontains=chronic_category)
        )

    # ── WhatsApp-only filter ──────────────────────────────────────────────────
    if target_filter.get('has_whatsapp'):
        qs = qs.exclude(whatsapp_phone='')

    branch_id = target_filter.get('branch_id')
    if branch_id:
        qs = qs.filter(preferred_branch_id=branch_id)

    min_ltv = target_filter.get('min_ltv')
    if min_ltv is not None:
        qs = qs.filter(ltv__gte=min_ltv)

    last_purchase_days_max = target_filter.get('last_purchase_days_max')
    if last_purchase_days_max:
        cutoff = timezone.now() - timezone.timedelta(days=int(last_purchase_days_max))
        bought_ids = (
            PurchaseHistory.objects
            .filter(invoice_date__gte=cutoff, doc_code='115')
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = qs.filter(id__in=bought_ids)

    last_purchase_days_min = target_filter.get('last_purchase_days_min')
    if last_purchase_days_min:
        cutoff = timezone.now() - timezone.timedelta(days=int(last_purchase_days_min))
        recent_ids = (
            PurchaseHistory.objects
            .filter(invoice_date__gte=cutoff, doc_code='115')
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = qs.exclude(id__in=recent_ids)

    item_id = target_filter.get('item_id')
    if item_id:
        bought_item_ids = (
            PurchaseHistory.objects
            .filter(lines__item_id=item_id, doc_code='115')
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = qs.filter(id__in=bought_item_ids)

    return qs


def _queue_messages(campaign: WhatsAppCampaign):
    """
    Build CampaignMessage rows for each matched customer.
    Idempotent — skips if messages already exist.
    """
    if campaign.messages.exists():
        return

    # Require at least one phone number — prefer whatsapp_phone, fall back to phone
    audience = _build_audience_qs(campaign.target_filter).filter(
        Q(whatsapp_phone__isnull=False, whatsapp_phone__gt='') |
        Q(phone__isnull=False, phone__gt='')
    ).select_related('preferred_branch')

    item = campaign.featured_item

    msgs = []
    for customer in audience.iterator(chunk_size=500):
        # Use whatsapp_phone if set, otherwise fall back to primary phone
        contact_phone = customer.whatsapp_phone or customer.phone
        if not contact_phone:
            continue
        text = campaign.render_message(customer, item)
        url  = WhatsAppCampaign.build_whatsapp_url(contact_phone, text)
        msgs.append(CampaignMessage(
            campaign=campaign,
            customer=customer,
            phone_number=contact_phone,
            customer_name=customer.name or '',
            message_text=text,
            whatsapp_url=url,
            status='pending',
        ))

    CampaignMessage.objects.bulk_create(msgs, batch_size=500)
    count = len(msgs)
    campaign.messages_queued = count
    campaign.estimated_reach = count
    campaign.queued_at = timezone.now()
    campaign.save(update_fields=['messages_queued', 'estimated_reach', 'queued_at'])
    logger.info('Queued %d messages for campaign %d', count, campaign.pk)


def _enqueue_to_wa_queue(campaign: WhatsAppCampaign):
    """
    Convert pending CampaignMessage rows into WAMessageQueue items so the
    drain_queue() scheduler sends them via WhatsApp Cloud API.
    Only runs when WHATSAPP_TOKEN is configured.
    """
    from django.conf import settings
    if not getattr(settings, 'WHATSAPP_TOKEN', ''):
        return  # WhatsApp not configured — wa.me links remain the only delivery method

    from apps.whatsapp.models import WAConversation, WAMessageQueue
    from apps.whatsapp.sender import _normalise_wa_id as sender_normalise

    pending_msgs = (
        campaign.messages
        .filter(status='pending')
        .select_related('customer')
    )

    created = 0
    for cm in pending_msgs.iterator(chunk_size=500):
        try:
            raw_phone = cm.phone_number or (cm.customer.phone if cm.customer else '')
            if not raw_phone:
                continue
            wa_id = sender_normalise(raw_phone)
            conversation, _ = WAConversation.objects.get_or_create(
                wa_id=wa_id,
                defaults={
                    'customer': cm.customer,
                    'status': 'open',
                },
            )

            WAMessageQueue.objects.get_or_create(
                conversation=conversation,
                message_type='text',
                body=cm.message_text,
                status='pending',
                defaults={'priority': 3},
            )
            created += 1
        except Exception as exc:
            logger.warning('_enqueue_to_wa_queue: skip cm=%d error=%s', cm.pk, exc)

    logger.info('Campaign %d: %d messages enqueued to WAMessageQueue', campaign.pk, created)


# ── Campaign list / create ────────────────────────────────────────────────────

class CampaignListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return WhatsAppCampaignDetailSerializer
        return WhatsAppCampaignListSerializer

    def get_queryset(self):
        qs = WhatsAppCampaign.objects.select_related(
            'created_by__user', 'approved_by__user', 'featured_item',
        )
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    def perform_create(self, serializer):
        staff = _get_staff(self.request)
        serializer.save(status='draft', created_by=staff)


# ── Campaign detail / update / delete ────────────────────────────────────────

class CampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = WhatsAppCampaignDetailSerializer
    queryset = WhatsAppCampaign.objects.select_related(
        'created_by__user', 'approved_by__user', 'rejected_by__user', 'featured_item',
    )

    def update(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status not in ('draft', 'rejected'):
            return Response(
                {'detail': 'يمكن تعديل الحملة فقط في حالة المسودة أو المرفوضة.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Reset to draft if re-editing a rejected campaign
        if campaign.status == 'rejected':
            campaign.status = 'draft'
            campaign.rejected_by = None
            campaign.rejection_reason = ''
            campaign.save(update_fields=['status', 'rejected_by', 'rejection_reason'])
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status not in ('draft', 'rejected', 'cancelled'):
            return Response(
                {'detail': 'لا يمكن حذف الحملة إلا في حالة المسودة أو المرفوضة أو الملغاة.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ── Audience preview ──────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def preview_audience(request, pk):
    """
    POST /api/campaigns/{pk}/preview-audience/
    Body: { target_filter: {...} }  OR uses campaign.target_filter if body empty.
    Returns estimated reach counts + sample names.
    """
    campaign = _get_campaign_or_404(pk)
    target_filter = request.data.get('target_filter', campaign.target_filter)

    qs = _build_audience_qs(target_filter)
    total = qs.count()
    has_phone = qs.exclude(phone='').filter(phone__isnull=False).count()
    sample_names = list(
        qs.exclude(phone='').filter(phone__isnull=False)
        .values_list('name', flat=True)[:10]
    )

    # Update estimated_reach on the campaign
    campaign.estimated_reach = has_phone
    campaign.save(update_fields=['estimated_reach'])

    payload = {
        'total_customers': total,
        'has_phone': has_phone,
        'sample_names': sample_names,
        'filter_summary': target_filter,
    }
    return Response(AudiencePreviewSerializer(payload).data)


# ── Approval workflow actions ─────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_approval(request, pk):
    """Draft → pending_approval"""
    campaign = _get_campaign_or_404(pk)
    if not campaign.can_request_approval():
        return Response(
            {'detail': 'الحملة ليست في حالة مسودة أو ليس لها نص رسالة.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    campaign.status = 'pending_approval'
    campaign.save(update_fields=['status', 'updated_at'])
    return Response(WhatsAppCampaignDetailSerializer(campaign).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_campaign(request, pk):
    """pending_approval → approved"""
    campaign = _get_campaign_or_404(pk)
    if not campaign.can_approve():
        return Response(
            {'detail': 'الحملة ليست في انتظار الموافقة.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = ApproveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    staff = _get_staff(request)
    campaign.status = 'approved'
    campaign.approved_by = staff
    campaign.approved_at = timezone.now()
    campaign.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    return Response(WhatsAppCampaignDetailSerializer(campaign).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_campaign(request, pk):
    """pending_approval → rejected"""
    campaign = _get_campaign_or_404(pk)
    if not campaign.can_approve():
        return Response(
            {'detail': 'الحملة ليست في انتظار الموافقة.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = RejectSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    staff = _get_staff(request)
    campaign.status = 'rejected'
    campaign.rejected_by = staff
    campaign.rejection_reason = serializer.validated_data['reason']
    campaign.save(update_fields=['status', 'rejected_by', 'rejection_reason', 'updated_at'])
    return Response(WhatsAppCampaignDetailSerializer(campaign).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def queue_campaign(request, pk):
    """approved → scheduled (if scheduled_at given) or running (immediate)"""
    campaign = _get_campaign_or_404(pk)
    if not campaign.can_queue():
        return Response(
            {'detail': 'الحملة ليست في حالة معتمدة.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = QueueSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    scheduled_at = serializer.validated_data.get('scheduled_at')

    with transaction.atomic():
        if scheduled_at:
            campaign.status = 'scheduled'
            campaign.scheduled_at = scheduled_at
        else:
            campaign.status = 'running'

        campaign.save(update_fields=['status', 'scheduled_at', 'updated_at'])
        _queue_messages(campaign)

    # Non-blocking — enqueue to WAMessageQueue for Cloud API send
    try:
        _enqueue_to_wa_queue(campaign)
    except Exception as exc:
        logger.warning('queue_campaign: WAMessageQueue enqueue failed (wa.me fallback active): %s', exc)

    return Response(WhatsAppCampaignDetailSerializer(campaign).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_campaign(request, pk):
    """Any cancellable status → cancelled"""
    campaign = _get_campaign_or_404(pk)
    if not campaign.can_cancel():
        return Response(
            {'detail': 'لا يمكن إلغاء الحملة في حالتها الحالية.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    campaign.status = 'cancelled'
    campaign.save(update_fields=['status', 'updated_at'])
    return Response(WhatsAppCampaignDetailSerializer(campaign).data)


# ── Messages ──────────────────────────────────────────────────────────────────

class CampaignMessageListView(generics.ListAPIView):
    """GET /api/campaigns/{pk}/messages/"""
    permission_classes = [IsAuthenticated]
    serializer_class   = CampaignMessageSerializer

    def get_queryset(self):
        qs = CampaignMessage.objects.filter(campaign_id=self.kwargs['pk'])
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_message_status(request, pk, msg_pk):
    """PATCH /api/campaigns/{pk}/messages/{msg_pk}/status/ — simulate delivery webhook"""
    try:
        msg = CampaignMessage.objects.select_related('campaign').get(
            pk=msg_pk, campaign_id=pk
        )
    except CampaignMessage.DoesNotExist:
        return Response({'detail': 'الرسالة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = MessageStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    new_status = serializer.validated_data['status']

    if new_status == 'sent':
        msg.mark_sent()
    elif new_status == 'delivered':
        msg.mark_delivered()
    elif new_status == 'failed':
        msg.mark_failed(serializer.validated_data.get('error_message', ''))
    else:
        msg.status = new_status
        msg.save(update_fields=['status'])

    # Update campaign counters
    _refresh_campaign_counters(msg.campaign)
    return Response(CampaignMessageSerializer(msg).data)


# ── Stats ─────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def campaign_stats(request, pk):
    """GET /api/campaigns/{pk}/stats/ — quick delivery summary"""
    campaign = _get_campaign_or_404(pk)
    msgs = campaign.messages.values('status')
    counts = {}
    for row in msgs:
        counts[row['status']] = counts.get(row['status'], 0) + 1

    total = sum(counts.values())
    return Response({
        'total':     total,
        'pending':   counts.get('pending',   0),
        'sent':      counts.get('sent',      0),
        'delivered': counts.get('delivered', 0),
        'failed':    counts.get('failed',    0),
        'opted_out': counts.get('opted_out', 0),
        'skipped':   counts.get('skipped',   0),
        'delivery_rate': campaign.delivery_rate,
    })


# ── Utilities ─────────────────────────────────────────────────────────────────

def _get_campaign_or_404(pk):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        WhatsAppCampaign.objects.select_related(
            'created_by__user', 'approved_by__user', 'rejected_by__user', 'featured_item',
        ),
        pk=pk,
    )


def _refresh_campaign_counters(campaign: WhatsAppCampaign):
    from django.db.models import Count
    agg = campaign.messages.aggregate(
        sent=Count('id', filter=Q(status='sent')),
        delivered=Count('id', filter=Q(status='delivered')),
        failed=Count('id', filter=Q(status='failed')),
        queued=Count('id', filter=Q(status='pending')),
    )
    campaign.messages_sent      = agg['sent']      or 0
    campaign.messages_delivered = agg['delivered'] or 0
    campaign.messages_failed    = agg['failed']    or 0
    campaign.messages_queued    = agg['queued']    or 0
    campaign.save(update_fields=[
        'messages_sent', 'messages_delivered', 'messages_failed', 'messages_queued',
    ])
