"""General Ledger service — the only place that drafts, approves and reverses journal entries.

Rules (deterministic, auditable, idempotent):
  * a draft may be unbalanced; approval requires Σdebit == Σcredit > 0;
  * amounts are ≥ 0, at most 2 decimals, exactly one side > 0 per line;
  * approval needs an open period and entry_date >= OPENING_DATE;
  * the number comes from a locked GLSequence row per year → JV-{year}-{n:06d};
  * an approved entry is never edited — it is reversed by an approved mirror entry.
Every call writes an AuditLog row (who / what / before-after).
"""
import calendar
import datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.finance.models import FinancialPeriod

from .models import GLAccount, GLSequence, LedgerEntry, LedgerLine

OPENING_DATE = datetime.date(2026, 1, 1)

_CENT = Decimal('0.01')
_MAX_AMOUNT = Decimal('1e16')  # LedgerLine.debit/credit: max_digits=18, decimal_places=2

MESSAGES = {
    'unbalanced':          'القيد مش متزن: إجمالي المدين لازم يساوي إجمالي الدائن.',
    'empty':               'القيد فاضي: لازم يكون فيه مبلغ.',
    'bad_amount':          'مبلغ غير صحيح: لازم يكون موجب، بحد أقصى رقمين عشريين، وفي جانب واحد بس (مدين أو دائن).',
    'closed_period':       'الفترة المالية مقفلة، مينفعش نسجل فيها.',
    'before_opening':      'تاريخ القيد قبل تاريخ بداية الدفاتر (1/1/2026).',
    'inactive_account':    'الحساب غير موجود أو موقوف.',
    'non_posting_account': 'الحساب ده إجمالي ومينفعش يترحل عليه مباشرة.',
    'party_required':      'الحساب ده محتاج كود طرف (مورد/عميل/موظف/شريك).',
    'branch_required':     'الحساب ده محتاج تحديد الفرع.',
    'not_draft':           'القيد ده مش مسودة، مينفعش يتعدل أو يتعتمد.',
    'not_approved':        'القيد لازم يكون معتمد عشان يتعكس.',
    'already_reversed':    'القيد ده اتعكس قبل كده.',
    'is_reversal':         'القيد ده قيد عكسي، مينفعش يتعكس.',
    'source_conflict':     'فيه قيد تاني شغال مربوط بنفس المصدر.',
}


class LedgerError(Exception):
    def __init__(self, code: str, detail: dict | None = None):
        self.code = code
        self.message = MESSAGES.get(code, code)
        self.detail = detail or {}
        super().__init__(f'{code}: {self.message}')


# ── helpers ──────────────────────────────────────────────────────────────────

def _amount(value, line_no: int) -> Decimal:
    if value in (None, ''):
        return Decimal('0')
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise LedgerError('bad_amount', {'line_no': line_no})
    if not d.is_finite() or d < 0 or d >= _MAX_AMOUNT or d != d.quantize(_CENT):
        raise LedgerError('bad_amount', {'line_no': line_no})
    return d.quantize(_CENT)


def _period_for(day: datetime.date) -> FinancialPeriod:
    """Get or create the month FinancialPeriod for `day` (safe against a concurrent create)."""
    last = calendar.monthrange(day.year, day.month)[1]
    period, _ = FinancialPeriod.objects.get_or_create(
        year=day.year, month=day.month, period_type='month',
        defaults={'period_start': day.replace(day=1), 'period_end': day.replace(day=last)})
    return period


def _check_account(account: GLAccount | None, line_no: int):
    if account is None or not account.is_active:
        raise LedgerError('inactive_account', {'line_no': line_no})
    if not account.is_posting:
        raise LedgerError('non_posting_account', {'line_no': line_no})


def _snapshot(entry: LedgerEntry) -> dict:
    return {
        'number': entry.number,
        'status': entry.status,
        'entry_date': entry.entry_date.isoformat() if entry.entry_date else None,
        'period_id': entry.period_id,
        'book': entry.book,
        'branch_id': entry.branch_id,
        'description': entry.description,
        'source_type': entry.source_type,
        'source_key': entry.source_key,
        'created_by': entry.created_by_id,
        'approved_by': entry.approved_by_id,
        'approved_at': entry.approved_at.isoformat() if entry.approved_at else None,
        'reverses': entry.reverses_id,
        'lines': [
            {'line_no': ln.line_no, 'account': ln.account.code, 'branch_id': ln.branch_id,
             'party_code': ln.party_code, 'debit': str(ln.debit), 'credit': str(ln.credit),
             'description': ln.description, 'cheque_no': ln.cheque_no,
             'due_date': ln.due_date.isoformat() if ln.due_date else None}
            for ln in entry.lines.select_related('account').order_by('line_no')
        ],
    }


def _next_number(year: int) -> str:
    GLSequence.objects.get_or_create(year=year)
    seq = GLSequence.objects.select_for_update().get(year=year)
    seq.last += 1
    seq.save(update_fields=['last'])
    return f'JV-{year}-{seq.last:06d}'


def _lock_open_period(day: datetime.date) -> FinancialPeriod:
    period = FinancialPeriod.objects.select_for_update().get(pk=_period_for(day).pk)
    if period.status != 'open':
        raise LedgerError('closed_period', {'period': str(period)})
    return period


# ── public API ───────────────────────────────────────────────────────────────

def save_draft(*, user, entry_date, description, lines, book='general', branch=None,
               source_type='', source_key='', entry: LedgerEntry | None = None) -> LedgerEntry:
    """Create a draft, or replace the header + lines of an existing draft."""
    # validate lines before touching the DB
    codes = {str(ln.get('account_code') or '') for ln in lines}
    accounts = {a.code: a for a in GLAccount.objects.filter(code__in=codes)}
    prepared = []
    for i, ln in enumerate(lines, start=1):
        account = accounts.get(str(ln.get('account_code') or ''))
        _check_account(account, i)
        debit, credit = _amount(ln.get('debit'), i), _amount(ln.get('credit'), i)
        if (debit > 0) == (credit > 0):  # both sides, or neither
            raise LedgerError('bad_amount', {'line_no': i})
        prepared.append(LedgerLine(
            line_no=i, account=account, branch_id=ln.get('branch_id') or None,
            party_code=(ln.get('party_code') or '').strip(), debit=debit, credit=credit,
            description=ln.get('description') or '', cheque_no=ln.get('cheque_no') or '',
            due_date=ln.get('due_date') or None))

    with transaction.atomic():
        period = _period_for(entry_date)
        old = None
        if entry is None:
            entry = LedgerEntry(created_by=user, status='draft')
        else:
            entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
            if entry.status != 'draft':
                raise LedgerError('not_draft')
            old = _snapshot(entry)
        entry.entry_date = entry_date
        entry.period = period
        entry.book = book
        entry.branch = branch
        entry.description = description or ''
        entry.source_type = source_type or ''
        entry.source_key = source_key or ''
        try:
            with transaction.atomic():
                entry.save()
        except IntegrityError:
            raise LedgerError('source_conflict', {'source_key': entry.source_key})
        entry.lines.all().delete()
        for ln in prepared:
            ln.entry = entry
        LedgerLine.objects.bulk_create(prepared)
        AuditLog.log('gl_entry_draft_saved', user=user, obj=entry,
                     old_data=old, new_data=_snapshot(entry))
    return entry


def approve(entry_id: int, *, user, _allow_before_opening: bool = False) -> LedgerEntry:
    """Approve a draft. `_allow_before_opening` is for gl_reproduce_workbook only (rolled back)."""
    with transaction.atomic():
        entry = LedgerEntry.objects.select_for_update().get(pk=entry_id)
        if entry.status != 'draft':
            raise LedgerError('not_draft')
        lines = list(entry.lines.select_related('account').order_by('line_no'))
        total_debit = sum((ln.debit for ln in lines), Decimal('0'))
        total_credit = sum((ln.credit for ln in lines), Decimal('0'))
        if not lines or (total_debit == 0 and total_credit == 0):
            raise LedgerError('empty')
        if total_debit != total_credit:
            raise LedgerError('unbalanced', {'debit': str(total_debit), 'credit': str(total_credit)})
        if entry.entry_date < OPENING_DATE and not _allow_before_opening:
            raise LedgerError('before_opening')
        for ln in lines:  # accounts may have changed since the draft was saved
            _check_account(ln.account, ln.line_no)
            if ln.account.requires_party and not ln.party_code:
                raise LedgerError('party_required', {'line_no': ln.line_no})
            if ln.account.requires_branch and not ln.branch_id:
                raise LedgerError('branch_required', {'line_no': ln.line_no})
        period = FinancialPeriod.objects.select_for_update().get(pk=entry.period_id)
        if period.status != 'open':
            raise LedgerError('closed_period', {'period': str(period)})

        old = _snapshot(entry)
        entry.number = _next_number(entry.entry_date.year)
        entry.status = 'approved'
        entry.approved_by = user
        entry.approved_at = timezone.now()
        entry.save(update_fields=['number', 'status', 'approved_by', 'approved_at'])
        AuditLog.log('gl_entry_approved', user=user, obj=entry,
                     old_data=old, new_data=_snapshot(entry))
    return entry


def reverse(entry_id: int, *, user, reason: str,
            entry_date: datetime.date | None = None) -> LedgerEntry:
    """Reverse an approved entry with an approved mirror entry (debit↔credit)."""
    with transaction.atomic():
        original = LedgerEntry.objects.select_for_update().get(pk=entry_id)
        if original.status == 'reversed':
            raise LedgerError('already_reversed')
        if original.status != 'approved':
            raise LedgerError('not_approved')
        if original.reverses_id:
            raise LedgerError('is_reversal')
        day = entry_date or original.entry_date
        if day < OPENING_DATE:
            raise LedgerError('before_opening')
        period = _lock_open_period(day)

        old = _snapshot(original)
        mirror = LedgerEntry.objects.create(
            entry_date=day, period=period, book=original.book, branch_id=original.branch_id,
            description=f'عكس قيد {original.number}'[:500], status='approved',
            source_type='reversal', source_key='', created_by=user, approved_by=user,
            approved_at=timezone.now(), reverses=original, notes=reason or '',
            number=_next_number(day.year))
        LedgerLine.objects.bulk_create([
            LedgerLine(entry=mirror, line_no=ln.line_no, account_id=ln.account_id,
                       branch_id=ln.branch_id, party_code=ln.party_code,
                       debit=ln.credit, credit=ln.debit, description=ln.description,
                       cheque_no=ln.cheque_no, due_date=ln.due_date)
            for ln in original.lines.order_by('line_no')
        ])
        original.status = 'reversed'
        original.save(update_fields=['status'])
        AuditLog.log('gl_entry_reversed', user=user, obj=original,
                     old_data=old, new_data=_snapshot(original),
                     extra={'reason': reason or '', 'reversal_id': mirror.id,
                            'reversal_number': mirror.number, 'reversal': _snapshot(mirror)},
                     note=(reason or '')[:255])
    return mirror
