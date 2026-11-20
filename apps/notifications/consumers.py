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
import asyncio
import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from apps.access.ws import ZoneGuardMixin

logger = logging.getLogger('elrezeiky.notifications')

# A burst of changes (a job sending 50 notifications) becomes one counts frame per open tab.
COUNTS_DEBOUNCE_SECONDS = 0.5


class NotificationConsumer(ZoneGuardMixin, AsyncWebsocketConsumer):
    """Personal real-time notification channel for one authenticated user."""
    socket_kind = 'notifications'

    async def connect(self):
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return
        if not await self.zone_admit():          # N5: account, device, expiry, zone
            return

        profile = await self._get_profile(user)
        if not profile:
            await self.close(code=4001)
            return

        self.profile_id = profile.id
        self.group_name = f'notifications_user_{self.profile_id}'
        self._counts_task = None

        from .live import LIVE_STAFF_GROUP
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # perf Stage 5: every staff socket hears "freshness changed" (domain keys + time only)
        await self.channel_layer.group_add(LIVE_STAFF_GROUP, self.channel_name)
        await self.accept()
        await self.zone_start()

        # Deliver any pending (unread) notifications accumulated while offline
        await self._send_pending()

    async def disconnect(self, close_code):
        await self.zone_stop()
        task = getattr(self, '_counts_task', None)
        if task and not task.done():
            task.cancel()
        if hasattr(self, 'group_name'):
            from .live import LIVE_STAFF_GROUP
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.channel_layer.group_discard(LIVE_STAFF_GROUP, self.channel_name)

    async def receive(self, text_data):
        """
        Client can send:
          {"action": "ping"}                       → pong
          {"action": "mark_read", "id": 123}       → mark one notification read
          {"action": "mark_all_read", "view": "action"|"all"} → mark the bell read (same scope as
                                                                REST mark-all-read, C26)
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
                if count:
                    await self._counts_to_all_tabs()

        elif action == 'mark_all_read':
            count = await self._mark_all_read(data.get('view'))
            await self.send(text_data=json.dumps({
                'event': 'all_marked_read', 'count': count
            }))
            if count:
                await self._counts_to_all_tabs()

    # ── Channel layer event handlers ──────────────────────────────────────────

    async def notification_message(self, event):
        """Forward a pushed notification payload to the WebSocket client."""
        await self.send(text_data=json.dumps(event['data']))

    async def notification_counts(self, event):
        """The user's unread counts changed (live.request_counts_push). Debounced: one counts frame
        per burst, computed here so only users with an open tab pay for it."""
        task = getattr(self, '_counts_task', None)
        if task and not task.done():
            return
        self._counts_task = asyncio.ensure_future(self._debounced_counts())

    async def _debounced_counts(self):
        try:
            await asyncio.sleep(COUNTS_DEBOUNCE_SECONDS)
            await self._send_counts()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug('counts push skipped for profile %s: %s', getattr(self, 'profile_id', None), exc)

    async def live_freshness(self, event):
        """A sync run / lane finished (live.broadcast_freshness): domain keys + time, nothing else."""
        from .live import freshness_message
        await self.send(text_data=json.dumps(freshness_message(event)))

    async def _send_counts(self):
        counts = await self._category_counts()
        if counts is not None:
            await self.send(text_data=json.dumps({'event': 'category_counts', **counts}))

    async def _counts_to_all_tabs(self):
        """After a read on this socket, refresh the counts on every tab of this user."""
        try:
            await self.channel_layer.group_send(self.group_name, {'type': 'notification.counts'})
        except Exception as exc:
            logger.debug('counts fan-out skipped: %s', exc)

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_profile(self, user):
        from apps.users.models import StaffProfile
        try:
            return StaffProfile.objects.get(user=user)
        except StaffProfile.DoesNotExist:
            return None

    @database_sync_to_async
    def _category_counts(self):
        from apps.users.models import StaffProfile
        from .views import unread_category_counts
        profile = StaffProfile.objects.filter(pk=self.profile_id).first()
        return unread_category_counts(profile) if profile else None

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
    def _mark_all_read(self, view=None) -> int:
        """The bell's «قراءة الكل» over the socket — the SAME scope as the REST route (C26). It used to
        mark every category (quiet feeds and snoozed rows included) and stamp every log row."""
        from apps.users.models import StaffProfile
        from .action_items import clean_view
        from .views import mark_bell_read
        profile = StaffProfile.objects.filter(pk=self.profile_id).first()
        if not profile:
            return 0
        return mark_bell_read(profile, view=clean_view(view))


class ChatterConsumer(ZoneGuardMixin, AsyncWebsocketConsumer):
    """
    Live chatter thread for a specific record.
    URL: /ws/chatter/{model_name}/{record_id}/?token=<jwt>
    """
    socket_kind = 'chatter'

    async def connect(self):
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return
        if not await self.zone_admit():          # N5, before the record checks (F2)
            return

        self.model_name = self.scope['url_route']['kwargs']['model_name']
        self.record_id  = self.scope['url_route']['kwargs']['record_id']
        # the REST rules: chattable models only, the record's branch for branch users (Batch 6,
        # W-3 — any logged-in user could join and post to any record's thread)
        if not await self._may_use(user):
            await self.close(code=4003)
            return
        self.group_name = f'chatter_{self.model_name}_{self.record_id}'

        # Cache the StaffProfile on connect so _create_message doesn't hit the
        # DB on every posted message (one query per connection, not per message)
        self._profile = await self._get_profile(user)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.zone_start()

    @database_sync_to_async
    def _may_use(self, user):
        from apps.notifications.chatter_access import can_use_thread
        return can_use_thread(user, self.model_name, self.record_id)

    @database_sync_to_async
    def _get_profile(self, user):
        from apps.users.models import StaffProfile
        try:
            return StaffProfile.objects.get(user=user)
        except StaffProfile.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        await self.zone_stop()
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
            from apps.notifications.chatter_access import MAX_MESSAGE_CHARS
            message = (data.get('message') or '').strip()
            if message and len(message) <= MAX_MESSAGE_CHARS:
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
