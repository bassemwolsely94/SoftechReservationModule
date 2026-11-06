"""The only Plan 3 module that touches Plan 2's drafting models.

Everything else in the close code asks these functions, so a Plan 2 change lands here.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from .models import GLDraftRun, GLParty, GLSourceDoc, LedgerEntry, SourceException


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
    source_type: str = ''
    book: str = 'general'


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


def closed_period_change(exception_id, *, for_update=False):
    rows = SourceException.objects.select_related('original_entry', 'source_doc__rule')
    if for_update:   # the row only: the joined FKs are nullable
        rows = rows.select_for_update(of=('self',))
    exc = rows.get(pk=exception_id, kind='closed_period_change')
    detail = exc.detail or {}
    rule = exc.source_doc.rule
    return ClosedPeriodChange(
        exception_id=exc.pk, status=exc.status, original_entry=exc.original_entry,
        draft_entry_id=detail.get('entry_id'), source_date=exc.source_date,
        group_key=detail.get('group_key') or '',
        member_source_keys=list(detail.get('member_source_keys') or []),
        proposed_lines=list(exc.proposed_lines or []),
        source_type=exc.source_doc.source_type, book=rule.book if rule else 'general')


def release_held_movers(exc):
    """`exc` (a closed_period_change) is ending. A listed member that moved to another group and
    was held there (holder_busy) has no open row left, which the engine reads as "finance
    decided": it goes back to 'new', unlinked from this group's entry, so the next run covering
    its date raises its own group. holder_busy means that group never got a row, so a group with
    a row in any status is not touched: it already has its own decision."""
    detail = exc.detail or {}
    movers = GLSourceDoc.objects.filter(
        source_key__in=list(detail.get('member_source_keys') or []), status='exception',
    ).exclude(group_key__in=['', detail.get('group_key') or ''])
    for doc in movers:
        if not SourceException.objects.filter(kind='closed_period_change',
                                              detail__group_key=doc.group_key).exists():
            GLSourceDoc.objects.filter(pk=doc.pk).update(status='new', entry=None)


def _settle_members(exc, entry):
    """`exc` is ending: the listed members still in its group become group members again, so the
    next rebuild counts them; a second change must not propose only the doc that changed.
    With no entry to sit on they are 'skipped': 'drafted' without a live entry would be retried at
    once, 'skipped' keeps its group_key, stays quiet and still counts in the rebuild."""
    detail = exc.detail or {}
    GLSourceDoc.objects.filter(
        source_key__in=list(detail.get('member_source_keys') or []), status='exception',
        group_key=detail.get('group_key') or '',
    ).exclude(group_key='').update(status='drafted' if entry else 'skipped', entry=entry)


def closed_change_ignored(exc):
    """«تجاهل» on a closed_period_change: finance accepts the old figure until the next change.
    Quiet until then: a member back on a live entry with an unchanged hash is not retried."""
    gk = (exc.detail or {}).get('group_key') or ''
    release_held_movers(exc)
    _settle_members(exc, LedgerEntry.objects.filter(source_key=gk, status__in=('draft', 'approved')).first()
                    if gk else None)


def mark_exception_resolved(exception_id, *, user, entry):
    """Close the exception once its correction exists; the members sit on the group's entry (the
    original, or the late document itself)."""
    exc = SourceException.objects.select_related('original_entry').get(pk=exception_id)
    release_held_movers(exc)
    _settle_members(exc, exc.original_entry or entry)
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
