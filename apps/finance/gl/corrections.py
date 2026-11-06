"""Late SOFTECH changes into months that no longer take postings.

A closed month is never touched: the difference is drafted into the first open month. Ruling P19:
one exception = one group = one correction. Entries are written only through ``ledger.save_draft``.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from apps.branches.models import Branch

from . import ledger, plan2_adapter
from .ledger import LedgerError
from .models import LedgerEntry, LedgerLine
from .periods import accepts_postings, first_open_period_after


def effective_lines(original: LedgerEntry, *, include_drafts: bool = False) -> dict:
    """(account_code, branch_id, party_code) -> signed net (debit − credit) of the original plus its
    approved corrections. A reversed correction drops out by its status (its mirror never points at
    the original). The original's own mirror counts even when it has no `corrects` link: it was
    reversed while its month was still open. Zero nets are left out.

    `include_drafts`: also the draft corrections, i.e. what the entry will say once they are
    approved. The engine compares with this, so a pending draft cannot hide a difference."""
    nets = defaultdict(Decimal)
    statuses = ('approved', 'draft') if include_drafts else ('approved',)
    rows = LedgerLine.objects.filter(
        Q(entry=original)
        | Q(entry__status__in=statuses) & (Q(entry__corrects=original) | Q(entry__reverses=original))
    ).values_list('account__code', 'branch_id', 'party_code', 'debit', 'credit')
    for code, branch_id, party_code, debit, credit in rows:
        nets[(code, branch_id, party_code)] += debit - credit
    return {key: net for key, net in nets.items() if net}


def _aggregate(lines) -> dict:
    nets = defaultdict(Decimal)
    for i, ln in enumerate(lines, start=1):
        branch_id = ln.get('branch_id') or None
        if branch_id is not None:
            try:
                branch_id = int(branch_id)
            except (TypeError, ValueError):
                raise LedgerError('bad_branch', {'line_no': i, 'branch_id': str(branch_id)})
        key = (str(ln.get('account_code') or ''), branch_id, (ln.get('party_code') or '').strip())
        nets[key] += ledger._amount(ln.get('debit'), i) - ledger._amount(ln.get('credit'), i)
    return nets


def net_lines(lines) -> dict:
    """Proposed lines in the shape of `effective_lines`."""
    return {key: net for key, net in _aggregate(lines).items() if net}


def _difference_lines(new_lines, current) -> list:
    """new_lines − current, debits first; zero nets dropped."""
    nets = _aggregate(new_lines)
    for key, net in current.items():
        nets[key] -= net
    out = [{'account_code': code, 'branch_id': branch_id, 'party_code': party_code,
            'debit': net if net > 0 else Decimal('0'), 'credit': -net if net < 0 else Decimal('0')}
           for (code, branch_id, party_code), net in nets.items() if net]
    out.sort(key=lambda ln: (ln['credit'] > 0, ln['account_code'], ln['branch_id'] or 0, ln['party_code']))
    return out


def _lock_open_change(exception_id):
    change = plan2_adapter.closed_period_change(exception_id, for_update=True)
    if change.status != 'open':
        raise LedgerError('exception_not_open', {'exception_id': exception_id})
    return change


def post_late_correction(original_id: int, new_lines: list, *, user, reason: str,
                         exception_id: int | None = None) -> LedgerEntry:
    """Draft the difference between `new_lines` and what `original` effectively says now, in the
    first open month after it. With `exception_id`, `new_lines` are the group's whole proposed
    lines and the exception resolves in the same transaction."""
    with transaction.atomic():
        original = LedgerEntry.objects.select_for_update().select_related('period').get(pk=original_id)
        if original.status == 'draft':
            raise LedgerError('original_is_draft')
        if original.reverses_id:
            raise LedgerError('is_reversal')
        if original.corrects_id:
            raise LedgerError('is_correction')
        if original.source_type in ledger.CLOSE_SOURCE_TYPES:
            raise LedgerError('close_entry')
        if original.period.status == 'open':
            raise LedgerError('period_open', {'period': str(original.period)})
        change = None
        if exception_id is not None:
            change = _lock_open_change(exception_id)
            if change.original_entry is None or change.original_entry.pk != original.pk:
                raise LedgerError('exception_mismatch', {'exception_id': exception_id})
            if (change.draft_entry_id
                    and LedgerEntry.objects.filter(pk=change.draft_entry_id, status='draft').exists()):
                raise LedgerError('exception_has_draft', {'entry_id': change.draft_entry_id})
        # only approved corrections net: a second one beside a draft would count the difference twice
        if original.corrections.filter(status='draft').exists():
            raise LedgerError('correction_pending')
        lines = _difference_lines(new_lines, effective_lines(original))
        if not lines:
            raise LedgerError('nothing_to_correct')

        period = first_open_period_after(original.entry_date)
        if change is not None:
            source_key = f'{change.group_key}#corr:exc{exception_id}'
        else:
            n = original.corrections.count() + 1
            # a manual original has no source key, and '' would collide across originals
            base = original.source_key or f'entry:{original.pk}'
            source_key = f'{base}#corr:{period.period_start:%Y-%m}:{n}'
        entry = ledger.save_draft(
            user=user, entry_date=period.period_start, lines=lines, book=original.book,
            branch=original.branch, source_type=original.source_type, source_key=source_key,
            description=f'تصحيح قيد {original.number} — {reason}'[:500], corrects=original)
        old_data, new_data = None, ledger._snapshot(entry)
        if change is not None:
            plan2_adapter.mark_exception_resolved(exception_id, user=user, entry=entry)
            old_data, new_data['exception_status'] = {'exception_status': change.status}, 'resolved'
        ledger._audit('gl_late_correction_drafted', user=user, obj=entry, old_data=old_data, new_data=new_data,
                      extra={'original_id': original.pk, 'original_number': original.number,
                             'reason': reason, 'exception_id': exception_id,
                             'group_key': change.group_key if change else '',
                             'member_source_keys': change.member_source_keys if change else []},
                      note=reason)
    return entry


def post_late_document(exception_id: int, *, user) -> LedgerEntry:
    """A brand-new SOFTECH group in a closed month: its proposed lines as they are, drafted once
    (source_key = the group key) in the first open month, and the exception resolved with it."""
    with transaction.atomic():
        change = _lock_open_change(exception_id)
        if change.original_entry is not None:
            raise LedgerError('exception_has_original', {'exception_id': exception_id})
        # 'approved': the month reopened and the draft was approved; posting again would double it
        if (change.draft_entry_id and LedgerEntry.objects.filter(
                pk=change.draft_entry_id, status__in=('draft', 'approved')).exists()):
            raise LedgerError('exception_has_draft', {'entry_id': change.draft_entry_id})
        if accepts_postings(change.source_date):
            raise LedgerError('period_open', {'source_date': change.source_date.isoformat()})
        if not change.proposed_lines:
            raise LedgerError('empty')
        period = first_open_period_after(change.source_date)
        branch_ids = {ln['branch_id'] for ln in change.proposed_lines if ln.get('branch_id')}
        entry = ledger.save_draft(
            user=user, entry_date=period.period_start, lines=change.proposed_lines, book=change.book,
            branch=Branch.objects.get(pk=branch_ids.pop()) if len(branch_ids) == 1 else None,
            source_type=change.source_type,
            source_key=change.group_key,
            description=f'مستند متأخر بتاريخ {change.source_date.isoformat()} — {change.group_key}'[:500])
        plan2_adapter.mark_exception_resolved(exception_id, user=user, entry=entry)
        ledger._audit('gl_late_document_drafted', user=user, obj=entry,
                      old_data={'exception_status': change.status},
                      new_data={**ledger._snapshot(entry), 'exception_status': 'resolved'},
                      extra={'exception_id': exception_id, 'group_key': change.group_key,
                             'member_source_keys': change.member_source_keys,
                             'source_date': change.source_date.isoformat()})
    return entry
