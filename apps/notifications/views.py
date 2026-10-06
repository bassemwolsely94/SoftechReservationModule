"""
apps/notifications/views.py

REST endpoints for notifications, chatter, and notification preferences.

Notification endpoints:
  GET    /api/notifications/              → list (filter: unread_only, type, search)
  GET    /api/notifications/unread-count/ → {count: N}
  POST   /api/notifications/mark-all-read/
  DELETE /api/notifications/delete-old/
  DELETE /api/notifications/clear-all/
  POST   /api/notifications/{id}/read/
  DELETE /api/notifications/{id}/

Chatter endpoints:
  GET    /api/notifications/chatter/{model}/{id}/        → list messages
  POST   /api/notifications/chatter/{model}/{id}/post/   → create message

Preferences endpoint:
  GET/PATCH /api/notifications/preferences/
"""
import logging

from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.conf import settings

from .models import (
    Notification, NotificationLog, ChatterMessage, RoleNotificationAccess,
    PersonalReminder, Announcement, AnnouncementRead, PushSubscription,
)
from .serializers import (
    NotificationSerializer,
    ChatterMessageSerializer,
    PersonalReminderSerializer,
    AnnouncementSerializer,
)

logger = logging.getLogger('elrezeiky.notifications')


def _get_profile(request):
    return getattr(request.user, 'staff_profile', None)


# Module-scoped categories are gated by the same RBAC the rest of each module
# uses: you must have `view` on the module to read its notification feed.
_CATEGORY_MODULE = {
    'demand':       'demand',
    'followups':    'followups',
    'delivery':     'delivery',
    'transfers':    'transfers',
    'reservations': 'reservations',
    'settings':     'settings',
    # 'monitoring' spans delivery + in-transit; left ungated (recipient-scoped).
}


def _can_view_category(profile, category):
    """True if the profile may see this notifier (category).

    Resolution: admin → always; explicit RoleNotificationAccess row → its value;
    otherwise INHERIT the module 'view' permission (ungated categories default on).
    """
    if not profile:
        return False
    # Personal per-user mute applies even to admins (it's their own choice).
    if category in (getattr(profile, 'muted_notification_categories', None) or []):
        return False
    if getattr(profile, 'role', None) == 'admin':
        return True
    row = (RoleNotificationAccess.objects
           .filter(role=profile.role, category=category)
           .values_list('is_allowed', flat=True).first())
    if row is not None:
        return row
    module = _CATEGORY_MODULE.get(category)
    if not module:
        return True
    return bool(profile.can_do(module, 'view'))


def _visible_categories(profile):
    """The set of notifier categories this profile may see (admin → all).

    Single batched read of the role's explicit overrides; falls back to module
    'view' for anything not explicitly set. Used to filter the bell + counts.
    """
    all_cats = [c for c, _ in Notification.CATEGORY_CHOICES]
    if not profile:
        return set()
    muted = set(getattr(profile, 'muted_notification_categories', None) or [])
    if getattr(profile, 'role', None) == 'admin':
        return set(all_cats) - muted
    explicit = dict(
        RoleNotificationAccess.objects
        .filter(role=profile.role).values_list('category', 'is_allowed')
    )
    visible = set()
    for c in all_cats:
        if c in muted:
            continue   # personal mute hides it for this user
        if c in explicit:
            if explicit[c]:
                visible.add(c)
        else:
            module = _CATEGORY_MODULE.get(c)
            if not module or profile.can_do(module, 'view'):
                visible.add(c)
    return visible


# ── Gap-4: chatter branch scope ───────────────────────────────────────────────

# Roles that can read chatter for ANY branch (HQ / oversight roles).
_CHATTER_BYPASS_ROLES = frozenset({'admin', 'call_center', 'manager', 'purchasing'})


def _get_record_branch_id(model_name: str, record_id: int):
    """
    Returns the branch_id that owns the record, or None if unknown/not found.
    Used to scope chatter_list access: branch-level staff only see their branch.

    Dispatch table: add new models here as they become chattable.
    """
    try:
        if model_name == 'reservation':
            from apps.reservations.models import Reservation
            return Reservation.objects.values_list('branch_id', flat=True).get(pk=record_id)
        if model_name == 'transfer':
            from apps.transfers.models import Transfer
            return Transfer.objects.values_list('from_branch_id', flat=True).get(pk=record_id)
        if model_name == 'voucher':
            from apps.vouchers.models import Voucher
            return Voucher.objects.values_list('branch_id', flat=True).get(pk=record_id)
    except Exception:
        pass
    # Unknown model or record not found → return None (fail-open: empty list returned)
    return None


# ── Notification list ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    """
    GET /api/notifications/

    Query params:
      ?unread_only=true
      ?type=follow_up_due         — filter by notification_type
      ?search=text                — search in title + body
      ?limit=50                   — page size (max 200)
    """
    profile = _get_profile(request)
    if not profile:
        return Response([], status=status.HTTP_200_OK)

    qs = (Notification.objects.filter(recipient=profile)
          .exclude(snoozed_until__gt=timezone.now())   # hide snoozed until due
          .order_by('-created_at'))

    # Category routing: a specific ?category= returns that module feed; otherwise
    # the global bell EXCLUDES module-scoped categories (demand, followups).
    category = request.query_params.get('category')
    if category:
        if not _can_view_category(profile, category):
            return Response({'detail': 'ليس لديك صلاحية الاطلاع على إشعارات هذه الوحدة'},
                            status=status.HTTP_403_FORBIDDEN)
        qs = qs.filter(category=category)
    else:
        # Default bell = visible, non-quiet categories (per-role notifier visibility).
        bell_visible = [c for c in _visible_categories(profile)
                        if c not in Notification.MODULE_CATEGORIES]
        qs = qs.filter(category__in=bell_visible)

    if request.query_params.get('unread_only') == 'true':
        qs = qs.filter(is_read=False)

    notif_type = request.query_params.get('type')
    if notif_type:
        qs = qs.filter(notification_type=notif_type)

    search = request.query_params.get('search', '').strip()
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=search) | Q(body__icontains=search))

    try:
        limit = min(int(request.query_params.get('limit', 50)), 200)
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = max(int(request.query_params.get('offset', 0)), 0)
    except (ValueError, TypeError):
        offset = 0

    qs = qs.select_related('reservation')[offset:offset + limit]
    return Response(NotificationSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_count(request):
    """GET /api/notifications/unread-count/

    Default (global bell) excludes module-scoped categories. Pass ?category=demand
    to count a single module feed.
    """
    profile = _get_profile(request)
    if not profile:
        return Response({'count': 0})
    qs = (Notification.objects.filter(recipient=profile, is_read=False)
          .exclude(snoozed_until__gt=timezone.now()))
    category = request.query_params.get('category')
    if category:
        if not _can_view_category(profile, category):
            return Response({'count': 0}, status=status.HTTP_403_FORBIDDEN)
        qs = qs.filter(category=category)
    else:
        bell_visible = [c for c in _visible_categories(profile)
                        if c not in Notification.MODULE_CATEGORIES]
        qs = qs.filter(category__in=bell_visible)
    return Response({'count': qs.count()})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def category_counts(request):
    """GET /api/notifications/category-counts/

    Unread counts per category in one call — powers the global bell badge and the
    per-module sidebar hints. Shape: {global: N, demand: M, followups: K}.
    """
    profile = _get_profile(request)
    if not profile:
        return Response({'global': 0, 'demand': 0, 'followups': 0})
    from django.db.models import Count
    rows = (
        Notification.objects.filter(recipient=profile, is_read=False)
        .exclude(snoozed_until__gt=timezone.now())
        .values('category').annotate(n=Count('id'))
    )
    counts = {row['category']: row['n'] for row in rows}
    visible = _visible_categories(profile)
    # Zero out any notifier the role can't see (explicit hide or no module view),
    # so a hidden feed never reveals a count.
    def _scoped(cat):
        return counts.get(cat, 0) if cat in visible else 0
    return Response({
        'global':       _scoped(Notification.CATEGORY_GLOBAL),
        'demand':       _scoped(Notification.CATEGORY_DEMAND),
        'followups':    _scoped(Notification.CATEGORY_FOLLOWUPS),
        'delivery':     _scoped(Notification.CATEGORY_DELIVERY),
        'transfers':    _scoped(Notification.CATEGORY_TRANSFERS),
        'reservations': _scoped(Notification.CATEGORY_RESERVATIONS),
        'monitoring':   _scoped(Notification.CATEGORY_MONITORING),
        'settings':     _scoped(Notification.CATEGORY_SETTINGS),
        'reports':      _scoped(Notification.CATEGORY_REPORTS),
        'mentions':     _scoped(Notification.CATEGORY_MENTIONS),
        # Bell badge = sum of VISIBLE categories that ride the main bell.
        'bell': sum(
            n for cat, n in counts.items()
            if cat in visible and cat not in Notification.MODULE_CATEGORIES
        ),
        # Which notifiers this role may see — drives front-end feed hiding + WS drop.
        'visible': sorted(visible),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request, pk):
    """POST /api/notifications/{id}/read/"""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    updated = Notification.objects.filter(pk=pk, recipient=profile).update(is_read=True)
    if not updated:
        return Response(
            {'detail': 'لم يتم العثور على الإشعار'},
            status=status.HTTP_404_NOT_FOUND,
        )
    # Keep NotificationLog in sync
    NotificationLog.objects.filter(
        notification_id=pk, recipient=profile, read_at__isnull=True
    ).update(read_at=timezone.now())
    return Response({'detail': 'تم التعليم كمقروء'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_action(request):
    """POST /api/notifications/bulk/

    Body: {"ids": [1,2,3], "action": "read" | "delete" | "snooze", "minutes": 60}
    Scoped to the caller's own notifications.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    ids    = request.data.get('ids') or []
    action = request.data.get('action')
    if not isinstance(ids, list) or not ids:
        return Response({'detail': 'حدد عناصر أولاً'}, status=status.HTTP_400_BAD_REQUEST)
    qs = Notification.objects.filter(pk__in=ids, recipient=profile)

    if action == 'read':
        n = qs.update(is_read=True)
        NotificationLog.objects.filter(
            notification_id__in=ids, recipient=profile, read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({'updated': n})
    if action == 'delete':
        n, _ = qs.delete()
        return Response({'deleted': n})
    if action == 'snooze':
        try:
            m = int(request.data.get('minutes', 60))
        except (ValueError, TypeError):
            m = 60
        n = qs.update(snoozed_until=timezone.now() + timedelta(minutes=max(m, 1)), is_read=False)
        return Response({'snoozed': n})
    return Response({'detail': 'إجراء غير معروف'}, status=status.HTTP_400_BAD_REQUEST)


_SNOOZE_PRESETS = {'15m': 15, '1h': 60, '3h': 180}  # convenience labels


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def snooze_notification(request, pk):
    """POST /api/notifications/{id}/snooze/

    Body (one of):
      {"minutes": 60}         — snooze N minutes from now (0 → un-snooze)
      {"preset": "1h"}        — 15m | 1h | 3h
      {"until": "<ISO>"}      — snooze until an explicit datetime

    A snoozed notification leaves the bell/counts now and a 1-minute worker
    clears it + re-pushes (re-alarm) when due.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    notif = Notification.objects.filter(pk=pk, recipient=profile).first()
    if not notif:
        return Response({'detail': 'لم يتم العثور على الإشعار'}, status=status.HTTP_404_NOT_FOUND)

    until_raw = request.data.get('until')
    preset    = request.data.get('preset')
    minutes   = request.data.get('minutes')
    if preset in _SNOOZE_PRESETS:
        minutes = _SNOOZE_PRESETS[preset]

    if until_raw:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(until_raw)
        if dt is None:
            return Response({'detail': 'صيغة وقت غير صالحة'}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        notif.snoozed_until = dt
    elif minutes is not None:
        try:
            m = int(minutes)
        except (ValueError, TypeError):
            return Response({'detail': 'قيمة الدقائق غير صالحة'}, status=status.HTTP_400_BAD_REQUEST)
        notif.snoozed_until = None if m <= 0 else timezone.now() + timedelta(minutes=m)
    else:
        return Response({'detail': 'حدد minutes أو preset أو until'}, status=status.HTTP_400_BAD_REQUEST)

    if notif.snoozed_until:
        notif.snooze_count = (notif.snooze_count or 0) + 1
        notif.is_read = False   # so it returns as unread and re-alarms
    notif.save(update_fields=['snoozed_until', 'snooze_count', 'is_read'])
    return Response({
        'detail': 'تم تأجيل الإشعار' if notif.snoozed_until else 'تم إلغاء التأجيل',
        'snoozed_until': notif.snoozed_until,
        'snooze_count': notif.snooze_count,
    })


# ── Personal reminders ──────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def reminders(request):
    """GET  /api/notifications/reminders/        → my pending reminders (?all=true for history)
       POST /api/notifications/reminders/        → create {title, note, remind_at, ...}"""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        qs = PersonalReminder.objects.filter(owner=profile)
        if request.query_params.get('all') != 'true':
            qs = qs.filter(is_fired=False)
        return Response(PersonalReminderSerializer(qs.order_by('remind_at'), many=True).data)

    ser = PersonalReminderSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    obj = ser.save(owner=profile)
    return Response(PersonalReminderSerializer(obj).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def reminder_detail(request, pk):
    """PATCH/DELETE /api/notifications/reminders/{id}/ — only the owner's own."""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    obj = PersonalReminder.objects.filter(pk=pk, owner=profile).first()
    if not obj:
        return Response({'detail': 'لم يتم العثور على التذكير'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = PersonalReminderSerializer(obj, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(PersonalReminderSerializer(obj).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_read(request):
    """POST /api/notifications/mark-all-read/

    Scoped like the list: default marks only the global bell; ?category=demand
    marks just that module feed. Prevents the bell's "mark all" from silently
    clearing module-scoped notifications the user hasn't seen yet.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    now = timezone.now()
    qs  = (Notification.objects.filter(recipient=profile, is_read=False)
           .exclude(snoozed_until__gt=now))   # don't mark snoozed (hidden) as read
    category = request.query_params.get('category')
    if category:
        if not _can_view_category(profile, category):
            return Response({'marked': 0}, status=status.HTTP_403_FORBIDDEN)
        qs = qs.filter(category=category)
    else:
        bell_visible = [c for c in _visible_categories(profile)
                        if c not in Notification.MODULE_CATEGORIES]
        qs = qs.filter(category__in=bell_visible)
    count = qs.update(is_read=True)
    NotificationLog.objects.filter(
        recipient=profile, read_at__isnull=True
    ).update(read_at=now)
    return Response({'marked': count})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_old(request):
    """DELETE /api/notifications/delete-old/ — read notifications older than 30 days."""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    cutoff   = timezone.now() - timedelta(days=30)
    deleted, _ = Notification.objects.filter(
        recipient=profile, is_read=True, created_at__lt=cutoff
    ).delete()
    return Response({'deleted': deleted})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_notification(request, pk):
    """DELETE /api/notifications/{id}/"""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    deleted, _ = Notification.objects.filter(pk=pk, recipient=profile).delete()
    if not deleted:
        return Response(
            {'detail': 'لم يتم العثور على الإشعار'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_all(request):
    """DELETE /api/notifications/clear-all/"""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    deleted, _ = Notification.objects.filter(recipient=profile).delete()
    return Response({'deleted': deleted})


# ── Notification preferences ──────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def preferences(request):
    """
    GET  /api/notifications/preferences/
    PATCH /api/notifications/preferences/

    Body (PATCH):
      { "enable_notifications": true, "enable_sound": false,
        "enable_browser_push": false, "muted_notification_categories": ["monitoring"] }
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    def _payload():
        return {
            'enable_notifications': profile.enable_notifications,
            'enable_sound':         profile.enable_sound,
            'enable_browser_push':  profile.enable_browser_push,
            'muted_notification_categories': profile.muted_notification_categories or [],
            # The categories this user's role exposes (so the UI can offer per-category mute)
            'notifiers': [{'value': v, 'label': l} for v, l in Notification.CATEGORY_CHOICES],
        }

    if request.method == 'GET':
        return Response(_payload())

    # PATCH
    updated = []
    for field in ('enable_notifications', 'enable_sound', 'enable_browser_push'):
        if field in request.data:
            setattr(profile, field, bool(request.data[field]))
            updated.append(field)
    if 'muted_notification_categories' in request.data:
        valid = {v for v, _ in Notification.CATEGORY_CHOICES}
        raw = request.data.get('muted_notification_categories') or []
        profile.muted_notification_categories = [c for c in raw if c in valid]
        updated.append('muted_notification_categories')
    if updated:
        profile.save(update_fields=updated)

    return Response(_payload())


# ── Web Push (VAPID) subscriptions ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def vapid_public_key(request):
    """GET /api/notifications/push/vapid-public-key/

    Returns the server's VAPID public key the browser needs to subscribe.
    `enabled` is False when no key is configured (front-end hides the affordance).
    """
    key = getattr(settings, 'WEBPUSH_VAPID_PUBLIC_KEY', '') or ''
    return Response({'public_key': key, 'enabled': bool(key)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def push_subscribe(request):
    """POST /api/notifications/push/subscribe/

    Body: a W3C PushSubscription JSON
      { "endpoint": "...", "keys": { "p256dh": "...", "auth": "..." } }

    Upserts by endpoint and flips the user's enable_browser_push preference on.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    data     = request.data or {}
    endpoint = (data.get('endpoint') or '').strip()
    keys     = data.get('keys') or {}
    p256dh   = (keys.get('p256dh') or '').strip()
    auth     = (keys.get('auth') or '').strip()
    if not endpoint or not p256dh or not auth:
        return Response({'detail': 'بيانات الاشتراك غير مكتملة'},
                        status=status.HTTP_400_BAD_REQUEST)

    user_agent = request.META.get('HTTP_USER_AGENT', '')[:300]
    sub, _created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'recipient':  profile,
            'p256dh':     p256dh,
            'auth':       auth,
            'user_agent': user_agent,
        },
    )
    if not profile.enable_browser_push:
        profile.enable_browser_push = True
        profile.save(update_fields=['enable_browser_push'])
    return Response({'detail': 'تم تفعيل إشعارات المتصفح', 'id': sub.id},
                    status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def push_unsubscribe(request):
    """POST /api/notifications/push/unsubscribe/

    Body: { "endpoint": "..." }
    Removes this endpoint. When the user has no endpoints left, the
    enable_browser_push preference is flipped back off.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    endpoint = (request.data.get('endpoint') or '').strip()
    if endpoint:
        PushSubscription.objects.filter(recipient=profile, endpoint=endpoint).delete()
    if not PushSubscription.objects.filter(recipient=profile).exists():
        if profile.enable_browser_push:
            profile.enable_browser_push = False
            profile.save(update_fields=['enable_browser_push'])
    return Response({'detail': 'تم إلغاء إشعارات المتصفح'})


# ── Announcements / internal broadcast ─────────────────────────────────────────

_BROADCAST_ROLES = frozenset({'admin', 'supervisor'})


def _can_broadcast(profile):
    return bool(profile and (profile.role in _BROADCAST_ROLES))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def announcements(request):
    """GET  /api/notifications/announcements/   → announcements targeted at me (+ my read state)
       POST /api/notifications/announcements/   → publish (admin/supervisor) + fan out notifications"""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        from django.db.models import Q
        now = timezone.now()
        qs = (Announcement.objects
              .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
              .filter(Q(audience_roles=[]) | Q(audience_roles__contains=[profile.role]))
              .select_related('author', 'author__user'))
        if profile.branch_id is not None:
            qs = qs.filter(Q(audience_branch_ids=[]) | Q(audience_branch_ids__contains=[profile.branch_id]))
        else:
            qs = qs.filter(audience_branch_ids=[])
        read_ids = set(AnnouncementRead.objects
                       .filter(staff=profile, announcement__in=qs).values_list('announcement_id', flat=True))
        data = AnnouncementSerializer(qs, many=True, context={'read_ids': read_ids}).data
        return Response(data)

    # POST — publish
    if not _can_broadcast(profile):
        return Response({'detail': 'لا تملك صلاحية نشر الإعلانات'}, status=status.HTTP_403_FORBIDDEN)
    ser = AnnouncementSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    ann = ser.save(author=profile)
    try:
        ann.fan_out()
    except Exception:
        logger.exception('announcement fan-out failed: %s', ann.pk)
    return Response(AnnouncementSerializer(ann, context={'read_ids': set()}).data,
                    status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def announcement_ack(request, pk):
    """POST /api/notifications/announcements/{id}/ack/ — acknowledge (read receipt)."""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    if not Announcement.objects.filter(pk=pk).exists():
        return Response({'detail': 'غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    AnnouncementRead.objects.get_or_create(announcement_id=pk, staff=profile)
    return Response({'detail': 'تم التأكيد'})


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def announcement_detail(request, pk):
    """GET stats (author/admin) · DELETE (author/admin)."""
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    ann = Announcement.objects.filter(pk=pk).select_related('author').first()
    if not ann:
        return Response({'detail': 'غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    is_owner = (ann.author_id == profile.id) or profile.role == 'admin'

    if request.method == 'DELETE':
        if not is_owner:
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
        ann.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # GET → read stats (author/admin only)
    if not is_owner:
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    ann._audience_count = ann.audience_staff().count()
    ann._read_count     = ann.reads.count()
    readers = list(ann.reads.select_related('staff', 'staff__user')
                   .values('staff__id', 'read_at'))
    payload = AnnouncementSerializer(ann, context={'read_ids': set()}).data
    payload['readers'] = readers
    return Response(payload)


# ── Chatter ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chatter_list(request, model_name, record_id):
    """
    GET /api/notifications/chatter/{model_name}/{record_id}/

    Returns all chatter messages for a record, oldest first.
    Query params:
      ?since_id=<id>    — only messages newer than this id (for polling fallback)
      ?limit=100

    Gap-4 fix: branch-scoped staff (pharmacist, salesperson) may only read
    chatter for records belonging to their own branch.  Admins, call-center,
    managers and purchasing roles bypass this check.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    # Branch scope enforcement
    if profile.role not in _CHATTER_BYPASS_ROLES and not getattr(profile, 'access_all_branches', False):
        try:
            record_id_int = int(record_id)
        except (ValueError, TypeError):
            record_id_int = None
        if record_id_int is not None:
            record_branch_id = _get_record_branch_id(model_name, record_id_int)
            if record_branch_id is not None and record_branch_id != profile.branch_id:
                return Response(
                    {'detail': 'ليس لديك صلاحية الاطلاع على سجلات هذا الفرع'},
                    status=status.HTTP_403_FORBIDDEN,
                )

    qs = (
        ChatterMessage.objects
        .filter(model_name=model_name, record_id=record_id)
        .select_related('author', 'author__user')
        .order_by('created_at')
    )

    since_id = request.query_params.get('since_id')
    if since_id:
        try:
            qs = qs.filter(pk__gt=int(since_id))
        except (ValueError, TypeError):
            pass

    try:
        limit = min(int(request.query_params.get('limit', 100)), 500)
    except (ValueError, TypeError):
        limit = 100

    qs = qs[:limit]
    return Response(ChatterMessageSerializer(qs, many=True).data)


_ALLOWED_CHATTER_MODELS = frozenset({
    'reservation', 'transfer', 'demand', 'invoice', 'purchase_order',
    'stock_count', 'shortage', 'voucher',
})


_ALLOWED_AUDIO_TYPES = {
    'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg',
    'audio/wav', 'audio/m4a', 'audio/aac',
}
_ALLOWED_ATTACHMENT_TYPES = _ALLOWED_AUDIO_TYPES | {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf',
}
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20 MB


def _validate_chatter_file(f, allowed_types):
    """Validate an uploaded chatter file (size + content type).

    Returns an Arabic error string when invalid, or None when OK.
    """
    if f.size > _MAX_ATTACHMENT_BYTES:
        return 'حجم الملف كبير جداً (الحد الأقصى 20 ميجابايت)'
    content_type = f.content_type or ''
    if content_type not in allowed_types:
        return f'نوع الملف "{content_type}" غير مدعوم'
    return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chatter_post(request, model_name, record_id):
    """
    POST /api/notifications/chatter/{model_name}/{record_id}/post/

    Accepts either:
      • JSON:      { "message": "..." }
      • Multipart: message (field) + attachment (file, optional)

    Creates a ChatterMessage. The model's save() triggers @mention notifications
    and pushes to WebSocket group chatter_{model_name}_{record_id}.
    """
    profile = _get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)

    # Validate model_name against an allowed list to prevent arbitrary group names
    if model_name not in _ALLOWED_CHATTER_MODELS:
        return Response(
            {'detail': f'نوع السجل "{model_name}" غير مدعوم'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    message = (request.data.get('message') or '').strip()
    attachment = request.FILES.get('attachment')
    # Dedicated voice note — independent of `attachment` so a message can carry
    # an image AND a voice note together (parity with reservation/transfer chatter).
    voice_note = request.FILES.get('voice_note')

    # Allow attachment/voice-only messages (no text required when a file is present)
    if not message and not attachment and not voice_note:
        return Response(
            {'detail': 'الرسالة فارغة'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(message) > 2000:
        return Response(
            {'detail': 'الرسالة طويلة جداً (الحد الأقصى 2000 حرف)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        record_id_int = int(record_id)
    except (ValueError, TypeError):
        return Response(
            {'detail': 'معرف السجل غير صالح'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Attachment validation (image / doc / legacy audio) ────────────────────
    file_type = ''
    if attachment:
        err = _validate_chatter_file(attachment, _ALLOWED_ATTACHMENT_TYPES)
        if err:
            return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)
        content_type = attachment.content_type or ''
        if content_type.startswith('audio/'):
            file_type = 'voice'
        elif content_type.startswith('image/'):
            file_type = 'image'
        else:
            file_type = 'doc'

    # ── Voice note validation (audio only) ────────────────────────────────────
    if voice_note:
        err = _validate_chatter_file(voice_note, _ALLOWED_AUDIO_TYPES)
        if err:
            return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)

    msg = ChatterMessage.objects.create(
        model_name=model_name,
        record_id=record_id_int,
        author=profile,
        message=message,
        attachment=attachment,
        file_type=file_type,
        voice_note=voice_note,
    )
    return Response(
        ChatterMessageSerializer(msg, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )
