"""
apps/pic_analytics/jobs.py — the background Excel export (doc 33 §15), on the shared export job.

A 12-month workbook takes longer than nginx's 60 s, so POST export/jobs/ validates the filters and
starts an ExportJob of kind 'pic_analytics' (apps/export_jobs, performance Stage 4). The page polls
the job and downloads the file when it is done; the `pic_analytics_exported` audit entry is
written at download (views.export_job_download). Behaviour is the same as the old PicExportJob:
one active job per user, 48 h retention, a job cut off by a restart reported failed.
"""
from apps.export_jobs import runner
from apps.export_jobs.registry import ExportFile, ExportKind

FAILED_MSG = runner.FAILED_MSG
STALE_MSG = runner.STALE_MSG
KIND_KEY = 'pic_analytics'
params_of = runner.params_of
query_dict = runner.query_dict


def cleanup():
    """Shared housekeeping (every export kind): stale -> failed, > 48 h -> deleted. -> (expired, deleted)."""
    return runner.cleanup()


def file_name_for(f):
    return f'pic-analytics_{f.start.isoformat()}_{f.end.isoformat()}.xlsx'


def _allowed(user):
    from .access import Access
    acc = Access(user)
    return bool(acc.can_view and acc.can_export and acc.profile is not None)


def build(job, user, progress):
    """Rebuilds Access from the requester and the filters from the stored params, exactly like the
    GET export did."""
    from . import export
    from .access import Access
    from .queries.filters import Filters
    acc = Access(user)
    req = runner.replay_request(job, user, KIND)
    f = Filters.from_request(req, acc)
    calls_f = Filters.from_request(req, acc, live=True) if acc.sees_calls_tabs else None
    data, counts = export.build_workbook(f, acc, exported_by=acc.profile.full_name if acc.profile else '',
                                         calls_f=calls_f, progress=progress)
    return ExportFile(data=data, file_name=file_name_for(f), rows=counts, meta=export.filters_dict(f))


KIND = ExportKind(key=KIND_KEY, label='تحليلات العملاء', allowed=_allowed, build=build,
                  audit_action='pic_analytics_exported')
