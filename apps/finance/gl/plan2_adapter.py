"""The only Plan 3 module that touches Plan 2's drafting models.

Everything else in the close code asks these functions, so a Plan 2 change lands here.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from .models import GLDraftRun, GLParty, LedgerEntry, SourceException


@dataclass
class ClosedPeriodChange:
    exception_id: int
    status: str
    original_entry: Optional[LedgerEntry]
    draft_entry_id: Optional[int]
    source_date: object
    group_key: str = ''
    member_source_keys: list = field(default_factory=list)
    proposed_lines: list = field(default_factory=list)


def party_names(codes):
    """GL party code -> name (any status)."""
    if not codes:
        return {}
    return dict(GLParty.objects.filter(code__in=list(codes)).values_list('code', 'name'))


def party_personcodes(codes):
    """GL party code -> SOFTECH personcode; confirmed parties only."""
    if not codes:
        return {}
    return dict(GLParty.objects.filter(code__in=list(codes), status='confirmed')
                .exclude(softech_personcode='').values_list('code', 'softech_personcode'))


def open_exception_count(date_from, date_to):
    return SourceException.objects.filter(
        status='open', source_date__gte=date_from, source_date__lte=date_to).count()


def closed_period_change(exception_id):
    exc = (SourceException.objects.select_related('original_entry')
           .get(pk=exception_id, kind='closed_period_change'))
    detail = exc.detail or {}
    return ClosedPeriodChange(
        exception_id=exc.pk, status=exc.status, original_entry=exc.original_entry,
        draft_entry_id=detail.get('entry_id'), source_date=exc.source_date,
        group_key=detail.get('group_key') or '',
        member_source_keys=list(detail.get('member_source_keys') or []),
        proposed_lines=list(exc.proposed_lines or []))


def mark_exception_resolved(exception_id, *, user, entry):
    """Close the exception once its correction exists; Plan 2's next run covering the
    members' date releases them."""
    exc = SourceException.objects.get(pk=exception_id)
    exc.status = 'resolved'
    exc.resolved_by = user
    exc.resolved_at = timezone.now()
    exc.resolution_note = (f'قيد التصحيح {entry.number or "#%s" % entry.pk}' if entry else '')[:500]
    exc.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
    return exc


def last_draft_run_through(period) -> Optional[datetime]:
    """Finish time of the latest all-types draft run that covered the whole period."""
    run = (GLDraftRun.objects
           .filter(status__in=['success', 'partial'],
                   date_from__lte=period.period_start, date_to__gte=period.period_end)
           .filter(Q(source_types=[]) | Q(source_types__isnull=True))
           .order_by('-started_at', '-id').first())
    if run is None:
        return None
    return run.finished_at or run.started_at
