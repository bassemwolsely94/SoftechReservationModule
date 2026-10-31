"""
apps/pbx/views.py
"""
from datetime import timedelta

from django.http import FileResponse, HttpResponseRedirect
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.pbx.models import AgentExtension, PBXQueue, CallSession, PBXEvent, PBXBridgeStatus
from core.errors import public_error
from apps.pbx.serializers import (
    AgentExtensionSerializer, PBXQueueSerializer,
    CallSessionSerializer, PBXEventSerializer,
)


class ReadOrAdminSupervisorWrite(BasePermission):
    """Any staff can read; only admin/supervisor change extension mapping."""
    def has_permission(self, request, view):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        p = getattr(request.user, 'staff_profile', None)
        return bool(p and p.is_active and p.role in ('admin', 'supervisor'))


from core.permissions import matrix_permission                     # noqa: E402

# PBX = the `callcenter` matrix module (Batch 4, Z-8b — queues, call sessions, live calls and
# dialling were open to any logged-in user). A user's own extension (my-extension) stays open:
# the POS screen-pop reads it. Diagnostics / extension map / spy keep admin / supervisor.
PBX = matrix_permission('callcenter', post=('create', 'edit', 'approve'))


class AgentExtensionListView(generics.ListCreateAPIView):
    serializer_class   = AgentExtensionSerializer
    permission_classes = [IsAuthenticated, PBX, ReadOrAdminSupervisorWrite]
    queryset           = AgentExtension.objects.select_related('staff').filter(is_active=True)


class AgentExtensionDetailView(generics.RetrieveUpdateAPIView):
    serializer_class   = AgentExtensionSerializer
    permission_classes = [IsAuthenticated, PBX, ReadOrAdminSupervisorWrite]
    queryset           = AgentExtension.objects.select_related('staff')


class QueueListView(generics.ListAPIView):
    serializer_class   = PBXQueueSerializer
    permission_classes = [IsAuthenticated, PBX]
    queryset           = PBXQueue.objects.filter(is_active=True)


class CallSessionListView(generics.ListAPIView):
    serializer_class   = CallSessionSerializer
    permission_classes = [IsAuthenticated, PBX]

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
    permission_classes = [IsAuthenticated, PBX]
    queryset           = CallSession.objects.select_related(
        'agent__staff', 'customer', 'queue', 'call_log'
    )


class LiveSessionsView(APIView):
    """GET /api/pbx/live/ — active (non-completed) call sessions."""
    permission_classes = [IsAuthenticated, PBX]

    # ?fresh=1 (POS screen-pop): only calls we can trust are live — the AMI bridge is alive
    # (no hang-up event can arrive without it) and the call started recently.
    FRESH_MAX_AGE = timedelta(hours=12)

    def get(self, request):
        sessions = CallSession.objects.filter(
            state__in=['ringing', 'answered', 'queued', 'on_hold', 'transferred']
        ).select_related('agent__staff', 'customer', 'queue').order_by('started_at')
        if request.query_params.get('fresh') == '1':
            bridge = PBXBridgeStatus.current()
            if not (bridge and bridge.is_alive):
                return Response([])
            sessions = sessions.filter(started_at__gte=timezone.now() - self.FRESH_MAX_AGE)
        return Response(CallSessionSerializer(sessions, many=True, context={'request': request}).data)


class MyExtensionView(APIView):
    """GET /api/pbx/my-extension/ — current user's Asterisk extension."""
    permission_classes = [IsAuthenticated]                      # own data: open (Z-8b)

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


class BridgeStatusView(APIView):
    """GET /api/pbx/status/ — connection badge (cheap; reads the bridge's row)."""
    permission_classes = [IsAuthenticated, PBX]

    def get(self, request):
        from apps.pbx.models import PBXBridgeStatus
        st = PBXBridgeStatus.current()
        if st is None:
            return Response({'state': 'unknown', 'alive': False, 'label': 'لم يعمل جسر السنترال بعد'})
        state = st.state if st.is_alive or st.state != 'connected' else 'stale'
        labels = dict(PBXBridgeStatus.STATE_CHOICES, stale='متوقف — لا نبضات')
        return Response({
            'state': state, 'alive': st.is_alive, 'label': labels.get(state, state),
            'host': st.host, 'port': st.port, 'banner': st.banner,
            'connected_since': st.connected_since, 'last_heartbeat_at': st.last_heartbeat_at,
            'last_event_at': st.last_event_at, 'last_error': st.last_error,
            'last_error_at': st.last_error_at, 'reconnect_count': st.reconnect_count,
        })


class DiagnosticsView(APIView):
    """POST /api/pbx/diagnostics/ — run the step-by-step connectivity check."""
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def post(self, request):
        from apps.pbx.diagnostics import run_diagnostics
        return Response(run_diagnostics())


class ExtensionStatusView(APIView):
    """GET /api/pbx/extensions/status/ — live registration per extension + mapping."""
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def get(self, request):
        from apps.pbx.extensions import extension_status
        return Response(extension_status())


class ExtensionMapView(APIView):
    """
    POST /api/pbx/extensions/map/ {extension, staff_id|null, extension_type?, sip_peer?}
    Maps an extension to a staff member in OUR database only (Issabel untouched).
    A staff member holds one extension: mapping moves them off any previous one.
    """
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def post(self, request):
        from django.db import transaction
        from apps.audit.models import AuditLog
        from apps.users.models import StaffProfile

        extension = str(request.data.get('extension', '')).strip()
        if not extension or len(extension) > 20:
            return Response({'detail': 'رقم التحويلة مطلوب'}, status=400)
        ext_type = request.data.get('extension_type')
        if ext_type and ext_type not in dict(AgentExtension.EXTENSION_TYPE_CHOICES):
            return Response({'detail': 'نوع تحويلة غير صحيح'}, status=400)

        staff = None
        staff_id = request.data.get('staff_id')
        if staff_id:
            staff = StaffProfile.objects.filter(pk=staff_id, is_active=True).first()
            if staff is None:
                return Response({'detail': 'الموظف غير موجود أو غير نشط'}, status=400)

        with transaction.atomic():
            ext, created = AgentExtension.objects.select_for_update().get_or_create(
                extension=extension,
                defaults={'extension_type': ext_type or AgentExtension.TYPE_AGENT})
            before = {'staff': ext.staff_id, 'type': ext.extension_type, 'sip_peer': ext.sip_peer}
            moved_from = None
            if staff is not None:
                prev = AgentExtension.objects.filter(staff=staff).exclude(pk=ext.pk).first()
                if prev:
                    moved_from = prev.extension
                    prev.staff = None
                    prev.save(update_fields=['staff', 'updated_at'])
            ext.staff = staff
            if ext_type:
                ext.extension_type = ext_type
            if 'sip_peer' in request.data:
                ext.sip_peer = str(request.data['sip_peer'] or '').strip()[:50]
            ext.save()
            after = {'staff': ext.staff_id, 'type': ext.extension_type, 'sip_peer': ext.sip_peer}

            AuditLog.log('pbx_extension_mapped', user=request.user.staff_profile, obj=ext,
                         changes={k: [before[k], after[k]] for k in after if before[k] != after[k]},
                         note=(f'ext {extension} → {staff.full_name if staff else "بدون موظف"}'
                               + (f' (نُقل من {moved_from})' if moved_from else '')
                               + (' — جديدة' if created else '')))

        # The bridge caches the extension registry; it reloads on reconnect
        return Response({**AgentExtensionSerializer(ext).data, 'moved_from': moved_from})


class StaffChoicesView(APIView):
    """GET /api/pbx/staff-choices/?q= — active staff for the mapping picker."""
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def get(self, request):
        from django.db.models import Q
        from apps.users.models import StaffProfile
        q = request.query_params.get('q', '').strip()
        qs = StaffProfile.objects.filter(is_active=True, user__is_active=True).select_related('user', 'branch')
        if q:
            qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
                           | Q(user__username__icontains=q))
        return Response([{'id': s.id, 'name': s.full_name, 'role': s.role,
                          'branch': s.branch.name_ar if s.branch_id else None}
                         for s in qs.order_by('user__first_name')[:30]])


class DialView(APIView):
    """
    POST /api/pbx/dial/  {"destination": "01012345678", "caller_id_name": "..."}

    Originates an outbound call from the requesting user's own extension.
    Asterisk rings the agent's desk phone; when answered, it dials the destination.
    """
    permission_classes = [IsAuthenticated, PBX]

    def post(self, request):
        destination = str(request.data.get('destination', '')).strip()
        if not destination:
            return Response({'detail': 'destination مطلوب'}, status=400)

        # Strip any non-digit chars except leading +
        import re as _re
        clean = _re.sub(r'[^\d+]', '', destination)
        if not clean:
            return Response({'detail': 'رقم هاتف غير صحيح'}, status=400)

        profile = getattr(request.user, 'staff_profile', None)
        ext = AgentExtension.objects.filter(staff=profile).first() if profile else None
        if ext is None:
            return Response(
                {'detail': 'لا توجد تحويلة مرتبطة بحسابك — اربطها من إدارة التحويلات'},
                status=400,
            )

        caller_id_name = request.data.get('caller_id_name', '') or (profile.full_name if profile else 'ElRezeiky')

        from apps.pbx.actions import AMIActionError, originate_call
        try:
            originate_call(ext.extension, clean, caller_id_name)
        except AMIActionError as exc:
            return Response({'detail': str(exc)}, status=502)
        except Exception as exc:
            return Response({'detail': f'خطأ AMI غير متوقع: {public_error(request, exc)}'}, status=502)

        return Response({
            'detail': 'سيرن هاتفك الآن — عند الرد سيُحوَّل إلى الرقم المطلوب',
            'caller_ext': ext.extension,
            'destination': clean,
        })


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
            return Response({'detail': f'خطأ AMI غير متوقع: {public_error(request, exc)}'}, status=502)

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

        recordings.ensure_recording(session)
        local = recordings.resolve_local_path(session)
        if local:
            import mimetypes
            content_type = mimetypes.guess_type(local)[0] or 'audio/wav'
            return FileResponse(open(local, 'rb'), content_type=content_type)

        if recordings.sftp_configured() and session.recording_path:
            from django.http import HttpResponse
            audio, mime = recordings.load_session_audio(session)
            if audio:
                return HttpResponse(audio, content_type=mime)

        remote = recordings.resolve_remote_url(session)
        if remote:
            return HttpResponseRedirect(remote)

        return Response({'detail': 'لا يوجد تسجيل متاح لهذه المكالمة'}, status=404)
