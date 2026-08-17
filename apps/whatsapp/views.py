"""
apps/whatsapp/views.py
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.whatsapp.models import WAConversation, WAMessage, WATemplate
from apps.whatsapp.serializers import (
    WAConversationSerializer, WAMessageSerializer,
    WATemplateSerializer, SendTextSerializer, SendTemplateSerializer,
)
from apps.whatsapp.webhook import process_webhook
from apps.whatsapp.sender import WhatsAppSender

logger = logging.getLogger('elrezeiky.whatsapp')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Webhook endpoint (public — no JWT, verified by Hub-Signature)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(APIView):
    """
    GET  — Meta webhook verification challenge
    POST — incoming event processing (signature verified)
    """
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        """Meta hub challenge verification."""
        mode      = request.GET.get('hub.mode')
        token     = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        verify_token = getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '')

        if mode == 'subscribe' and token == verify_token:
            return HttpResponse(challenge, content_type='text/plain')
        return HttpResponse('Forbidden', status=403)

    def post(self, request):
        """Process incoming Meta webhook event."""
        # Verify signature
        if not self._verify_signature(request):
            logger.warning('WhatsApp webhook: invalid signature')
            return HttpResponse('Forbidden', status=403)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse('Bad Request', status=400)

        process_webhook(payload)
        return HttpResponse('EVENT_RECEIVED', status=200)

    def _verify_signature(self, request) -> bool:
        app_secret = getattr(settings, 'WHATSAPP_APP_SECRET', '')
        if not app_secret:
            logger.warning('WHATSAPP_APP_SECRET not set — skipping signature verification')
            return True

        sig_header = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
        if not sig_header.startswith('sha256='):
            return False

        expected = hmac.new(
            app_secret.encode(), request.body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig_header[7:], expected)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Conversation list / detail
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConversationListView(generics.ListAPIView):
    serializer_class   = WAConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Q
        qs = WAConversation.objects.select_related('customer', 'assigned_to__user')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        assigned = self.request.query_params.get('assigned_to_me')
        if assigned:
            profile = getattr(self.request.user, 'staff_profile', None)
            if profile is not None:
                qs = qs.filter(assigned_to=profile)
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(wa_id__icontains=q) |
                Q(customer__name__icontains=q) |
                Q(customer__phone__icontains=q)
            )
        return qs.order_by('-last_message_at')


class ConversationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = WAConversationSerializer
    permission_classes = [IsAuthenticated]
    queryset           = WAConversation.objects.select_related('customer', 'assigned_to')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Messages in a conversation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MessageListView(generics.ListAPIView):
    serializer_class   = WAMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            WAMessage.objects
            .filter(conversation_id=self.kwargs['conversation_id'])
            .order_by('created_at')
            .select_related('media', 'template', 'sent_by')
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Send message
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SendTextView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        try:
            convo = WAConversation.objects.get(pk=conversation_id)
        except WAConversation.DoesNotExist:
            return Response({'detail': 'المحادثة غير موجودة'}, status=404)

        ser = SendTextSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        if not convo.window_open:
            return Response(
                {'detail': 'نافذة المحادثة منتهية — استخدم قالباً معتمداً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            sender = WhatsAppSender()
            result = sender.send_text(
                wa_id=convo.wa_id,
                body=ser.validated_data['body'],
            )
            return Response({'wamid': result.get('messages', [{}])[0].get('id', '')})
        except Exception as exc:
            logger.error('SendTextView error: %s', exc)
            return Response({'detail': str(exc)}, status=500)


class SendTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        try:
            convo = WAConversation.objects.get(pk=conversation_id)
        except WAConversation.DoesNotExist:
            return Response({'detail': 'المحادثة غير موجودة'}, status=404)

        ser = SendTemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            sender = WhatsAppSender()
            result = sender.send_template(
                wa_id=convo.wa_id,
                template_name=ser.validated_data['template_name'],
                language=ser.validated_data.get('language', 'ar'),
                variables=ser.validated_data.get('variables', []),
            )
            return Response({'wamid': result.get('messages', [{}])[0].get('id', '')})
        except Exception as exc:
            logger.error('SendTemplateView error: %s', exc)
            return Response({'detail': str(exc)}, status=500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Templates
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TemplateListView(generics.ListAPIView):
    serializer_class   = WATemplateSerializer
    permission_classes = [IsAuthenticated]
    queryset           = WATemplate.objects.filter(status='approved').order_by('name')
