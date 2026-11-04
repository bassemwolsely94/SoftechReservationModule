"""Draft-now endpoints (Plan 2 / Task 7) - mounted under /api/finance/gl/drafting/.

POST run/ starts a background run (202 {run_id}; 409 when another run is active); GET runs/ and
runs/{id}/ feed the ProgressBar. All-branch users only, RBAC module ``ledger``.
"""
import datetime
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.finance.models import GLDraftRun
from core.threads import start_thread

from . import drafting
from .views import VIEW, _perms

logger = logging.getLogger(__name__)

CREATE = _perms(post=('create',))
MAX_SPAN_DAYS = 400


def _bad(detail):
    return Response({'code': 'bad_input', 'detail': detail}, status=status.HTTP_400_BAD_REQUEST)


def _run_json(r):
    return {'id': r.pk, 'status': r.status, 'date_from': r.date_from.isoformat(),
            'date_to': r.date_to.isoformat(), 'source_types': r.source_types,
            'triggered_by': r.triggered_by, 'counts': r.counts, 'detail': r.detail,
            'started_at': r.started_at.isoformat() if r.started_at else None,
            'finished_at': r.finished_at.isoformat() if r.finished_at else None}


def _background(run_id, date_from, date_to, source_types):
    run = GLDraftRun.objects.get(pk=run_id)
    try:
        drafting.draft_range(date_from, date_to, source_types=source_types, run=run)
    except Exception:   # draft_range records its own failures; last line of defence
        logger.exception('gl draft-now run %s crashed', run_id)
        GLDraftRun.objects.filter(pk=run_id, status='running').update(status='failed')


@api_view(['POST'])
@permission_classes(CREATE)
def drafting_run(request):
    try:
        d1 = datetime.date.fromisoformat(str(request.data.get('date_from') or '')[:10])
        d2 = datetime.date.fromisoformat(str(request.data.get('date_to') or '')[:10])
    except ValueError:
        return _bad('التاريخ غير صحيح (YYYY-MM-DD)')
    if d2 < d1:
        return _bad('تاريخ النهاية قبل البداية')
    if (d2 - d1).days > MAX_SPAN_DAYS:
        return _bad('المدة أطول من المسموح')
    types = request.data.get('source_types') or []
    if not isinstance(types, list) or any(t not in drafting.SOURCE_ORDER for t in types):
        return _bad('نوع مصدر غير معروف')
    try:
        run = drafting.start_run(triggered_by=f'user:{request.user.pk}', date_from=d1, date_to=d2,
                                 source_types=types)
    except drafting.DraftBusy:
        return Response({'code': 'busy', 'detail': 'هناك عملية ترحيل جارية الآن'},
                        status=status.HTTP_409_CONFLICT)
    start_thread(_background, args=(run.pk, d1, d2, types or None), name=f'gl-draft-{run.pk}')
    return Response({'run_id': run.pk}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes(VIEW)
def drafting_runs(request):
    try:
        limit = max(1, min(int(request.query_params.get('limit') or 10), 100))
    except ValueError:
        limit = 10
    return Response({'results': [_run_json(r) for r in GLDraftRun.objects.all()[:limit]]})


@api_view(['GET'])
@permission_classes(VIEW)
def drafting_run_detail(request, pk):
    r = GLDraftRun.objects.filter(pk=pk).first()
    if r is None:
        return Response({'code': 'not_found', 'detail': 'التشغيل غير موجود'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_run_json(r))
