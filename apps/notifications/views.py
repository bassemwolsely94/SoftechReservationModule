from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Notification
from .serializers import NotificationSerializer


def get_profile(request):
    return getattr(request.user, 'staff_profile', None)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    """
    GET /api/notifications/
    Returns the 50 most recent notifications for the logged-in user.
    Query params:
      ?unread_only=true   — only unread notifications
      ?type=follow_up_due — filter by notification_type
    """
    profile = get_profile(request)
    if not profile:
        return Response([], status=status.HTTP_200_OK)

    qs = Notification.objects.filter(recipient=profile).order_by('-created_at')

    unread_only = request.query_params.get('unread_only') == 'true'
    if unread_only:
        qs = qs.filter(is_read=False)

    notif_type = request.query_params.get('type')
    if notif_type:
        qs = qs.filter(notification_type=notif_type)

    qs = qs.select_related('reservation')[:50]
    return Response(NotificationSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_count(request):
    """GET /api/notifications/unread-count/"""
    profile = get_profile(request)
    if not profile:
        return Response({'count': 0})
    count = Notification.objects.filter(recipient=profile, is_read=False).count()
    return Response({'count': count})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request, pk):
    """POST /api/notifications/{id}/read/"""
    profile = get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    updated = Notification.objects.filter(pk=pk, recipient=profile).update(is_read=True)
    if not updated:
        return Response({'detail': 'لم يتم العثور على الإشعار'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'detail': 'تم التعليم كمقروء'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_read(request):
    """POST /api/notifications/mark-all-read/"""
    profile = get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    count = Notification.objects.filter(recipient=profile, is_read=False).update(is_read=True)
    return Response({'marked': count})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_old(request):
    """
    DELETE /api/notifications/delete-old/
    Deletes all read notifications older than 30 days for the current user.
    """
    from django.utils import timezone
    from datetime import timedelta
    profile = get_profile(request)
    if not profile:
        return Response(status=status.HTTP_403_FORBIDDEN)
    cutoff = timezone.now() - timedelta(days=30)
    deleted, _ = Notification.objects.filter(
        recipient=profile, is_read=True, created_at__lt=cutoff
    ).delete()
    return Response({'deleted': deleted})
