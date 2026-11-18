"""/api/rpa/agent/portal/ — the supplier-portal robot's endpoints on the buyer's PC.

Same sign-in as part 1's agent (apps/rpa/agent_views.AgentView): a device secret, run as the
device's operator, so the rpa module matrix (create) applies to that person. A device only gets
its operator's own jobs (queue.claim_next) and only touches runs it was given.
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.rpa.agent_views import AgentView, save_screenshot
from apps.rpa.models import PortalJob, PortalRun

from . import queue


class PortalAgentView(AgentView):

    def handle_exception(self, exc):
        if isinstance(exc, queue.RunConflict):
            return Response({'detail': 'هذا التشغيل ليس لهذا الجهاز أو لم يعد مفتوحاً'},
                            status=status.HTTP_409_CONFLICT)
        if isinstance(exc, queue.QueueError):
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, PortalRun.DoesNotExist):
            return Response({'detail': 'التشغيل غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        return super().handle_exception(exc)


class ClaimView(PortalAgentView):

    def post(self, request):
        claim = queue.claim_next(request.auth)
        if claim is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(claim)


class HeartbeatView(PortalAgentView):

    def post(self, request, pk):
        lease_until = queue.heartbeat(get_object_or_404(PortalRun, pk=pk), request.auth)
        return Response({'lease_until': lease_until.isoformat()})


class ReportView(PortalAgentView):

    def post(self, request, pk):
        run = get_object_or_404(PortalRun, pk=pk)
        result = queue.report(run, request.auth, request.data)
        run.refresh_from_db()
        kind = 'job' if isinstance(result, PortalJob) else 'basket'
        return Response({'run_id': run.pk, 'outcome': run.outcome, kind: result.pk, 'status': result.status})


class ScreenshotView(PortalAgentView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        run = get_object_or_404(PortalRun, pk=pk, device=request.auth)
        return save_screenshot(request, run, portal_run=run)
