"""/api/rpa/agent/ — the attended Windows agent's endpoints.

Signed in by device secret (RpaDeviceAuthentication) and run as the device's operator, so the rpa
module matrix (create) applies to that person. A device only ever sees documents it claimed, and
it only claims its operator's own jobs (dispatch.claim_next).
"""
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import public_error
from core.permissions import matrix_permission
from core.upload_safety import detect

from . import dispatch
from .auth import HasRpaDevice, RpaDeviceAuthentication
from .models import RpaDocument, RpaRun, RpaScreenshot

MAX_SHOT_BYTES = 2 * 1024 * 1024
MAX_SHOTS_PER_RUN = 300
_SHOT_FORMATS = ('png', 'jpg')


class AgentView(APIView):
    authentication_classes = [RpaDeviceAuthentication]
    permission_classes = [IsAuthenticated, HasRpaDevice, matrix_permission('rpa', post=('create',))]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def handle_exception(self, exc):
        if isinstance(exc, (APIException, Http404, DjangoPermissionDenied)):
            return super().handle_exception(exc)
        if isinstance(exc, RpaRun.DoesNotExist):
            return Response({'detail': 'التشغيل غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if isinstance(exc, dispatch.LeaseLost):
            return Response({'detail': 'انتهت مهلة هذا المستند أو لم يعد لهذا الجهاز'},
                            status=status.HTTP_409_CONFLICT)
        return Response({'detail': public_error(self.request, exc)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def my_document(self, request, pk):
        return get_object_or_404(RpaDocument, pk=pk, claimed_by=request.auth)


class ClaimView(AgentView):

    def post(self, request):
        claim = dispatch.claim_next(request.auth)
        if claim is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({'run_id': claim.run.pk, 'mode': claim.mode, 'keyplan': claim.keyplan})


class HeartbeatView(AgentView):

    def post(self, request, pk):
        lease_until = dispatch.extend_lease(self.my_document(request, pk), request.auth)
        return Response({'lease_until': lease_until.isoformat()})


class ReportView(AgentView):

    def post(self, request, pk):
        run = dispatch.report_run(self.my_document(request, pk), request.auth, request.data)
        return Response({'run_id': run.pk, 'outcome': run.outcome,
                         'status': RpaDocument.objects.values_list('status', flat=True).get(pk=pk)})


class ScreenshotView(AgentView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        run = get_object_or_404(RpaRun, pk=pk, device=request.auth)
        if run.finished_at is not None:
            return Response({'detail': 'انتهى هذا التشغيل'}, status=status.HTTP_409_CONFLICT)
        try:
            step_index = int(request.data.get('step_index', ''))
        except (TypeError, ValueError):
            raise ValidationError({'step_index': 'رقم خطوة غير صالح'})
        if step_index < 0:
            raise ValidationError({'step_index': 'رقم خطوة غير صالح'})
        upload = request.FILES.get('image')
        if upload is None:
            raise ValidationError({'image': 'لا توجد صورة'})
        if upload.size > MAX_SHOT_BYTES:
            raise ValidationError({'image': 'الصورة أكبر من 2 ميجابايت'})
        data = upload.read(MAX_SHOT_BYTES + 1)
        ext = detect(data, 'image') if len(data) <= MAX_SHOT_BYTES else None
        if ext not in _SHOT_FORMATS:
            raise ValidationError({'image': 'الصورة يجب أن تكون PNG أو JPEG'})
        if run.shots.count() >= MAX_SHOTS_PER_RUN:
            return Response({'detail': 'تم بلوغ الحد الأقصى للصور'}, status=status.HTTP_409_CONFLICT)
        shot = RpaScreenshot(run=run, step_index=step_index)
        shot.image.save(f'run{run.pk}_step{step_index}.{ext}', ContentFile(data), save=True)
        return Response({'id': shot.pk}, status=status.HTTP_201_CREATED)
