"""
apps/social/views.py
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView

from apps.social.webhooks import (
    process_meta_webhook, process_telegram_update, resolve_telegram_account,
)

logger = logging.getLogger('elrezeiky.social')


@method_decorator(csrf_exempt, name='dispatch')
class MetaGraphWebhookView(APIView):
    """
    ONE webhook for Messenger + Instagram (doc 15 Phase 3).
    GET  — Meta hub challenge (META_GRAPH_VERIFY_TOKEN)
    POST — signature-verified event processing (META_GRAPH_APP_SECRET)
    """
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        mode      = request.GET.get('hub.mode')
        token     = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        verify_token = getattr(settings, 'META_GRAPH_VERIFY_TOKEN', '')
        if mode == 'subscribe' and token == verify_token:
            return HttpResponse(challenge, content_type='text/plain')
        return HttpResponse('Forbidden', status=403)

    def post(self, request):
        app_secret = getattr(settings, 'META_GRAPH_APP_SECRET', '')
        if app_secret:
            sig = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
            expected = hmac.new(app_secret.encode(), request.body, hashlib.sha256).hexdigest()
            if not (sig.startswith('sha256=') and
                    hmac.compare_digest(sig[7:], expected)):
                logger.warning('Meta Graph webhook: invalid signature')
                return HttpResponse('Forbidden', status=403)
        else:
            logger.warning('META_GRAPH_APP_SECRET not set — skipping signature verification')

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse('Bad Request', status=400)

        process_meta_webhook(payload)
        return HttpResponse('EVENT_RECEIVED', status=200)


@method_decorator(csrf_exempt, name='dispatch')
class TelegramWebhookView(APIView):
    """
    POST — Telegram bot updates. The bot/account is identified by the
    X-Telegram-Bot-Api-Secret-Token header (set when registering the webhook
    via setWebhook secret_token=...), matched against the account's stored
    webhook_secret credential.
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        secret = request.META.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN', '')
        account = resolve_telegram_account(secret)
        if account is None:
            logger.warning('Telegram webhook: unknown or missing secret token')
            return HttpResponse('Forbidden', status=403)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse('Bad Request', status=400)

        process_telegram_update(payload, account)
        return HttpResponse('OK', status=200)


@method_decorator(csrf_exempt, name='dispatch')
class TikTokWebhookView(APIView):
    """Placeholder — TikTok Business DM API access pending approval (doc 15)."""
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        logger.info('TikTok webhook hit — API access not yet approved; payload ignored')
        return HttpResponse('Not Implemented', status=501)
