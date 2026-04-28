from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .activity_models import ActivityLog
from .models import Reservation
from apps.notifications.models import Notification


class ActivityLogSerializer(serializers.ModelSerializer):
    logged_by_name = serializers.CharField(read_only=True)
    activity_type_display = serializers.CharField(
        source='get_activity_type_display', read_only=True
    )

    class Meta:
        model = ActivityLog
        fields = [
            'id', 'activity_type', 'activity_type_display',
            'note', 'logged_by_name', 'callback_datetime',
            'expected_date', 'logged_at',
        ]


class ActivityLogCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = ['activity_type', 'note', 'callback_datetime', 'expected_date']


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def reservation_activity(request, reservation_id):
    """GET activity log for a reservation. POST to add a new entry."""
    staff = getattr(request.user, 'staff_profile', None)

    try:
        reservation = Reservation.objects.get(pk=reservation_id)
    except Reservation.DoesNotExist:
        return Response({'error': 'Reservation not found'}, status=status.HTTP_404_NOT_FOUND)

    # Branch access check
    if staff and not staff.can_see_all_branches:
        if reservation.branch != staff.branch:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        logs = ActivityLog.objects.filter(
            reservation=reservation
        ).select_related('logged_by__user', 'logged_by__branch')
        return Response(ActivityLogSerializer(logs, many=True).data)

    # POST — log new activity
    serializer = ActivityLogCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    log = serializer.save(reservation=reservation, logged_by=staff)

    # Auto-update follow_up_date if callback was requested
    if log.activity_type == 'call_callback_requested' and log.callback_datetime:
        reservation.follow_up_date = log.callback_datetime.date()
        reservation.save(update_fields=['follow_up_date', 'updated_at'])

    # Auto-update expected_arrival_date if item expected
    if log.activity_type == 'item_expected_date' and log.expected_date:
        reservation.expected_arrival_date = log.expected_date
        reservation.save(update_fields=['expected_arrival_date', 'updated_at'])

    # Notify the other entity (branch notifies call center and vice versa)
    _notify_counterpart(request.user, staff, reservation, log)

    return Response(ActivityLogSerializer(log).data, status=status.HTTP_201_CREATED)


def _notify_counterpart(user, staff, reservation, log):
    """
    When branch staff logs an activity, notify call center.
    When call center logs an activity, notify the branch.
    """
    if not staff:
        return

    actor = staff.full_name
    branch_name = staff.branch_name
    title = f"تحديث على حجز #{reservation.id}"
    message = (
        f"{actor} ({branch_name}) سجّل: "
        f"{log.get_activity_type_display()}"
    )
    if log.note:
        message += f" — {log.note[:100]}"

    if staff.is_call_center or staff.is_admin:
        # Call center acted → notify branch
        Notification.send_to_branch(
            branch=reservation.branch,
            notification_type='call_logged',
            title=title,
            message=message,
            reservation=reservation,
            exclude_user=user,
        )
    else:
        # Branch acted → notify call center
        Notification.send_to_call_center(
            notification_type='call_logged',
            title=title,
            message=message,
            reservation=reservation,
            exclude_user=user,
        )
