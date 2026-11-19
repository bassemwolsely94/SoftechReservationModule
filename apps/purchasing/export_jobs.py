"""
apps/purchasing/export_jobs.py — purchasing exports as background jobs (performance Stage 4).

  POST /api/purchasing/export/jobs/?<same query as export/>        kind 'purchasing'
  POST /api/purchasing/isr/fulfilment/export/jobs/  <same body>     kind 'isr_fulfilment'

Each job replays the old direct export (export_purchasing_response / isr_fulfilment_export_response)
with the stored query or body and the requester, so the file is the same one — same sheets,
columns, values, formula guard and branch labels. Follow / download: /api/export-jobs/<id>/.

ISR fulfilment can read SOFTECH live (when the screen's cached snapshot has expired), so it always
runs on the web process's thread, never on the jobs service (design §10).
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.export_jobs import runner
from apps.export_jobs.registry import ExportFile, ExportKind
from core.permissions import matrix_allows


def _profile(user):
    return getattr(user, 'staff_profile', None)


# ── purchasing/export/ (flat xlsx / csv, pivot) ──────────────────────────────────────────────────

def _purchasing_allowed(user):
    # the direct GET export's permission: IsAuthenticated + PURCHASING (GET -> view)
    return matrix_allows(_profile(user), 'purchasing', 'view')


def _purchasing_validate(request):
    from .views import _latest_run
    if not _latest_run():
        return Response({'detail': 'لا توجد بيانات — شغّل المحرك أولاً'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


def _purchasing_build(job, user, progress):
    from .views import export_purchasing_response
    progress(5, 'قراءة بيانات المشتريات…')
    resp = export_purchasing_response(runner.replay_request(job, user, PURCHASING))
    data, name, ctype = runner.file_from_response(resp)
    return ExportFile(data=data, file_name=name, content_type=ctype)


PURCHASING = ExportKind(key='purchasing', label='تصدير المشتريات', allowed=_purchasing_allowed,
                        build=_purchasing_build, validate=_purchasing_validate)


# ── purchasing/isr/fulfilment/export/ ────────────────────────────────────────────────────────────

def _isr_allowed(user):
    # the direct POST export's permission: PURCHASING (POST -> create/edit/approve) + _can_view_fulfilment
    from .access import can_run_engine, can_supply_write
    return (matrix_allows(_profile(user), 'purchasing', 'create', 'edit', 'approve')
            and (can_supply_write(user) or can_run_engine(user)))


def _isr_validate(request):
    from .isr_views import _fulfil_error, _fulfil_inputs
    try:
        _fulfil_inputs(request)
    except ValueError as exc:
        return _fulfil_error(exc)
    return None


def _isr_build(job, user, progress):
    from .isr_views import isr_fulfilment_export_response
    progress(5, 'قراءة طلبات التوريد…')
    resp = isr_fulfilment_export_response(runner.replay_request(job, user, ISR_FULFILMENT))
    data, name, ctype = runner.file_from_response(resp)
    return ExportFile(data=data, file_name=name, content_type=ctype)


ISR_FULFILMENT = ExportKind(key='isr_fulfilment', label='خطة تلبية طلبات التوريد', allowed=_isr_allowed,
                            build=_isr_build, validate=_isr_validate, body=True, needs_softech=True)


# ── start endpoints (follow / download are the shared /api/export-jobs/<id>/) ────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])      # the kind's own check (runner.start_view) = the old export's
def purchasing_export_job(request):
    return runner.start_view(request, 'purchasing')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def isr_fulfilment_export_job(request):
    return runner.start_view(request, 'isr_fulfilment')
