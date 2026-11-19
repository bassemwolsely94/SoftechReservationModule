"""
apps/export_jobs/runner.py — start, run and tidy export jobs (performance Stage 4).

Start (a web request): validate cheaply, save a queued ExportJob, hand it to a worker and answer
202 — no file work in the request, so it returns in well under a second.

Who runs it:
  • the jobs service (`manage.py run_export_jobs`, deploy/elrezeiky-jobs.service) when
    EXPORT_JOBS_RUNNER=service: it claims queued jobs with SELECT … FOR UPDATE SKIP LOCKED,
    one at a time, in its own process (no JVM);
  • otherwise (dev, office, or a kind that reads SOFTECH live) a thread in the web process, as
    PicExportJob always did (core.threads.start_thread keeps the requester's context for the
    SOFTECH gate).

A job with no progress for STALE_AFTER is reported failed (the process that ran it restarted —
neither a thread nor the service resumes a half-built file). Jobs older than KEEP_FOR are deleted
with their bytes, on every start and nightly.
"""
import logging
import re
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import unquote

from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.functions import Coalesce
from django.http import QueryDict
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from .models import ExportJob
from .registry import get_kind, service_kinds

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)
KEEP_FOR = timedelta(hours=48)
FAILED_MSG = 'تعذّر إنشاء الملف — حاول مرة أخرى'
STALE_MSG = 'توقّف إنشاء الملف (أُعيد تشغيل السيرفر) — حاول مرة أخرى'
START_MSG = 'بدء التصدير…'


class JobError(Exception):
    """A failure whose text the user may see (a refusal the old direct export answered with)."""


# ── params ───────────────────────────────────────────────────────────────────────────────────────

def params_of(query_params):
    """The raw query params as JSON: {key: [values]} (keeps repeated keys)."""
    return {k: list(v) for k, v in query_params.lists()}


def query_dict(params):
    qd = QueryDict(mutable=True)
    for k, vals in (params or {}).items():
        qd.setlist(k, [str(v) for v in (vals if isinstance(vals, list) else [vals])])
    return qd


def replay_request(job, user, kind=None):
    """A stand-in for the request that started the job: the same query string or body, the same
    user. Export builders only read GET / query_params / data / user."""
    kind = kind or get_kind(job.kind)
    if kind.body:
        qd = QueryDict()
        return SimpleNamespace(GET=qd, query_params=qd, data=dict(job.params or {}), user=user, method='POST')
    qd = query_dict(job.params)
    return SimpleNamespace(GET=qd, query_params=qd, data={}, user=user, method='GET')


def _disposition_name(value):
    star = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    if star:
        return unquote(star.group(1))
    plain = re.search(r'filename="?([^";]+)"?', value, re.I)
    return plain.group(1) if plain else ''


def file_from_response(resp, default_name=''):
    """(bytes, file name, content type) from the HttpResponse an old export function returned.
    A refusal (4xx/5xx, a DRF Response) becomes a JobError carrying its message."""
    from django.http import StreamingHttpResponse
    if isinstance(resp, Response) or resp.status_code >= 400:
        data = getattr(resp, 'data', None)
        detail = str(data.get('detail') or data.get('error') or '') if isinstance(data, dict) else ''
        raise JobError(detail or FAILED_MSG)
    if isinstance(resp, StreamingHttpResponse):
        body = b''.join(c if isinstance(c, bytes) else str(c).encode('utf-8') for c in resp.streaming_content)
    else:
        body = resp.content
    name = _disposition_name(resp.get('Content-Disposition') or '') or default_name
    return body, name, (resp.get('Content-Type') or '')


# ── housekeeping ─────────────────────────────────────────────────────────────────────────────────

def expire_stale(qs=None):
    """Report every job with no progress for STALE_AFTER as failed. Returns how many."""
    qs = ExportJob.objects.all() if qs is None else qs
    now = timezone.now()
    pks = list(qs.filter(status__in=ExportJob.ACTIVE)
               .annotate(last_seen=Coalesce('heartbeat_at', 'started_at', 'created_at'))
               .filter(last_seen__lt=now - STALE_AFTER).values_list('pk', flat=True))
    if not pks:
        return 0
    return ExportJob.objects.filter(pk__in=pks, status__in=ExportJob.ACTIVE).update(
        status=ExportJob.FAILED, error=STALE_MSG, finished_at=now)


def refresh_if_stale(job):
    """For a job being read: apply the stale rule to it, then return it fresh."""
    if job.status in ExportJob.ACTIVE and expire_stale(ExportJob.objects.filter(pk=job.pk)):
        job.refresh_from_db()
    return job


def cleanup():
    """Expire stale jobs, delete jobs older than KEEP_FOR (their file included). -> (expired, deleted)."""
    expired = expire_stale()
    deleted, _ = ExportJob.objects.filter(created_at__lt=timezone.now() - KEEP_FOR).delete()
    return expired, deleted


# ── start ────────────────────────────────────────────────────────────────────────────────────────

def runner_mode():
    return 'service' if str(getattr(settings, 'EXPORT_JOBS_RUNNER', '') or '').lower() == 'service' else 'thread'


def job_json(job):
    return {'id': job.pk, 'kind': job.kind, 'status': job.status, 'status_label': job.get_status_display(),
            'progress_pct': job.progress_pct, 'progress_msg': job.progress_msg, 'file_name': job.file_name,
            'error': job.error, 'rows': job.rows, 'created_at': job.created_at,
            'started_at': job.started_at, 'finished_at': job.finished_at}


def start(kind_key, profile, params, meta=None):
    """Save a queued job for `profile` and hand it to a worker. -> (job, created). `created` is
    False when one of the same kind is already queued/running for this user (that one is returned)."""
    kind = get_kind(kind_key)
    try:
        cleanup()                           # opportunistic: stale -> failed, > 48 h -> deleted
    except Exception:                       # housekeeping never blocks an export
        logger.exception('export job cleanup failed')
    active = ExportJob.objects.defer('data').filter(requested_by=profile, kind=kind_key,
                                                    status__in=ExportJob.ACTIVE)
    running = active.first()
    if running is None:
        try:
            with transaction.atomic():
                job = ExportJob.objects.create(kind=kind_key, requested_by=profile, params=params or {},
                                               meta=meta or {})
        except IntegrityError:              # two clicks at once: the constraint lets one through
            running = active.first()
            if running is None:
                raise
    if running is not None:
        return running, False
    dispatch(job, kind)
    return job, True


def dispatch(job, kind=None):
    """Thread now, or leave it queued for the jobs service. -> 'thread' | 'service'."""
    kind = kind or get_kind(job.kind)
    if runner_mode() == 'service' and not kind.needs_softech:
        return 'service'
    from core.threads import start_thread
    ExportJob.objects.filter(pk=job.pk).update(worker='thread')
    start_thread(run_job, args=(job.pk,), name=f'export-{job.kind}-{job.pk}')
    return 'thread'


def start_response(job, created):
    if not created:
        return Response({'detail': 'يوجد تصدير جارٍ بالفعل', 'id': job.pk, 'status': job.status},
                        status=status.HTTP_409_CONFLICT)
    return Response({'id': job.pk, 'status': job.status}, status=status.HTTP_202_ACCEPTED)


def start_view(request, kind_key):
    """The whole POST <export>/jobs/ answer for a kind: permission, cheap validation, start."""
    kind = get_kind(kind_key)
    profile = getattr(request.user, 'staff_profile', None)
    if profile is None or not kind.allowed(request.user):
        return Response({'detail': 'غير مصرح لك.'}, status=status.HTTP_403_FORBIDDEN)
    if kind.validate is not None:
        try:
            refusal = kind.validate(request)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if refusal is not None:
            return refusal
    params = dict(request.data) if kind.body else params_of(request.query_params)
    return start_response(*start(kind_key, profile, params))


# ── run ──────────────────────────────────────────────────────────────────────────────────────────

def _mark_running(pk, worker):
    now = timezone.now()
    ExportJob.objects.filter(pk=pk).update(status=ExportJob.RUNNING, worker=worker, started_at=now,
                                           heartbeat_at=now, progress_pct=1, progress_msg=START_MSG)


def _claim(job_id, worker):
    """queued -> running for this worker; False when another worker has it / it is no longer queued."""
    with transaction.atomic():
        row = (ExportJob.objects.select_for_update(skip_locked=True).only('pk')
               .filter(pk=job_id, status=ExportJob.QUEUED).first())
        if row is None:
            return False
        _mark_running(job_id, worker)
    return True


def claim_next(worker='service'):
    """The oldest queued job the service may run, claimed (SKIP LOCKED: two runners never take the
    same one). -> its id or None."""
    with transaction.atomic():
        row = (ExportJob.objects.select_for_update(skip_locked=True).only('pk')
               .filter(status=ExportJob.QUEUED, kind__in=service_kinds()).order_by('created_at').first())
        if row is None:
            return None
        _mark_running(row.pk, worker)
    return row.pk


def run_job(job_id, worker='thread'):
    """Claim and run one job (the thread entry point). Never raises."""
    try:
        if _claim(job_id, worker):
            execute(job_id)
    except Exception:                       # the claim itself failed; nothing to record
        logger.exception('export job %s could not start', job_id)
    finally:
        # a worker thread owns its connection: release it (never inside a test's atomic block, where
        # the worker runs inline on the test connection)
        if not connection.in_atomic_block:
            close_old_connections()
            connection.close()


def execute(job_id):
    """Build the file of a claimed (running) job and store it. Never raises."""
    try:
        job = ExportJob.objects.select_related('requested_by__user').defer('data').get(pk=job_id)
        kind = get_kind(job.kind)
        user = job.requested_by.user
        if not kind.allowed(user):
            raise PermissionError('export access revoked before the job ran')

        def progress(pct, msg):
            ExportJob.objects.filter(pk=job_id, status=ExportJob.RUNNING).update(
                progress_pct=max(1, min(99, int(pct))), progress_msg=str(msg)[:120],
                heartbeat_at=timezone.now())

        out = kind.build(job, user, progress)
        fields = dict(status=ExportJob.DONE, data=out.data, rows=out.rows or {}, file_name=out.file_name[:200],
                      content_type=(out.content_type or '')[:120], progress_pct=100, progress_msg='الملف جاهز',
                      finished_at=timezone.now())
        if out.meta is not None:
            fields['meta'] = out.meta
        ExportJob.objects.filter(pk=job_id, status=ExportJob.RUNNING).update(**fields)
    except JobError as exc:
        _fail(job_id, str(exc) or FAILED_MSG)
    except Exception:                       # the user gets a safe message, the log the traceback
        logger.exception('export job %s failed', job_id)
        _fail(job_id, FAILED_MSG)


def _fail(job_id, msg):
    try:
        ExportJob.objects.filter(pk=job_id, status__in=ExportJob.ACTIVE).update(
            status=ExportJob.FAILED, error=msg[:255], finished_at=timezone.now())
    except Exception:                     
        logger.exception('export job %s: could not record the failure', job_id)


def fail_orphans(worker='service'):
    """At service start: the jobs it was running were cut off by the restart -> failed."""
    return ExportJob.objects.filter(status=ExportJob.RUNNING, worker=worker).update(
        status=ExportJob.FAILED, error=STALE_MSG, finished_at=timezone.now())
