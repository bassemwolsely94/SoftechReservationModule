"""
apps/tax_invoicing/egs_sheet_views.py — the Invoicer's bulk EGS sheet on «طابور الترميز» (doc 36, batch S3).

  GET  codes/sheet/                      versions, the running/last build, and what a build would add now (view)
  POST codes/sheet/build/                starts a build in the background, 202; 409 while one runs (approve)
  GET  codes/sheet/<n>/download/?kind=   full = the stored workbook · new = only the rows that version wrote (approve)

The sheet is company-level (one Invoicer file for every branch), seen with tax_invoicing → view. Its download is the
Invoicer's master file, so it needs `approve` and is audited (egs_sheet_download).
"""
import io

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import matrix_permission
from core.threads import start_thread

from . import egs_sheet, services
from .models import TaxEgsSheetVersion
from .views import APPROVER, MODULE, VIEWER, _can

APPROVER_GET = matrix_permission(MODULE, get=('approve',))
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
VERSIONS_SHOWN = 20


def _who(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username


def _version_row(v):
    return {'number': v.number, 'built_at': v.built_at, 'source': v.source, 'built_by': _who(v.built_by),
            'note': v.note, 'coded_rows': v.coded_rows, 'total_rows': v.total_rows, 'added': len(v.added),
            'coded': len(v.coded), 'skipped': v.skipped, 'size': v.size,
            'has_file': (egs_sheet._dir() / v.file_name).is_file()}


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def sheet(request):
    """{versions (newest first), build: the running or last build, pending: {ready, skipped}, can_build}. `pending`
    is what a build would write now (candidates() against the latest version)."""
    versions = list(TaxEgsSheetVersion.objects.select_related('built_by').order_by('-number')[:VERSIONS_SHOWN])
    pending = egs_sheet.candidates() if versions else []
    return Response({
        'versions': [_version_row(v) for v in versions],
        'build': egs_sheet.build_state(),
        'pending': {'ready': sum(1 for c in pending if not c['why']),
                    'skipped': [{'itemcode': c['itemcode'], 'why': c['why']} for c in pending if c['why']]},
        'can_build': _can(request, 'approve'),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def sheet_build(request):
    """Starts a build on a thread (≈100 s on the real sheet) and answers at once; GET codes/sheet/ reports it."""
    note = str(request.data.get('note') or '')[:300]
    if egs_sheet.latest() is None:      # nothing to build from; and no thread is started for nothing
        return Response({'detail': egs_sheet.NO_HELD}, status=status.HTTP_400_BAD_REQUEST)
    if not egs_sheet.claim_build(request.user):
        return Response({'detail': egs_sheet.BUILD_BUSY}, status=status.HTTP_409_CONFLICT)
    start_thread(egs_sheet.build_thread, args=(request.user, note), name='egs-sheet-build')
    return Response({'started': True}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, APPROVER_GET])
def sheet_download(request, number):
    """kind=full: the stored workbook as the Invoicer reads it; kind=new: only the rows this version added or coded.
    Not passed through core/export_safety: this is the Invoicer's input workbook, not a report, and its cells must
    stay exactly as stored (documented exception, doc 36 S3). Audited."""
    kind = request.query_params.get('kind') or 'full'
    if kind not in ('full', 'new'):
        return Response({'detail': 'نوع التنزيل: full أو new'}, status=status.HTTP_400_BAD_REQUEST)
    version = get_object_or_404(TaxEgsSheetVersion, number=number)
    try:
        if kind == 'full':
            data, name = egs_sheet.open_version(version), egs_sheet.DOWNLOAD_NAME
        else:
            data, name = egs_sheet.new_rows_xlsx(version), f'ElRezeiky_Bulk_EGS_Items_v{version.number}_new.xlsx'
    except egs_sheet.SheetError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
    services.audit('egs_sheet_download', actor=request.user, entity='egs_sheet', entity_id=version.number,
                   after={'number': version.number, 'kind': kind, 'sha256': version.sha256 if kind == 'full' else ''})
    return FileResponse(io.BytesIO(data), as_attachment=True, filename=name, content_type=XLSX)
