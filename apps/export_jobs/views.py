"""
apps/export_jobs/views.py — follow and download one's own export job (performance Stage 4).

  GET /api/export-jobs/<id>/            status + progress
  GET /api/export-jobs/<id>/download/   the file, once done

Own gate (module_access EXEMPT_PREFIXES): a job is only ever visible to the staff member who
started it — another user's id answers 404 like a missing one — and the download re-checks the
kind's own permission (access can be revoked after the job started). Starting a job is under the
exporting module's own URL, so its module grant applies there. The download is an attachment,
so ExportAuditMiddleware writes `export_taken` and stamps the xlsx like any direct export (N5).
"""
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import runner
from .models import ExportJob
from .registry import XLSX, get_kind


def own_job(user, pk, kind=None):
    """The requester's own job (no bytes), stale rule applied, or None."""
    profile = getattr(user, 'staff_profile', None)
    if profile is None:
        return None
    qs = ExportJob.objects.defer('data').filter(pk=pk, requested_by=profile)
    if kind:
        qs = qs.filter(kind=kind)
    job = qs.first()
    return runner.refresh_if_stale(job) if job else None


def not_found():
    return Response({'detail': 'غير موجود — Not found'}, status=status.HTTP_404_NOT_FOUND)


def file_response(request, job, *, allowed=None, audit_extra=None):
    """The download answer for an own job: 403 when access was revoked, 409 until done, else the
    bytes (+ the kind's own audit row when it has one)."""
    kind = get_kind(job.kind)
    ok = kind.allowed(request.user) if allowed is None else allowed
    if not ok:
        return Response({'detail': 'غير مصرح لك.'}, status=status.HTTP_403_FORBIDDEN)
    if job.status != ExportJob.DONE:
        return Response({'detail': 'الملف غير جاهز', 'status': job.status}, status=status.HTTP_409_CONFLICT)
    data = ExportJob.objects.filter(pk=job.pk).values_list('data', flat=True).first()
    if not data:
        return not_found()
    if kind.audit_action:
        from apps.audit.models import AuditLog
        extra = audit_extra if audit_extra is not None else {'filters': job.meta, 'rows': job.rows,
                                                             'job_id': job.pk}
        AuditLog.log(kind.audit_action, user=job.requested_by, request=request, note=job.file_name, extra=extra)
    resp = HttpResponse(bytes(data), content_type=job.content_type or XLSX)
    resp['Content-Disposition'] = content_disposition_header(True, job.file_name or f'export-{job.pk}')
    return resp


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_status(request, pk):
    job = own_job(request.user, pk)
    return Response(runner.job_json(job)) if job else not_found()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_download(request, pk):
    job = own_job(request.user, pk)
    return file_response(request, job) if job else not_found()
