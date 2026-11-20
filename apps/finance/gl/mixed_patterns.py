"""Decide parked mixed journal groups by pattern (spec 2026-11-20-gl-mixed-patterns-design.md).

A finance journal group with both manual and SOFTECH-fed accounts waits in the exceptions inbox as
`mixed_manual_entry`. Its pattern is the book + its manual accounts + its SOFTECH-fed accounts (the
link account left out), read from the lines stored on the exception. An accountant imports a whole
pattern as drafts or ignores it with a reason. Nothing here approves, and nothing reaches SOFTECH.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.models import LedgerEntry, SourceException

from . import parties, plan2_adapter
from .ledger import LedgerError, _audit, save_draft
from .manual_import import _link_accounts

MAX_NOTE = 2000
SAMPLES = 3

MESSAGES = {
    'bad_decision': 'القرار لازم يكون استيراد أو تجاهل.',
    'note_required': 'اكتب سبب التجاهل.',
    'count_changed': 'عدد القيود في النمط ده اتغيّر من ساعة ما فتحت الشاشة — راجع تاني.',
    'unknown_pattern': 'مفيش قيود مفتوحة على النمط ده.',
}


class PatternError(Exception):
    def __init__(self, code: str):
        self.code = code
        self.message = MESSAGES.get(code, code)
        super().__init__(f'{code}: {self.message}')


def pattern_key(book: str, manual, softech) -> str:
    return f'{book}|{",".join(manual)}|{",".join(softech)}'


def _open_rows():
    return (SourceException.objects.filter(kind=plan2_adapter.MIXED_MANUAL_KIND, status='open')
            .select_related('source_doc').order_by('source_date', 'pk'))


def _split(lines, fed, links):
    codes = {str(ln.get('account_code')) for ln in lines or () if ln.get('account_code')} - links
    return sorted(codes - fed), sorted(codes & fed)


def _pattern_of(exc, fed, links) -> tuple:
    manual, softech = _split(exc.proposed_lines, fed, links)
    return (exc.source_doc.attrs or {}).get('book', ''), manual, softech


def _debit(lines) -> Decimal:
    return sum((Decimal(str(ln.get('debit') or 0)) for ln in lines or ()), Decimal('0.00'))


def list_patterns() -> list:
    fed, links = plan2_adapter.softech_fed_account_codes(), _link_accounts()
    out = {}
    for exc in _open_rows():
        book, manual, softech = _pattern_of(exc, fed, links)
        key = pattern_key(book, manual, softech)
        p = out.setdefault(key, {'pattern': key, 'book': book, 'manual_accounts': manual,
                                 'softech_accounts': softech, 'count': 0, 'debit': Decimal('0.00'),
                                 'date_from': exc.source_date, 'date_to': exc.source_date, 'samples': []})
        p['count'] += 1
        p['debit'] += _debit(exc.proposed_lines)
        p['date_from'] = min(p['date_from'], exc.source_date)
        p['date_to'] = max(p['date_to'], exc.source_date)
        desc = (exc.source_doc.attrs or {}).get('description', '')
        if desc and desc not in p['samples'] and len(p['samples']) < SAMPLES:
            p['samples'].append(desc)
    return sorted(out.values(), key=lambda p: (-p['count'], p['pattern']))


def _lines(stored) -> list:
    """The stored (canonical JSON) lines back to what `save_draft` takes."""
    out = []
    for ln in stored:
        due = ln.get('due_date')
        out.append({**ln, 'debit': Decimal(str(ln.get('debit') or 0)), 'credit': Decimal(str(ln.get('credit') or 0)),
                    'due_date': datetime.date.fromisoformat(due) if due else None})
    return out


def _import_one(exc, user, branches) -> str:
    """-> 'imported' | 'already_imported'. A LedgerError rolls back this group only."""
    doc = exc.source_doc
    with transaction.atomic():
        live = LedgerEntry.objects.filter(source_key=doc.source_key, status__in=('draft', 'approved')).first()
        if live is not None:
            plan2_adapter.settle_parked_manual_entry(doc.source_key, entry=live, user=user)
            return 'already_imported'
        attrs = doc.attrs or {}
        entry = save_draft(user=user, entry_date=doc.doc_date, description=(attrs.get('description') or '')[:500],
                           lines=_lines(exc.proposed_lines), book=attrs.get('book') or 'general',
                           branch=branches.get(doc.branch_code), source_type=plan2_adapter.MANUAL_IMPORT_SOURCE,
                           source_key=doc.source_key)
        plan2_adapter.settle_parked_manual_entry(doc.source_key, entry=entry, user=user)
    return 'imported'


def _ignore_one(exc, user, note):
    exc.status, exc.resolved_by, exc.resolved_at, exc.resolution_note = 'ignored', user, timezone.now(), note
    exc.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
    parties._audit('gl_exception_ignored', user=user, obj=exc, old_data={'status': 'open'},
                   new_data={'status': 'ignored', 'kind': exc.kind, 'note': note,
                             'source_key': exc.source_doc.source_key})


def decide(*, pattern: str, decision: str, expected_count: int, note: str, user) -> dict:
    if decision not in ('import', 'ignore'):
        raise PatternError('bad_decision')
    note = (note or '').strip()
    if decision == 'ignore' and (not note or len(note) > MAX_NOTE):
        raise PatternError('note_required')
    fed, links = plan2_adapter.softech_fed_account_codes(), _link_accounts()
    res = {'pattern': pattern, 'decision': decision, 'decided': 0, 'imported': 0, 'already_imported': 0,
           'ignored': 0, 'failed': []}
    with transaction.atomic():
        rows = [e for e in _open_rows().select_for_update(of=('self',))
                if pattern_key(*_pattern_of(e, fed, links)) == pattern]
        if not rows:
            raise PatternError('unknown_pattern')
        if len(rows) != expected_count:
            raise PatternError('count_changed')
        branches = {b.softech_branch_id: b for b in
                    Branch.objects.filter(softech_branch_id__in={e.source_doc.branch_code for e in rows})}
        for exc in rows:
            if decision == 'ignore':
                _ignore_one(exc, user, note)
                res['ignored'] += 1
                continue
            try:
                res[_import_one(exc, user, branches)] += 1
            except LedgerError as err:
                res['failed'].append({'key': exc.source_doc.source_key, 'code': err.code, 'detail': err.message})
        res['decided'] = res['imported'] + res['already_imported'] + res['ignored']
        _audit('gl_mixed_pattern_decided', user=user, obj=None,
               new_data={k: res[k] for k in ('pattern', 'decision', 'decided', 'imported', 'already_imported',
                                             'ignored')} | {'failed': len(res['failed'])},
               note=note[:255] if decision == 'ignore' else '')
    return res
