"""
apps/notifications/consumers.py

Two async WebSocket consumers:

NotificationConsumer  — personal notification stream for one user
    URL:   /ws/notifications/?token=<jwt>
    Group: notifications_user_{profile_id}
    Receives: new_notification events pushed by Notification.push_realtime()

ChatterConsumer       — live chatter thread for a specific record
    URL:   /ws/chatter/{model_name}/{record_id}/?token=<jwt>
    Group: chatter_{model_name}_{record_id}
    Receives: new_chatter events pushed by ChatterMessage._push_chatter_realtime()
"""
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger('elrezeiky.notifications')


class NotificationConsumer(AsyncWebsocketConsumer):
    """Personal real-time notification channel for one authenticated user."""

    async def connect(self):
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        profile = await self._get_profile(user)
        if not profile:
            await self.close(code=4001)
            return

        self.profile_id = profile.id
        self.group_name = f'notifications_user_{self.profile_id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Deliver any pending (unread) notifications accumulated while offline
        await self._send_pending()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """
        Client can send:
          {"action": "ping"}                       → pong
          {"action": "mark_read", "id": 123}       → mark one notification read
          {"action": "mark_all_read"}              → mark all read
        """
        try:
            data   = json.loads(text_data)
            action = data.get('action')
        except (json.JSONDecodeError, AttributeError):
            return

        if action == 'ping':
            await self.send(text_data=json.dumps({'event': 'pong'}))

        elif action == 'mark_read':
            notif_id = data.get('id')
            if notif_id:
                count = await self._mark_read(notif_id)
                await self.send(text_data=json.dumps({
                    'event': 'marked_read', 'id': notif_id, 'updated': count
                }))

        elif action == 'mark_all_read':
            count = await self._mark_all_read()
            await self.send(text_data=json.dumps({
                'event': 'all_marked_read', 'count': count
            }))

    # ── Channel layer event handlers ──────────────────────────────────────────

    async def notification_message(self, event):
        """Forward a pushed notification payload to the WebSocket client."""
        await self.send(text_data=json.dumps(event['data']))

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_profile(self, user):
        from apps.users.models import StaffProfile
        try:
            return StaffProfile.objects.get(user=user)
        except StaffProfile.DoesNotExist:
            return None

    async def _send_pending(self):
        """
        Push up to 50 unread notifications accumulated while offline.

        Batched into ONE WebSocket frame:
          {"event": "pending_notifications", "notifications": [...]}

        This avoids up to 50 separate send() calls on reconnect — a single
        JSON payload is far more efficient for both the server and the client.

        IMPORTANT: stays on Daphne's event loop throughout; DB work is
        delegated to _get_pending_notifications() which runs in the thread pool.
        """
        pending = await self._get_pending_notifications()
        if not pending:
            return
        await self.send(text_data=json.dumps(
            {'event': 'pending_notifications', 'notifications': pending},
            default=str,
        ))

    @database_sync_to_async
    def _get_pending_notifications(self):
        """Return serialized unread notifications as plain dicts (thread-safe)."""
        from apps.notifications.models import Notification
        from apps.notifications.serializers import NotificationSerializer

        qs = (
            Notification.objects
            .select_related('recipient', 'recipient__user')
            .filter(recipient_id=self.profile_id, is_read=False)
            .order_by('created_at')[:50]
        )
        # Evaluate queryset inside this sync thread, then serialise
        return [dict(NotificationSerializer(n).data) for n in qs]

    @database_sync_to_async
    def _mark_read(self, notif_id: int) -> int:
        from django.utils import timezone
        from apps.notifications.models import Notification, NotificationLog
        updated = Notification.objects.filter(
            pk=notif_id, recipient_id=self.profile_id
        ).update(is_read=True)
        if updated:
            NotificationLog.objects.filter(
                notification_id=notif_id, recipient_id=self.profile_id, read_at__isnull=True
            ).update(read_at=timezone.now())
        return updated

    @database_sync_to_async
    def _mark_all_read(self) -> int:
        from django.utils import timezone
        from apps.notifications.models import Notification, NotificationLog
        count = Notification.objects.filter(
            recipient_id=self.profile_id, is_read=False
        ).update(is_read=True)
        NotificationLog.objects.filter(
            recipient_id=self.profile_id, read_at__isnull=True
        ).update(read_at=timezone.now())
        return count


class ChatterConsumer(AsyncWebsocketConsumer):
    """
    Live chatter thread for a specific record.
    URL: /ws/chatter/{model_name}/{record_id}/?token=<jwt>
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        self.model_name = self.scope['url_route']['kwargs']['model_name']
        self.record_id  = self.scope['url_route']['kwargs']['record_id']
        self.group_name = f'chatter_{self.model_name}_{self.record_id}'

        # Cache the StaffProfile on connect so _create_message doesn't hit the
        # DB on every posted message (one query per connection, not per message)
        self._profile = await self._get_profile(user)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    @database_sync_to_async
    def _get_profile(self, user):
        from apps.users.models import StaffProfile
        try:
            return StaffProfile.objects.get(user=user)
        except StaffProfile.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """
        Client can send:
          {"action": "ping"}
          {"action": "post", "message": "..."}  → create ChatterMessage
        """
        try:
            data   = json.loads(text_data)
            action = data.get('action')
        except (json.JSONDecodeError, AttributeError):
            return

        if action == 'ping':
            await self.send(text_data=json.dumps({'event': 'pong'}))

        elif action == 'post':
            message = (data.get('message') or '').strip()
            if message:
                await self._create_message(message)

    async def chatter_message(self, event):
        """Forward a chatter push to connected clients."""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def _create_message(self, message: str):
        from apps.notifications.models import ChatterMessage
        # Use the profile cached on connect — no extra DB query per message
        if not self._profile:
            logger.warning('ChatterConsumer.create_message: no profile cached, skipping')
            return
        try:
            ChatterMessage.objects.create(
                model_name=self.model_name,
                record_id=int(self.record_id),
                author=self._profile,
                message=message,
            )
        except Exception as exc:
            logger.warning('ChatterConsumer.create_message failed: %s', exc)
