"""
apps/pbx/views.py
"""
from django.http import FileResponse, HttpResponseRedirect
from rest_framework import generics
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.pbx.models import AgentExtension, PBXQueue, CallSession, PBXEvent
from apps.pbx.serializers import (
    AgentExtensionSerializer, PBXQueueSerializer,
    CallSessionSerializer, PBXEventSerializer,
)


class AgentExtensionListView(generics.ListCreateAPIView):
    serializer_class   = AgentExtensionSerializer
    permission_classes = [IsAuthenticated]
    queryset           = AgentExtension.objects.select_related('staff').filter(is_active=True)


class AgentExtensionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = AgentExtensionSerializer
    permission_classes = [IsAuthenticated]
    queryset           = AgentExtension.objects.select_related('staff')


class QueueListView(generics.ListAPIView):
    serializer_class   = PBXQueueSerializer
    permission_classes = [IsAuthenticated]
    queryset           = PBXQueue.objects.filter(is_active=True)


class CallSessionListView(generics.ListAPIView):
    serializer_class   = CallSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = CallSession.objects.select_related(
            'agent__staff', 'customer', 'queue', 'call_log'
        ).order_by('-started_at')

        state = self.request.query_params.get('state')
        if state:
            qs = qs.filter(state=state)
        direction = self.request.query_params.get('direction')
        if direction:
            qs = qs.filter(direction=direction)
        return qs[:200]


class CallSessionDetailView(generics.RetrieveAPIView):
    serializer_class   = CallSessionSerializer
    permission_classes = [IsAuthenticated]
    queryset           = CallSession.objects.select_related(
        'agent__staff', 'customer', 'queue', 'call_log'
    )


class LiveSessionsView(APIView):
    """GET /api/pbx/live/ — active (non-completed) call sessions."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = CallSession.objects.filter(
            state__in=['ringing', 'answered', 'queued', 'on_hold', 'transferred']
        ).select_related('agent__staff', 'customer', 'queue').order_by('started_at')
        return Response(CallSessionSerializer(sessions, many=True).data)


class MyExtensionView(APIView):
    """GET /api/pbx/my-extension/ — current user's Asterisk extension."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = getattr(request.user, 'staff_profile', None)
        ext = AgentExtension.objects.filter(staff=profile).first() if profile else None
        if ext is None:
            return Response({'detail': 'لا توجد تحويلة مرتبطة بهذا الحساب'}, status=404)
        return Response(AgentExtensionSerializer(ext).data)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Supervisor live listen / whisper (ChanSpy) — doc 15 Phase 2
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        p = getattr(request.user, 'staff_profile', None)
        return bool(p and p.is_active and p.role in ('admin', 'supervisor'))


class SpyView(APIView):
    """
    POST /api/pbx/spy/  {"target_ext": "201", "mode": "listen"|"whisper"}

    Rings the supervisor's own extension; on answer, Asterisk bridges them
    into the agent's live call (silent, or whispering to the agent only).
    """
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def post(self, request):
        target_ext = str(request.data.get('target_ext', '')).strip()
        mode = request.data.get('mode', 'listen')
        if not target_ext:
            return Response({'detail': 'حدد تحويلة الموظف المستهدف'}, status=400)
        if mode not in ('listen', 'whisper'):
            return Response({'detail': 'الوضع يجب أن يكون listen أو whisper'}, status=400)

        profile = getattr(request.user, 'staff_profile', None)
        supervisor_ext = AgentExtension.objects.filter(staff=profile).first()
        if supervisor_ext is None:
            return Response(
                {'detail': 'لا توجد تحويلة مرتبطة بحسابك — اربط تحويلتك أولاً من إدارة التحويلات'},
                status=400,
            )

        from apps.pbx.actions import AMIActionError, originate_chanspy
        try:
            originate_chanspy(supervisor_ext.extension, target_ext, mode)
        except AMIActionError as exc:
            return Response({'detail': str(exc)}, status=502)
        except Exception as exc:
            return Response({'detail': f'خطأ AMI غير متوقع: {exc}'}, status=502)

        return Response({
            'detail': 'سيرن هاتفك الآن — عند الرد ستدخل المكالمة',
            'supervisor_ext': supervisor_ext.extension,
            'target_ext': target_ext,
            'mode': mode,
        })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Recording playback (tokenized — <audio> cannot send JWT headers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RecordingView(APIView):
    """GET /api/pbx/recordings/{session_pk}/?t=<signed token>"""
    permission_classes = []
    authentication_classes = []

    def get(self, request, pk):
        from apps.pbx import recordings

        if not recordings.validate_recording_token(pk, request.GET.get('t', '')):
            return Response({'detail': 'رابط غير صالح أو منتهي'}, status=403)
        try:
            session = CallSession.objects.get(pk=pk)
        except CallSession.DoesNotExist:
            return Response({'detail': 'الجلسة غير موجودة'}, status=404)

        local = recordings.resolve_local_path(session)
        if local:
            import mimetypes
            content_type = mimetypes.guess_type(local)[0] or 'audio/wav'
            return FileResponse(open(local, 'rb'), content_type=content_type)

        remote = recordings.resolve_remote_url(session)
        if remote:
            return HttpResponseRedirect(remote)

        return Response({'detail': 'لا يوجد تسجيل متاح لهذه المكالمة'}, status=404)
