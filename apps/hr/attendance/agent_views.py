"""
apps/hr/attendance/agent_views.py — the API the office agent calls, under
/api/hr-attendance/agent/. No staff user: per-agent secret, hashed, constant-time (agent_auth.py).

Every answer is a JSON object, because the agent treats anything else as "not accepted" and keeps
its file. Agents can add data only; nothing here edits or deletes a stored punch.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ParseError, PermissionDenied
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hr.models import AttendanceAgent, AttendanceDevice
from core.errors import public_error

from . import ingest
from .agent_auth import AgentSecretAuthentication, HasAgentSecret


class SwitchedOff(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'الحضور والبصمة غير مفعل'
    default_code = 'switched_off'


class AgentView(APIView):
    authentication_classes = [AgentSecretAuthentication]
    permission_classes = [HasAgentSecret]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def initial(self, request, *args, **kwargs):
        if not settings.HR_ATTENDANCE_ENABLED:
            raise SwitchedOff()
        super().initial(request, *args, **kwargs)
        AttendanceAgent.objects.filter(pk=request.auth.pk).update(last_seen_at=timezone.now())

    def handle_exception(self, exc):
        if isinstance(exc, ingest.Malformed):
            return Response({'detail': 'طلب غير صالح'}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, (APIException, Http404, DjangoPermissionDenied)):
            return super().handle_exception(exc)
        return Response({'detail': public_error(self.request, exc)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def body(self, request):
        if not isinstance(request.data, dict):
            raise ParseError('طلب غير صالح')
        return request.data

    def device(self, request):
        """The named machine, only if it is assigned to this agent. An inactive machine still
        counts, so punches already waiting on the agent's disk aren't refused."""
        serial = self.body(request).get('device_serial')
        if not ingest.is_storable_text(serial):
            raise ParseError('طلب غير صالح')
        device = AttendanceDevice.objects.filter(serial=serial, agent=request.auth).first()
        if device is None:
            raise PermissionDenied('الجهاز غير مخصص لهذا البرنامج')
        return device

    def rows(self, request, key):
        rows = self.body(request).get(key)
        if not isinstance(rows, list):
            raise ParseError('طلب غير صالح')
        return rows


class AgentConfigView(AgentView):

    def get(self, request):
        agent = request.auth
        devices = AttendanceDevice.objects.filter(agent=agent, is_active=True).order_by('serial')
        return Response({
            'agent': agent.name,
            'collect_now': agent.collect_requested_at is not None,
            # Cairo local time (the zone the agent's naive stamps are read in). The agent
            # measures its own PC wall clock against this and reports machine drift
            # against the corrected time.
            'server_time': timezone.localtime().isoformat(),
            'devices': [{'serial': d.serial, 'name': d.name, 'ip': d.ip, 'port': d.port} for d in devices],
        })


class AgentPunchesView(AgentView):

    def post(self, request):
        rows = self.rows(request, 'punches')
        if len(rows) > ingest.MAX_PUNCHES_PER_REQUEST:
            return Response({'detail': 'عدد البصمات أكبر من المسموح'},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        accepted, duplicate = ingest.store_punches(self.device(request), rows)
        return Response({'accepted': accepted, 'duplicate': duplicate})


class AgentRosterView(AgentView):

    def post(self, request):
        users = self.rows(request, 'users')
        if len(users) > ingest.MAX_ROSTER_USERS:
            return Response({'detail': 'عدد المستخدمين أكبر من المسموح'},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        return Response({'stored': ingest.store_roster(self.device(request), users)})


class AgentRunsView(AgentView):

    def post(self, request):
        created = ingest.store_run(request.auth, self.device(request), self.body(request))
        return Response({'stored': created})
