from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from .models import SyncRun, SyncLog


class SyncLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncLog
        fields = ['table_name', 'records_processed', 'created_at']


class SyncRunSerializer(serializers.ModelSerializer):
    logs = SyncLogSerializer(many=True, read_only=True)
    duration_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = SyncRun
        fields = ['id', 'status', 'started_at', 'completed_at',
                  'records_synced', 'error_message', 'duration_seconds', 'logs']


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_status(request):
    last = SyncRun.objects.first()
    return Response(SyncRunSerializer(last).data if last else {'status': 'no_sync_yet'})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_sync(request):
    from apps.sync.tasks import run_full_sync
    full = request.data.get('full', False)
    sync_run = run_full_sync(full_history=full)
    return Response(SyncRunSerializer(sync_run).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_logs(request):
    runs = SyncRun.objects.prefetch_related('logs').order_by('-started_at')[:20]
    return Response(SyncRunSerializer(runs, many=True).data)
