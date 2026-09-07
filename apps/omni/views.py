"""
apps/omni/views.py

Unified inbox API. Composes the channel apps — reply routing dispatches
to the native channel sender (WhatsApp only in Phase 0; voice is
click-to-call via the existing /api/pbx/ endpoints).
"""
import logging

from django.db.models import Q
from rest_framework import generics, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.omni.models import (
    AutomationRule, AutomationRun, ChannelAccount, Conversation, TimelineEvent,
)
from apps.omni.serializers import (
    AutomationRuleSerializer, AutomationRunSerializer,
    ChannelAccountSerializer, ConversationSerializer,
    TimelineEventSerializer, ReplySerializer,
)

logger = logging.getLogger('elrezeiky.omni')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Conversations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            Conversation.objects
            .select_related('customer', 'assigned_to', 'branch')
            .prefetch_related('wa_threads')
        )
        p = self.request.query_params

        status_filter = p.get('status')
        if status_filter == 'active':
            qs = qs.filter(status__in=Conversation.ACTIVE_STATUSES)
        elif status_filter:
            qs = qs.filter(status=status_filter)

        channel = p.get('channel')
        if channel:
            qs = qs.filter(created_from_channel=channel)

        if p.get('assigned_to_me'):
            profile = getattr(self.request.user, 'staff_profile', None)
            if profile is not None:
                qs = qs.filter(assigned_to=profile)

        customer_id = p.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        q = p.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(contact_phone__icontains=q) |
                Q(customer__name__icontains=q) |
                Q(customer__phone__icontains=q) |
                Q(subject__icontains=q)
            )
        return qs.order_by('-last_activity_at')


class ConversationDetailView(generics.RetrieveUpdateAPIView):
    """PATCH: status / priority / assigned_to / subject / branch."""
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]
    queryset = (
        Conversation.objects
        .select_related('customer', 'assigned_to', 'branch')
        .prefetch_related('wa_threads')
    )

    def perform_update(self, serializer):
        old = {f: getattr(serializer.instance, f) for f in ('status', 'assigned_to_id')}
        convo = serializer.save()

        # Audit assignment / status transitions into the timeline itself
        from apps.omni import services
        actor = getattr(self.request.user, 'staff_profile', None)
        if convo.assigned_to_id != old['assigned_to_id'] and convo.assigned_to:
            services.add_event(
                convo, 'assignment', actor=actor,
                summary=f'أُسندت إلى {convo.assigned_to.full_name}',
            )
        if convo.status != old['status']:
            services.add_event(
                convo, 'status_change', actor=actor,
                summary=f'الحالة: {convo.get_status_display()}',
            )


class TimelineListView(generics.ListAPIView):
    serializer_class = TimelineEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            TimelineEvent.objects
            .filter(conversation_id=self.kwargs['conversation_id'])
            .select_related('actor', 'content_type')
            .order_by('occurred_at')
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Reply — routes to the native channel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        try:
            convo = Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist:
            return Response({'detail': 'المحادثة غير موجودة'}, status=404)

        ser = ReplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data['body']
        profile = getattr(request.user, 'staff_profile', None)

        # Route to the most recently active writable thread across channels
        wa_thread = convo.wa_threads.order_by('-last_message_at').first()
        social_thread = (
            convo.social_threads.select_related('account')
            .order_by('-last_message_at').first()
        )

        def _ts(t):
            return t.last_message_at or t.created_at

        candidates = [t for t in (wa_thread, social_thread) if t is not None]
        if not candidates:
            return Response(
                {'detail': 'لا توجد قناة رسائل مرتبطة بهذه المحادثة — استخدم الاتصال الهاتفي'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        thread = max(candidates, key=_ts)

        try:
            if thread is wa_thread:
                if not thread.window_open:
                    return Response(
                        {'detail': 'نافذة الـ 24 ساعة مغلقة — استخدم قالباً معتمداً من صندوق واتساب'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                from apps.whatsapp.sender import WhatsAppSender
                # Reply from the same company number the customer wrote to;
                # the created WAMessage flows into the timeline via signal.
                result = WhatsAppSender(account=thread.account).send_text(
                    wa_id=thread.wa_id, body=body,
                )
                return Response({'wamid': result.get('messages', [{}])[0].get('id', '')})

            # Social thread (Messenger / Instagram / Telegram)
            if not thread.window_open:
                return Response(
                    {'detail': 'نافذة الـ 24 ساعة مغلقة لهذه القناة (سياسة Meta)'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            from apps.social.sender import send_social_text
            msg = send_social_text(thread, body, sent_by=profile)
            return Response({'message_id': msg.pk, 'channel': thread.account.channel})
        except Exception as exc:
            logger.error('omni ReplyView error: %s', exc)
            return Response({'detail': str(exc)}, status=500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Channel accounts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AccountListView(generics.ListCreateAPIView):
    serializer_class = ChannelAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ChannelAccount.objects.select_related('branch', 'supervisor')
        channel = self.request.query_params.get('channel')
        if channel:
            qs = qs.filter(channel=channel)
        return qs


class AccountDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ChannelAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset = ChannelAccount.objects.select_related('branch', 'supervisor')


class TranscribeEventView(APIView):
    """
    POST /api/omni/events/{id}/transcribe/ — start async transcription of a
    call recording or WhatsApp voice note. Result lands in the timeline as an
    'ai_insight' event (picked up by inbox polling).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            event = TimelineEvent.objects.select_related('content_type').get(pk=pk)
        except TimelineEvent.DoesNotExist:
            return Response({'detail': 'الحدث غير موجود'}, status=404)

        model = (f'{event.content_type.app_label}.{event.content_type.model}'
                 if event.content_type_id else '')
        from threading import Thread
        from apps.omni import transcription

        if model == 'callcenter.calllog':
            Thread(target=transcription.transcribe_call_log,
                   args=(event.object_id,), daemon=True).start()
        elif model == 'whatsapp.wamessage':
            Thread(target=transcription.transcribe_wa_voice,
                   args=(event.object_id,), daemon=True).start()
        else:
            return Response(
                {'detail': 'هذا الحدث لا يحتوي على صوت قابل للتفريغ'}, status=400)

        return Response({'detail': 'بدأ التفريغ — سيظهر في المحادثة خلال لحظات'},
                        status=status.HTTP_202_ACCEPTED)


class WallboardView(APIView):
    """
    GET /api/omni/wallboard/ — supervisor live aggregate (doc 15 Phase 2):
    live calls, per-queue stats today, agent states, WhatsApp account load,
    unified-conversation backlog. Polled by /omni/wallboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, 'staff_profile', None)
        if not (profile and profile.is_active and
                profile.role in ('admin', 'supervisor', 'quality_manager')):
            return Response({'detail': 'صلاحية المشرفين فقط'}, status=403)

        from django.db.models import Avg, Count, Q
        from django.utils import timezone as tz
        from apps.pbx.models import AgentExtension, CallSession

        now = tz.now()
        today = tz.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        live_states = ['ringing', 'queued', 'answered', 'on_hold', 'transferred']

        # ── Live calls ────────────────────────────────────────────────────
        live = (
            CallSession.objects.filter(state__in=live_states)
            .select_related('agent__staff', 'customer', 'queue')
            .order_by('started_at')[:100]
        )
        live_calls = [{
            'id': s.pk,
            'caller': s.caller_number,
            'customer_name': s.customer.name if s.customer_id else None,
            'state': s.state,
            'direction': s.direction,
            'queue': s.queue.name if s.queue_id else '',
            'agent_ext': s.agent.extension if s.agent_id else '',
            'agent_name': (s.agent.staff.full_name
                           if s.agent_id and s.agent.staff_id else ''),
            'started_at': s.started_at,
            'seconds': int((now - s.started_at).total_seconds()),
        } for s in live]

        # ── Today per queue ───────────────────────────────────────────────
        queues = list(
            CallSession.objects.filter(started_at__gte=today, queue__isnull=False)
            .values('queue__name')
            .annotate(
                total=Count('id'),
                answered=Count('id', filter=Q(answered_at__isnull=False)),
                abandoned=Count('id', filter=Q(state='abandoned')),
                avg_wait=Avg('wait_seconds'),
                avg_talk=Avg('talk_seconds', filter=Q(talk_seconds__gt=0)),
            )
            .order_by('queue__name')
        )

        # ── Today totals ──────────────────────────────────────────────────
        today_calls = CallSession.objects.filter(started_at__gte=today)
        totals = today_calls.aggregate(
            total=Count('id'),
            answered=Count('id', filter=Q(answered_at__isnull=False)),
            abandoned=Count('id', filter=Q(state='abandoned')),
            missed=Count('id', filter=Q(state__in=['no_answer', 'busy', 'failed'])),
            avg_wait=Avg('wait_seconds'),
        )

        # ── Agents ────────────────────────────────────────────────────────
        busy_agent_ids = {
            s.agent_id for s in live if s.agent_id is not None
        } if live_calls else set()
        agents = [{
            'extension': a.extension,
            'name': a.staff.full_name if a.staff_id else '(غير مُعيَّن)',
            'registered': a.is_registered,
            'on_call': a.pk in busy_agent_ids,
        } for a in AgentExtension.objects.filter(
            extension_type='agent', is_active=True,
        ).select_related('staff').order_by('extension')]

        # ── WhatsApp accounts + conversation backlog ──────────────────────
        wa_accounts = ChannelAccount.objects.filter(channel='whatsapp', is_active=True)
        from django.db.models import Sum
        from apps.whatsapp.models import WAConversation
        conversations = {
            'active': Conversation.objects.filter(
                status__in=Conversation.ACTIVE_STATUSES).count(),
            'unassigned': Conversation.objects.filter(
                status__in=Conversation.ACTIVE_STATUSES,
                assigned_to__isnull=True).count(),
            'wa_unread': WAConversation.objects.aggregate(
                t=Sum('unread_count'))['t'] or 0,
        }

        return Response({
            'generated_at': now,
            'live_calls': live_calls,
            'queues': queues,
            'today': totals,
            'agents': agents,
            'accounts': {
                'total': wa_accounts.count(),
                'connected': wa_accounts.filter(status='connected').count(),
            },
            'conversations': conversations,
        })


class AIAssistView(APIView):
    """
    POST /api/omni/conversations/{id}/ai-assist/ — Gemini reads the recent
    timeline and returns a summary, suggested replies, intent, and urgency.
    Assists the pharmacist; never sends anything itself (doc 15 AI principle).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            convo = Conversation.objects.select_related('customer').get(pk=pk)
        except Conversation.DoesNotExist:
            return Response({'detail': 'المحادثة غير موجودة'}, status=404)

        events = list(
            convo.events.exclude(event_type__in=['assignment', 'status_change'])
            .order_by('-occurred_at')[:25]
        )
        events.reverse()
        if not events:
            return Response({'detail': 'لا توجد أحداث لتحليلها'}, status=400)

        from apps.omni.ai import assist_conversation
        result = assist_conversation(convo, events)
        if result is None:
            return Response(
                {'detail': 'تعذّر توليد الاقتراحات — تحقق من إعداد GOOGLE_API_KEY'},
                status=503)
        return Response(result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Automation rules (admin/supervisor manage; engine runs in services)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        p = getattr(request.user, 'staff_profile', None)
        return bool(p and p.is_active and p.role in ('admin', 'supervisor'))


class AutomationListView(generics.ListCreateAPIView):
    serializer_class = AutomationRuleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]
    queryset = AutomationRule.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=getattr(self.request.user, 'staff_profile', None))


class AutomationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AutomationRuleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]
    queryset = AutomationRule.objects.all()


class AutomationRunsView(generics.ListAPIView):
    serializer_class = AutomationRunSerializer
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def get_queryset(self):
        qs = AutomationRun.objects.select_related('rule').order_by('-created_at')
        rule_id = self.request.query_params.get('rule')
        if rule_id:
            qs = qs.filter(rule_id=rule_id)
        return qs[:200]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cross-channel analytics (doc 15 Phase 5)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, 'staff_profile', None)
        if not (profile and profile.is_active and
                profile.role in ('admin', 'supervisor', 'quality_manager')):
            return Response({'detail': 'صلاحية المشرفين فقط'}, status=403)

        from datetime import timedelta
        from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
        from django.db.models.functions import TruncDate
        from django.utils import timezone as tz

        try:
            days = max(1, min(90, int(request.query_params.get('days', 30))))
        except ValueError:
            days = 30
        since = tz.now() - timedelta(days=days)

        events = TimelineEvent.objects.filter(occurred_at__gte=since)
        convos = Conversation.objects.filter(created_at__gte=since)

        # Volume by channel
        by_channel = list(
            events.filter(event_type__in=['message_in', 'message_out', 'call', 'call_missed'])
            .exclude(channel='')
            .values('channel')
            .annotate(
                total=Count('id'),
                inbound=Count('id', filter=Q(event_type__in=['message_in', 'call'])),
            )
            .order_by('-total')
        )

        # Volume by day (inbound messages + calls)
        by_day = list(
            events.filter(event_type__in=['message_in', 'call', 'call_missed'])
            .annotate(day=TruncDate('occurred_at'))
            .values('day')
            .annotate(total=Count('id'))
            .order_by('day')
        )

        # First-response time: avg(first message_out − first_inbound_at)
        from django.db.models import Min
        frt = (
            convos.filter(first_inbound_at__isnull=False,
                          events__event_type='message_out')
            .annotate(first_out=Min('events__occurred_at',
                                    filter=Q(events__event_type='message_out')))
            .annotate(frt=ExpressionWrapper(
                F('first_out') - F('first_inbound_at'), output_field=DurationField()))
            .aggregate(avg=Avg('frt'))
        )
        frt_seconds = frt['avg'].total_seconds() if frt['avg'] else None

        # Conversation → reservation conversion
        total_convos = convos.count()
        converted = convos.filter(events__event_type='erp_reservation').distinct().count()

        # Resolution + status split
        status_split = list(
            convos.values('status').annotate(n=Count('id')).order_by('-n')
        )

        # Per-agent activity (outbound messages sent)
        by_agent = list(
            events.filter(event_type='message_out', actor__isnull=False)
            .values('actor', 'actor__user__first_name', 'actor__user__last_name')
            .annotate(replies=Count('id'))
            .order_by('-replies')[:15]
        )
        for a in by_agent:
            a['agent_name'] = (
                f"{a.pop('actor__user__first_name', '') or ''} "
                f"{a.pop('actor__user__last_name', '') or ''}".strip()
                or f"#{a['actor']}"
            )

        return Response({
            'days': days,
            'by_channel': by_channel,
            'by_day': by_day,
            'first_response_seconds': frt_seconds,
            'conversion': {
                'conversations': total_convos,
                'to_reservation': converted,
                'rate': round(converted / total_convos, 3) if total_convos else 0,
            },
            'status_split': status_split,
            'by_agent': by_agent,
        })


class AccountHealthView(APIView):
    """
    GET /api/omni/accounts/{id}/health/ — live provider probe + local status.
    Meta Cloud: pings the Graph API phone-number object (quality rating etc.)
    and updates the stored status/heartbeat accordingly. Never raises.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            account = ChannelAccount.objects.get(pk=pk)
        except ChannelAccount.DoesNotExist:
            return Response({'detail': 'الحساب غير موجود'}, status=404)

        from apps.omni.providers import get_provider
        try:
            probe = get_provider(account).health()
        except Exception as exc:
            probe = {'ok': False, 'detail': str(exc)}

        if probe.get('ok'):
            account.touch_heartbeat('connected')
        elif account.status == 'connected':
            account.touch_heartbeat('degraded')

        return Response({
            'id': account.pk,
            'status': account.status,
            'last_heartbeat_at': account.last_heartbeat_at,
            'provider': account.provider,
            'probe': probe,
        })
