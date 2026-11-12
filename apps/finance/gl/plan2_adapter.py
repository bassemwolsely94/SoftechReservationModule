"""The only Plan 3 module that touches Plan 2's drafting models.

Everything else in the close code asks these functions, so a Plan 2 change lands here.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLog

from .ledger import _audit
from .models import (GLDraftRun, GLParty, GLSourceDoc, GLSourceMap, LedgerEntry, PostingRule,
                     SourceException)

MANUAL_IMPORT_SOURCE = 'manual_import'
MIXED_MANUAL_KIND = 'mixed_manual_entry'
MIXED_MANUAL_MESSAGE = 'قيد من يومية المالية على حسابات يدوية وحسابات من سوفتيك — يتضم بكل أسطره أو يتجاهل بسبب'
MIXED_MANUAL_RESOLVED = 'اتضم من يومية المالية بكل أسطره'
LATE_DOCUMENT_DRAFTED = 'gl_late_document_drafted'   # corrections.post_late_document
NOTHING_TO_CORRECT = 'مفيش فرق يتصحح بعد إلغاء التصحيح'
CORRECTION_KEY = re.compile(r'#corr:exc(\d+)$')   # corrections.post_late_correction, from an exception


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
    lines_stale: bool = False


def party_names(codes, party_type=None):
    """GL party code -> name (any status). Codes are only unique per type: pass `party_type`
    whenever the caller knows it."""
    if not codes:
        return {}
    qs = GLParty.objects.filter(code__in=list(codes))
    if party_type:
        qs = qs.filter(party_type=party_type)
    return dict(qs.values_list('code', 'name'))


def party_personcodes(codes, party_type=None):
    """GL party code -> SOFTECH personcode; confirmed parties only."""
    if not codes:
        return {}
    qs = GLParty.objects.filter(code__in=list(codes), status='confirmed').exclude(softech_personcode='')
    if party_type:
        qs = qs.filter(party_type=party_type)
    return dict(qs.values_list('code', 'softech_personcode'))


def party_recon_parties(codes, party_type):
    """GL party code -> its linked ReconParty (parties with a link only)."""
    if not codes:
        return {}
    return {p.code: p.recon_party for p in GLParty.objects
            .filter(code__in=list(codes), party_type=party_type, recon_party__isnull=False)
            .select_related('recon_party')}


def party_codes_with_recon(party_type):
    """Codes of every party of one type that has a ReconParty link."""
    return list(GLParty.objects.filter(party_type=party_type, recon_party__isnull=False)
                .values_list('code', flat=True))


def all_party_personcodes(party_type):
    """GL party code -> SOFTECH personcode for every confirmed party of one type."""
    return dict(GLParty.objects.filter(party_type=party_type, status='confirmed')
                .exclude(softech_personcode='').values_list('code', 'softech_personcode'))


def open_exception_count(date_from, date_to):
    return SourceException.objects.filter(
        status='open', source_date__gte=date_from, source_date__lte=date_to).count()


def open_late_change_count(before) -> int:
    """Open closed_period_change rows dated before `before`: their month closed already, so its checklist can no
    longer stop on them."""
    return SourceException.objects.filter(status='open', kind='closed_period_change', source_date__lt=before).count()


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
        source_type=exc.source_doc.source_type, book=rule.book if rule else 'general',
        lines_stale=bool(detail.get('lines_stale')))


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
    original while it stands, else the late document itself)."""
    exc = SourceException.objects.select_related('original_entry').get(pk=exception_id)
    release_held_movers(exc)
    original = exc.original_entry
    _settle_members(exc, original if original is not None and original.status == 'approved' else entry)
    exc.status = 'resolved'
    exc.resolved_by = user
    exc.resolved_at = timezone.now()
    exc.resolution_note = (f'قيد التصحيح {entry.number or "#%s" % entry.pk}' if entry else '')[:500]
    exc.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
    return exc


def _undone_exception_id(entry_id, source_key):
    """The exception this entry was posted from: a correction says so in its key, a late document in its audit row."""
    found = CORRECTION_KEY.search(source_key or '')
    if found:
        return int(found[1])
    row = (AuditLog.objects.filter(action=LATE_DOCUMENT_DRAFTED, model_name='LedgerEntry', object_id=str(entry_id))
           .order_by('-id').first())
    return (row.extra or {}).get('exception_id') if row else None


def late_posting_undone(entry_id, source_key, *, user):
    """A correction or late document is gone outside the engine (a draft deleted, an approved one reversed), called
    once its entry no longer counts. The SOFTECH change is unposted again and nothing else remembers it: the members
    look settled, and the scheduled window never covers a closed month. So in the caller's transaction the group gets
    its open row back, proposing what its documents say now (each keeps the amounts last read): a row's own lines may
    be older than a later correction. A group whose ledger already says that has nothing to correct and gets no row.
    A group with an open row keeps that one. A holder doc busy with another group's row sends the members back to
    'new', for the next run covering them. Lines that no longer build leave the row refusing to post until a redraft."""
    exception_id = _undone_exception_id(entry_id, source_key)
    if exception_id is None:
        return None
    exc = (SourceException.objects.select_for_update()
           .filter(pk=exception_id, kind='closed_period_change', status='resolved').first())
    if exc is None:
        return None
    from . import drafting   # these two import this module
    from .corrections import effective_lines, net_lines

    detail = exc.detail or {}
    gk = detail.get('group_key') or ''
    lines, keys = drafting.group_proposal(gk)
    live = LedgerEntry.objects.filter(source_key=gk, status__in=('draft', 'approved')).first()
    settled = lines is not None and net_lines(lines) == (effective_lines(live, include_drafts=True) if live else {})
    rows = SourceException.objects.filter(status='open', kind='closed_period_change')
    current = rows.filter(detail__group_key=gk).order_by('pk').first()
    members = GLSourceDoc.objects.filter(source_key__in=keys or list(detail.get('member_source_keys') or []),
                                         group_key=gk).exclude(group_key='').exclude(status='vanished')
    row, state = current or exc, 'kept' if current else 'reopened'
    old = {'status': row.status, 'resolved_by': row.resolved_by_id, 'resolution_note': row.resolution_note}
    if settled:
        state = 'nothing_to_correct'
        members.update(status='drafted' if live else 'skipped', entry=live)
        if current is not None:
            current.status, current.resolved_by, current.resolved_at = 'resolved', user, timezone.now()
            current.resolution_note = NOTHING_TO_CORRECT
            current.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
    elif current is None and rows.filter(source_doc_id=exc.source_doc_id).exists():
        state = 'members_new'
        members.update(status='new')
    else:
        row_detail = {key: value for key, value in (row.detail or {}).items() if key != 'lines_stale'}
        if lines is None:
            row_detail['lines_stale'] = True
        else:
            row.proposed_lines = lines
            row_detail['member_source_keys'] = keys
        row.detail = row_detail
        row.source_date = row.source_doc.doc_date
        row.status, row.resolved_by, row.resolved_at, row.resolution_note = 'open', None, None, ''
        row.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note', 'detail', 'proposed_lines',
                                'source_date'])
        members.exclude(status='exception').update(status='exception')
    _audit('gl_late_change_reopened', user=user, obj=row, old_data=old,
           new_data={'status': row.status, 'state': state, 'proposed_lines': row.proposed_lines},
           extra={'undone_entry_id': entry_id, 'exception_id': exc.pk, 'group_key': gk})
    return row


def softech_fed_account_codes() -> set:
    """Accounts the drafting engine posts to: static lines of active posting rules + every source map
    (a rule's mapped line lands on an account of a map)."""
    codes = set(GLSourceMap.objects.values_list('account__code', flat=True))
    for lines in PostingRule.objects.filter(is_active=True, action='post').values_list('lines', flat=True):
        codes.update(str(ln['account']) for ln in lines or () if ln.get('account'))
    return codes


def parked_manual_keys() -> set:
    return set(GLSourceDoc.objects.filter(source_type=MANUAL_IMPORT_SOURCE).values_list('source_key', flat=True))


def park_mixed_manual_entry(*, key, entry_date, branch_code, book, description, lines, user) -> str:
    """A mixed group of finance's journal waits in the exceptions inbox, and so blocks its month's
    close. -> 'created', or the status of the row it already has: a group finance ignored or included
    is not raised again."""
    with transaction.atomic():
        doc, _ = GLSourceDoc.objects.get_or_create(source_key=key, defaults={
            'source_type': MANUAL_IMPORT_SOURCE, 'doc_date': entry_date, 'branch_code': branch_code,
            'amounts': {}, 'attrs': {'book': book, 'description': description},
            'content_hash': hashlib.sha256(key.encode('utf-8')).hexdigest(), 'status': 'exception'})
        existing = (SourceException.objects.filter(source_doc=doc, kind=MIXED_MANUAL_KIND)
                    .values_list('status', flat=True).first())
        if existing:
            return existing
        message = f'{MIXED_MANUAL_MESSAGE}: {description}' if description else MIXED_MANUAL_MESSAGE
        exc = SourceException.objects.create(
            source_doc=doc, kind=MIXED_MANUAL_KIND, source_date=entry_date, message=message[:500],
            proposed_lines=lines, detail={'group_key': key})
        _audit('gl_manual_entry_parked', user=user, obj=exc,
               new_data={'status': 'open', 'source_key': key, 'date': entry_date.isoformat(),
                         'lines': lines})
    return 'created'


def settle_parked_manual_entry(key, *, entry, user):
    """The group now has its draft: the doc sits on it and an open exception resolves. An ignored
    one keeps finance's decision on record."""
    doc = GLSourceDoc.objects.select_for_update().get(source_key=key)
    GLSourceDoc.objects.filter(pk=doc.pk).update(status='drafted', entry=entry)
    rows = SourceException.objects.select_for_update().filter(source_doc=doc, kind=MIXED_MANUAL_KIND, status='open')
    for exc in rows:
        exc.status, exc.resolved_by, exc.resolved_at = 'resolved', user, timezone.now()
        exc.resolution_note = MIXED_MANUAL_RESOLVED
        exc.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
        _audit('gl_manual_exception_resolved', user=user, obj=exc, old_data={'status': 'open'},
               new_data={'status': 'resolved', 'source_key': key, 'entry_id': entry.pk})


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
