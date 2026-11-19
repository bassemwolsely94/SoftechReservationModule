"""
apps/notifications/live.py — small live events over the existing notification WebSocket
(performance Stage 5, docs/superpowers/plans/2026-11-19-perf-stage5-live-updates.md).

Two events replace most of the polling every open screen used to do:

• **Bell counts** — `request_counts_push(profile_id)` tells that user's open sockets
  (group `notifications_user_{id}`) that their unread counts changed. The message carries NO data:
  each connected socket computes the counts itself (NotificationConsumer.notification_counts,
  debounced), so a user with no open tab costs nothing, and a burst of 50 new notifications costs one
  count per tab.

• **Freshness changed** — `broadcast_freshness(domains)` tells every staff socket (group
  `live_staff`) that a sync run or lane finished. The event carries only domain keys and a
  timestamp: the data-freshness bar, the sync status chip and the dashboard summary refetch on it.

Security (Stage 5 rule): neither event carries customer data, phone numbers or record content —
counts are integers, freshness is a list of domain keys plus an ISO time. Joining the groups happens
in NotificationConsumer.connect, after the usual login + zone (N5) checks.

Both send AFTER the database transaction commits (the counts must see the new rows) and never raise:
a channel-layer failure must not break the caller's write.
"""
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.notifications')

LIVE_STAFF_GROUP = 'live_staff'


def user_group(profile_id) -> str:
    return f'notifications_user_{profile_id}'


def _group_send(group: str, message: dict) -> None:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(group, message)
    except Exception as exc:   # never break the caller's write over a live hint
        logger.debug('live push to %s skipped: %s', group, exc)


def request_counts_push(profile_id) -> None:
    """After commit: ask this user's open sockets to send fresh unread category counts."""
    if not profile_id:
        return
    group = user_group(profile_id)
    transaction.on_commit(lambda: _group_send(group, {'type': 'notification.counts'}))


def broadcast_freshness(domains) -> None:
    """After commit: tell every staff socket that these data domains have new freshness."""
    keys = sorted({str(d) for d in (domains or []) if d})
    if not keys:
        return
    at = timezone.now().isoformat()
    transaction.on_commit(lambda: _group_send(
        LIVE_STAFF_GROUP, {'type': 'live.freshness', 'domains': keys, 'at': at}))


def freshness_message(event: dict) -> dict:
    """The exact client frame for a live.freshness group message — built from known fields only,
    so nothing else that rides the channel-layer message can reach a browser."""
    domains = [str(d) for d in (event.get('domains') or []) if isinstance(d, str)]
    return {'event': 'freshness_changed', 'domains': domains, 'at': str(event.get('at') or '')}


def _on_notification_saved(sender, instance, **kwargs):
    # A new notification, a snooze or an un-snooze (save()) changes the recipient's counts. Paths that
    # use queryset .update() / .delete() call request_counts_push themselves (views, consumer).
    request_counts_push(getattr(instance, 'recipient_id', None))


def connect_signals():
    from django.db.models.signals import post_save
    from .models import Notification
    post_save.connect(_on_notification_saved, sender=Notification,
                      dispatch_uid='notifications.live.counts_on_save')
