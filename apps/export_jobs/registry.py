"""
apps/export_jobs/registry.py — what each export kind is.

A kind is looked up lazily by its key (the module that defines it is imported on first use), so
this file never imports the apps that export. Add a kind = one line in KINDS + an `ExportKind`
in the exporting app (see apps/purchasing/export_jobs.py).
"""
from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable, Optional

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@dataclass(frozen=True)
class ExportFile:
    data: bytes
    file_name: str
    content_type: str = XLSX
    rows: dict = field(default_factory=dict)       # {sheet: rows written}
    meta: Optional[dict] = None                    # effective filters for the audit entry (None = keep)


@dataclass(frozen=True)
class ExportKind:
    key: str
    label: str
    # allowed(user) -> bool: checked at start, again when the job runs and again at download
    allowed: Callable
    # build(job, user, progress) -> ExportFile; raise runner.JobError(text) for a message the user may see
    build: Callable
    # validate(request) -> None or a DRF Response (refusal); ValueError -> 400 with its text. Cheap only.
    validate: Optional[Callable] = None
    # the stored params come from the JSON body (a POST export) instead of the query string
    body: bool = False
    # reads SOFTECH live: always runs on the in-process thread (the jobs service has no JVM, design §10)
    needs_softech: bool = False
    # an extra kind-specific AuditLog row at download (export_taken is written for every download anyway)
    audit_action: str = ''


# key -> 'module.path:ATTRIBUTE'
KINDS = {
    'pic_analytics': 'apps.pic_analytics.jobs:KIND',
    'purchasing': 'apps.purchasing.export_jobs:PURCHASING',
    'isr_fulfilment': 'apps.purchasing.export_jobs:ISR_FULFILMENT',
}


def get_kind(key) -> ExportKind:
    if key not in KINDS:
        raise KeyError(f'unknown export kind {key!r}')
    module, attr = KINDS[key].split(':')
    return getattr(import_module(module), attr)


def service_kinds():
    """Kinds the jobs service may run (no live SOFTECH read)."""
    return [k for k in KINDS if not get_kind(k).needs_softech]
