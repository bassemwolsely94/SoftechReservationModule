"""
apps/pic_analytics/jobs.py — the background Excel export (doc 33 §15).

A 12-month workbook takes longer than nginx's 60 s, so POST export/jobs/ validates the filters, saves a
PicExportJob and builds the workbook on a thread (core.threads.start_thread). The page polls the job and
downloads the file when it is done; the audit entry is written at download (views.export_job_download).

Housekeeping: a queued/running job older than STALE_AFTER is reported failed (the process that ran it
restarted — a thread does not survive that); jobs older than KEEP_FOR are deleted with their bytes,
on every POST and nightly after build_pic_facts.
"""
import logging
from datetime import timedelta
from types import SimpleNamespace

from django.db import close_old_connections, connection
from django.http import QueryDict
from django.utils import timezone

from .models import PicExportJob

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)
KEEP_FOR = timedelta(hours=48)
FAILED_MSG = 'تعذّر إنشاء الملف — حاول مرة أخرى'
STALE_MSG = 'توقّف إنشاء الملف (أُعيد تشغيل السيرفر) — حاول مرة أخرى'


def params_of(query_params):
    """The raw query params as JSON: {key: [values]} (keeps repeated keys)."""
    return {k: list(v) for k, v in query_params.lists()}


def query_dict(params):
    qd = QueryDict(mutable=True)
    for k, vals in (params or {}).items():
        qd.setlist(k, [str(v) for v in (vals if isinstance(vals, list) else [vals])])
    return qd


def expire_stale(qs=None):
    """Report every queued/running job older than STALE_AFTER as failed. Returns how many."""
    qs = PicExportJob.objects.all() if qs is None else qs
    now = timezone.now()
    return qs.filter(status__in=PicExportJob.ACTIVE, created_at__lt=now - STALE_AFTER).update(
        status=PicExportJob.FAILED, error=STALE_MSG, finished_at=now)


def refresh_if_stale(job):
    """For a job being read: apply the stale rule to it, then return it fresh."""
    if job.status in PicExportJob.ACTIVE and expire_stale(PicExportJob.objects.filter(pk=job.pk)):
        job.refresh_from_db()
    return job


def cleanup():
    """Expire stale jobs, delete jobs older than KEEP_FOR (their file included). -> (expired, deleted)."""
    expired = expire_stale()
    deleted, _ = PicExportJob.objects.filter(created_at__lt=timezone.now() - KEEP_FOR).delete()
    return expired, deleted


def file_name_for(f):
    return f'pic-analytics_{f.start.isoformat()}_{f.end.isoformat()}.xlsx'


def run_job(job_id):
    """The worker. Rebuilds Access from the requester and the filters from the stored params, exactly like
    the GET export did, and writes progress as it goes. Never raises."""
    from .access import Access
    from .export import build_workbook, filters_dict
    from .queries.filters import Filters
    try:
        job = PicExportJob.objects.select_related('requested_by__user').get(pk=job_id)
        if job.status != PicExportJob.QUEUED:
            return
        PicExportJob.objects.filter(pk=job_id).update(status=PicExportJob.RUNNING, started_at=timezone.now(),
                                                      progress_pct=1, progress_msg='بدء التصدير…')
        acc = Access(job.requested_by.user)
        if not acc.can_view or not acc.can_export:
            raise PermissionError('export access revoked before the job ran')
        req = SimpleNamespace(GET=query_dict(job.params))
        f = Filters.from_request(req, acc)
        calls_f = Filters.from_request(req, acc, live=True) if acc.sees_calls_tabs else None

        def progress(pct, msg):
            PicExportJob.objects.filter(pk=job_id, status=PicExportJob.RUNNING).update(
                progress_pct=max(1, min(99, int(pct))), progress_msg=msg[:120])

        data, counts = build_workbook(f, acc, exported_by=acc.profile.full_name if acc.profile else '',
                                      calls_f=calls_f, progress=progress)
        PicExportJob.objects.filter(pk=job_id, status=PicExportJob.RUNNING).update(
            status=PicExportJob.DONE, data=data, rows=counts, filters=filters_dict(f), file_name=file_name_for(f),
            progress_pct=100, progress_msg='الملف جاهز', finished_at=timezone.now())
    except Exception:                       # noqa: BLE001 — the user gets a safe message, the log the traceback
        logger.exception('pic analytics export job %s failed', job_id)
        try:
            PicExportJob.objects.filter(pk=job_id, status__in=PicExportJob.ACTIVE).update(
                status=PicExportJob.FAILED, error=FAILED_MSG, finished_at=timezone.now())
        except Exception:                   # noqa: BLE001
            logger.exception('pic analytics export job %s: could not record the failure', job_id)
    finally:
        # a worker thread owns its connection: release it (never inside a test's atomic block, where the
        # worker runs inline on the test connection)
        if not connection.in_atomic_block:
            close_old_connections()
            connection.close()
