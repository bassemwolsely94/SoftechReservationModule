"""
apps/tax_invoicing/egs_sheet_views.py — the Invoicer's bulk EGS sheet on «طابور الترميز» (doc 36, batch S3).

  GET  codes/sheet/                      versions, the running/last build, and what a build would add now (view)
  POST codes/sheet/build/                starts a build in the background, 202; 409 while one runs (approve)
  GET  codes/sheet/<n>/download/?kind=   full = the stored workbook · new = only the rows that version wrote (approve)

The seal PC's agent and the live sheet in D:\\invoicer_mini (batch S5, apps/tax_invoicing/egs_agent.py):
  GET  codes/sheet/agent/                the write switch, the agent's last poll and version, the last fetch and its
                                         difference from the latest version, the hold that stands, recent jobs (view)
  POST codes/sheet/agent/fetch/          «اقرأ الملف الحالي»: an egs_fetch job (approve)
  POST codes/sheet/agent/write/          «اكتب الآن» (a preview while the switch is off); {override: true, note}
                                         = «اكتب فوقها» over hand edits, a reason required, audited (approve)
  POST codes/sheet/agent/import/         «استورد التعديلات»: {job, allow_removals} (approve)

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

from core.errors import public_error
from core.permissions import matrix_permission
from core.threads import start_thread

from config.writers import writer_allowed

from . import egs_agent, egs_sheet, services
from .models import TaxAgentFileJob, TaxEgsSheetVersion
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
    try:
        start_thread(egs_sheet.build_thread, args=(request.user, note), name='egs-sheet-build')
    except Exception as exc:    # no thread: the claimed state must not stay "running"
        egs_sheet.fail_start()
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
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


# ── The seal PC's agent (S5) ────────────────────────────────────────────────────────────────────

JOBS_SHOWN = 20
CODES_SHOWN = 500       # itemcodes listed per side of a difference; the counts are always whole
OVERRIDE_NEEDS_REASON = 'اكتب سبب الكتابة فوق التعديلات اليدوية'


def _job_row(j):
    return {'id': j.pk, 'kind': j.kind, 'mode': j.mode, 'status': j.status, 'override': j.override,
            'version': j.version.number if j.version_id else None, 'created_at': j.created_at,
            'finished_at': j.finished_at, 'requested_by': _who(j.requested_by), 'error': j.error,
            'result': _job_summary(j)}


def _job_summary(j):
    """The few result fields the screen shows (never the agent's whole report)."""
    r = j.result or {}
    agent = r.get('agent') if isinstance(r.get('agent'), dict) else {}
    if j.kind == TaxAgentFileJob.KIND_FETCH:
        live = r.get('live') or {}
        return {'coded_rows': live.get('coded_rows'), 'total_rows': live.get('total_rows'),
                'matches_version': r.get('matches_version'), 'hand_edits': r.get('hand_edits'),
                'added': len(r.get('added_vs_latest') or []), 'removed': len(r.get('removed_vs_latest') or []),
                'locked': agent.get('locked')}
    if j.status == TaxAgentFileJob.HELD:
        return {'added': len(r.get('added') or []), 'removed': len(r.get('removed') or [])}
    return {key: agent.get(key) for key in ('written', 'preview', 'would_write', 'live_changed', 'locked',
                                            'backup', 'retries', 'backup_dir_writable') if key in agent}


def _codes(values):
    values = list(values or [])
    return {'count': len(values), 'items': values[:CODES_SHOWN]}


def _held(live, latest):
    """The hold that stands now: the newest write is held, for the latest version, on the fetch that is the live
    state. A later write, version or fetch ends it."""
    newest = TaxAgentFileJob.objects.filter(kind=TaxAgentFileJob.KIND_WRITE).order_by('-id').first()
    if (newest is None or newest.status != TaxAgentFileJob.HELD or latest is None or newest.version_id != latest.pk
            or live is None or live['source'] != 'fetch'
            or (newest.result or {}).get('fetch_job') != live['job'].pk):
        return None
    r = newest.result or {}
    return {'id': newest.pk, 'version': latest.number, 'finished_at': newest.finished_at,
            'added': _codes(r.get('added')), 'removed': _codes(r.get('removed'))}


def _fetch_row(fetch, live, latest):
    if fetch is None:
        return None
    r = fetch.result or {}
    codes = set(r.get('coded_itemcodes') or [])
    removed_now = set(latest.coded_itemcodes if latest else ()) - codes
    current = live is not None and live['source'] == 'fetch' and live['job'].pk == fetch.pk
    has_copy = bool(fetch.fetched_file) and (egs_agent._fetched_dir() / fetch.fetched_file).is_file()
    return {'id': fetch.pk, 'finished_at': fetch.finished_at, 'live': r.get('live') or {},
            'latest': r.get('latest'), 'matches_version': r.get('matches_version'),
            'hand_edits': bool(current and live['hand_edits']), 'current': current, 'has_copy': has_copy,
            'added_vs_latest': _codes(r.get('added_vs_latest')),
            'removed_vs_latest': _codes(r.get('removed_vs_latest')),
            # what an import would drop now, against the latest version as it is today (import_fetched decides)
            'import_removes': len(removed_now),
            'importable': bool(current and has_copy and latest is not None
                               and latest.sha256 != (r.get('live') or {}).get('sha256'))}


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def agent_state(request):
    """{switch, agent: {at, version, outdated}, live, last_fetch, held, jobs, busy, can_approve}. `switch` =
    TAX_EGS_SHEET_AGENT_WRITE_ENABLED (the owner's, config/writers.py): off = every write is a preview."""
    seen = egs_agent.agent_seen()
    live = egs_agent.live_state()
    latest = egs_sheet.latest()
    jobs = list(TaxAgentFileJob.objects.select_related('version', 'requested_by').order_by('-id')[:JOBS_SHOWN])
    version = seen.get('version')
    return Response({
        'switch': writer_allowed(egs_agent.WRITE_FLAG),
        'agent': {'at': seen.get('at'), 'version': version, 'min_version': egs_agent.MIN_AGENT_VERSION,
                  'outdated': not isinstance(version, int) or version < egs_agent.MIN_AGENT_VERSION},
        'live': live and {'source': live['source'], 'job': live['job'].pk, 'hand_edits': live['hand_edits']},
        'last_fetch': _fetch_row(egs_agent.last_fetch(), live, latest),
        'held': _held(live, latest),
        'jobs': [_job_row(j) for j in jobs],
        'busy': TaxAgentFileJob.objects.filter(status__in=TaxAgentFileJob.OPEN).exists(),
        'has_version': latest is not None,
        'can_approve': _can(request, 'approve'),
    })


def _yes(value):
    return value in (True, 'true', '1', 1)


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def agent_fetch(request):
    """«اقرأ الملف الحالي»: an egs_fetch job, or the open one."""
    job = egs_agent.request_fetch(request.user)
    return Response({'job': _job_row(job)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def agent_write(request):
    """«اكتب الآن» (a preview while the switch is off). {job: null} = the live file already is the latest version;
    a held job = the live file has hand edits (import them, or write over them: override + a reason, audited)."""
    override = _yes(request.data.get('override'))
    note = str(request.data.get('note') or '').strip()[:300]
    if override and not note:
        return Response({'detail': OVERRIDE_NEEDS_REASON}, status=status.HTTP_400_BAD_REQUEST)
    try:
        job = egs_agent.request_write(request.user, override=override, note=note)
    except egs_agent.EgsAgentError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'job': job and _job_row(job)})


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def agent_import(request):
    """«استورد التعديلات»: {job, allow_removals}. import_fetched holds every rule (newest fetch only, removals only
    with an explicit yes)."""
    try:
        pk = int(request.data.get('job'))
    except (TypeError, ValueError):
        return Response({'detail': egs_agent.NOT_FETCH}, status=status.HTTP_400_BAD_REQUEST)
    job = get_object_or_404(TaxAgentFileJob, pk=pk)
    try:
        version = egs_agent.import_fetched(request.user, job, allow_removals=_yes(request.data.get('allow_removals')))
    except egs_agent.EgsAgentError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'version': _version_row(version)}, status=status.HTTP_201_CREATED)
