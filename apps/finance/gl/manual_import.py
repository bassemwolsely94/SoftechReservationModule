"""Importer for finance's 2026 manual-only journal entries (finance-gl Plan 3, Task 8).

Finance's journal has one row per account side and no entry number, so rows are grouped by
(date, book, branch, description). A group whose accounts are all manual becomes one draft; a group
SOFTECH feeds is skipped (the drafting engine replaces it); a group with both is parked in the
exceptions inbox for an accountant, never guessed. Nothing here approves.

Money is read as it stands: more than 2 decimals is reported, never rounded. The one exception is a
float within 1e-6 of 2 decimals, which is Excel's float noise, not a third decimal.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import zipfile
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import openpyxl
from django.db import transaction
from openpyxl.utils.exceptions import InvalidFileException

from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance.models import FinancialPeriod

from . import plan2_adapter
from .ledger import _MAX_AMOUNT, LedgerError, _audit, save_draft
from .models import GLAccount, LedgerEntry, LedgerLine
from .names import normalize_ar
from .periods import OPENING_DATE
from .sources import _canon

logger = logging.getLogger(__name__)

SOURCE_TYPE = plan2_adapter.MANUAL_IMPORT_SOURCE
_CENT = Decimal('0.01')
_ZERO = Decimal('0.00')
_FLOAT_NOISE = Decimal('0.000001')
HEADER_SCAN_ROWS = 20
# what openpyxl raises on a file that is a zip but not a sound workbook (XML parse errors are SyntaxErrors)
READ_ERRORS = (zipfile.BadZipFile, KeyError, ValueError, SyntaxError, EOFError, zlib.error)

# column -> finance's header labels; a renamed header in the 2026 file is one more alias here
_COLUMNS = {
    'account': ('رقم العملية',), 'customer': ('customer code',), 'supplier': ('suppliar code', 'supplier code'),
    'employee': ('كود الموظف',), 'description': ('discreption', 'description'), 'shift': ('shift num.',),
    'debit': ('مدين',), 'credit': ('credit',), 'balance': ('balanc', 'balance'), 'condition': ('condition',),
    'date': ('date',), 'pay_cheque': ('Payment cheque num.',), 'recv_cheque': ('Received cheque num.',),
    'branch_code': ('رقم القرع', 'رقم الفرع'), 'branch_name': ('اسم الفرع',), 'book': ('اليومية',),
}
_DUE_LABEL = 'due date'   # twice in the file: first = payment cheque, second = received cheque
_VALUE_COLUMNS = ('account', 'date', 'description', 'debit', 'credit', 'balance', 'condition')


def _label(value) -> str:
    return normalize_ar(value).casefold()


_LABELS = {_label(alias): col for col, aliases in _COLUMNS.items() for alias in aliases}
_CONDITION_SIDE = {_label(k): v for k, v in (('Debt', 'debit'), ('Debit', 'debit'), ('مدين', 'debit'),
                                             ('Credit', 'credit'), ('دائن', 'credit'))}
_NOTHING = _label('Nothing')

# Credit-book note §2: returns and discounts carry text on these and the document number on 2341
_RETURN_ACCOUNTS = frozenset({'5101', '5102', '5105', '5106', '5121', '5122', '2341'})
_SUPPLIERS = '2341'
MERGED_BY_DATE_BRANCH = 'date_branch'

STATUSES = ('manual', 'softech', 'mixed', 'unbalanced', 'unknown_account', 'unknown_branch', 'before_opening',
            'changed_since_import', 'possible_duplicate', 'closed_period')
NOT_IMPORTABLE = ('unbalanced', 'unknown_account', 'unknown_branch', 'before_opening', 'changed_since_import',
                  'possible_duplicate', 'closed_period')
INCLUDABLE = ('mixed', 'possible_duplicate')   # an accountant's decision: `include_mixed`
_PARTY_FIELD = {'supplier': 'supplier_code', 'customer': 'customer_code', 'employee': 'employee_code'}

DEFAULT_LINK_ACCOUNTS = ('2354',)   # finance's cross-book clearing account: nets to ~0, not a creditor
# Finance's own list: SOFTECH-mapped accounts, but these pairs are keyed by hand (daily cash handovers)
DEFAULT_MANUAL_ACCOUNT_SETS = (('1301', '1302'), ('1302', '2404'), ('1301', '2405'), ('1301', '2406'),
                               ('1301', '2408'), ('1301', '2413'), ('1301', '2417'))
MAX_PARTY_CODE = 40   # LedgerLine.party_code
MAX_CHEQUE_NO = 40    # LedgerLine.cheque_no
DEFAULT_BRANCH_ALIASES = {   # finance's branch names -> SOFTECH branch
    'شركة الرزيقي': '100', 'صيدلية د علياء النزهة2': '130', 'صيدلية د بليغ الجيزة': '140',
    'صيدلية الرزيقى عين شمس': '150', 'صيدلية باب الحديد': '160', 'صيدلية د  محسن عباسية': '170',
}

PARSE_MESSAGES = {
    'book_required': 'حدد الدفتر (نقدية / آجل): الملف مفيهوش عمود «اليومية» واسم الملف مبيقولش.',
    'bad_book': 'الدفتر لازم يكون cash أو credit.',
    'sheet_not_found': 'الشيت المحدد مش موجود في الملف.',
    'header_not_found': 'مفيش شيت فيه عناوين اليومية (رقم العملية، discreption، date، المدين والدائن).',
    'too_many_rows': 'الملف أكبر من الحد المسموح — قسّمه إلى ملفات أصغر.',
    'unreadable': 'تعذّر قراءة الملف.',
}


class ParseError(Exception):
    def __init__(self, code: str):
        self.code = code
        self.message = PARSE_MESSAGES.get(code, code)
        super().__init__(f'{code}: {self.message}')


@dataclass(slots=True)
class JournalRow:
    row_no: int
    date: datetime.date
    book: str
    account_code: str
    branch_code: str
    branch_name: str
    description: str
    shift: str
    side: str
    amount: Decimal
    customer_code: str
    supplier_code: str
    employee_code: str
    cheque_no: str
    due_date: datetime.date | None


@dataclass
class ParsedJournal:
    rows: list
    skipped: list          # [{'row': n, 'reason': code}]: never figures or names
    book: str              # cash | credit | mixed (a file holding both)
    warnings: list
    skipped_zero: int = 0
    # (date, book, branch name, branch code, normalised description) of the groups that lost a reported row
    rejected: set = field(default_factory=set)


@dataclass
class JournalGroup:
    key: str               # the entry's source_key: manual_import:<lines hash>:<group identity>
    date: datetime.date
    book: str
    branch: str
    description: str
    rows: list
    balanced: bool = False
    merged_by: str = ''
    feeds: set = field(default_factory=set)
    status: str = ''
    target_branch: Branch | None = None
    manual_set: bool = False        # its accounts are on finance's list: manual whatever the feeds say
    existing_entry: LedgerEntry | None = None   # changed_since_import, possible_duplicate: the live entry

    @property
    def debit(self) -> Decimal:
        return sum((r.amount for r in self.rows if r.side == 'debit'), _ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((r.amount for r in self.rows if r.side == 'credit'), _ZERO)


# ── cells ────────────────────────────────────────────────────────────────────

def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _code(value) -> str:
    """A code cell: Excel's 1341.0 is '1341'; finance's lookups leave 0 or - on an empty one."""
    t = _text(value)
    return '' if t in ('0', '-') else t


def _date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        for parse in (datetime.date.fromisoformat, lambda s: datetime.datetime.strptime(s, '%d/%m/%Y').date()):
            try:
                return parse(value.strip()[:10])
            except ValueError:
                continue
    return None


def _money(value) -> Decimal:
    """Decimal with 2 places, blank = 0.00. ValueError: not a number, or more than 2 decimals."""
    if value is None or value == '':
        return _ZERO
    if isinstance(value, bool):
        raise ValueError('bad_amount')
    try:
        d = Decimal(value.strip()) if isinstance(value, str) else Decimal(str(value))
        if not d.is_finite() or abs(d) >= _MAX_AMOUNT:
            raise ValueError('bad_amount')
        q = d.quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError('bad_amount')
    if d == q or (isinstance(value, float) and abs(d - q) <= _FLOAT_NOISE):
        return q
    raise ValueError('bad_amount')


def _book_in(text) -> str:
    t = normalize_ar(text)
    if 'اجل' in t:
        return 'credit'
    return 'cash' if 'نقد' in t else ''


# ── parsing ──────────────────────────────────────────────────────────────────

def _sheet_rows(ws, **kw):
    """The sheet's rows; a failed read is an unreadable file. Only the read: an error in the caller's code stays a bug."""
    try:
        yield from ws.iter_rows(values_only=True, **kw)
    except READ_ERRORS:
        raise ParseError('unreadable')


def _columns(cells) -> dict:
    cols = {}
    for pos, value in enumerate(cells):
        if not isinstance(value, str):
            continue
        label = _label(value)
        if label == _DUE_LABEL:
            cols.setdefault('due', []).append(pos)
        elif label in _LABELS:
            cols.setdefault(_LABELS[label], pos)
    return cols


def _is_header(cols) -> bool:
    return ({'account', 'date', 'description'} <= cols.keys()
            and ({'debit', 'credit'} <= cols.keys() or {'condition', 'balance'} <= cols.keys()))


def _find_header(ws):
    for row_no, cells in enumerate(_sheet_rows(ws, max_row=HEADER_SCAN_ROWS), start=1):
        cols = _columns(cells)
        if _is_header(cols):
            return row_no, cols
    return None


def _journal_sheet(wb, sheet_name):
    """-> (worksheet, header row, columns) of the named sheet, or of the first holding the labels."""
    if sheet_name:
        sheets = [ws for ws in wb.worksheets if _label(ws.title) == _label(sheet_name)]
        if not sheets:
            raise ParseError('sheet_not_found')
    else:
        sheets = wb.worksheets
    for ws in sheets:
        found = _find_header(ws)
        if found:
            return (ws, *found)
    raise ParseError('header_not_found')


def _side_amount(values, cols):
    """-> (side, amount), side '' for a zero row. ValueError(reason) for a row to report."""
    if 'debit' in cols and 'credit' in cols:
        debit, credit = _money(values.get('debit')), _money(values.get('credit'))
        if debit < 0 or credit < 0:
            raise ValueError('bad_amount')
        if debit and credit:
            raise ValueError('both_sides')
        return ('debit', debit) if debit else ('credit', credit) if credit else ('', _ZERO)
    amount = abs(_money(values.get('balance')))
    if not amount:
        return '', _ZERO
    side = _CONDITION_SIDE.get(_label(values.get('condition')))
    if side is None:
        raise ValueError('bad_condition')
    return side, amount


def parse_journal(path, sheet_name=None, book=None, max_rows=None) -> ParsedJournal:
    """Read one journal sheet in read-only streaming mode. Named columns only: the file's other
    columns (some hold filler text on every row) are never read. `max_rows` is the API's cap."""
    if book and book not in ('cash', 'credit'):
        raise ParseError('bad_book')
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, *READ_ERRORS):
        raise ParseError('unreadable')
    try:
        ws, header_row, cols = _journal_sheet(wb, sheet_name)
        default_book = book or _book_in(os.path.basename(str(path)))
        if 'book' not in cols and not default_book:
            raise ParseError('book_required')
        return _read_rows(ws, header_row, cols, default_book, max_rows)
    finally:
        wb.close()


def _cell(cells, pos):
    return cells[pos] if pos is not None and pos < len(cells) else None


def _cheque_pair(values, first_due, second_due):
    """The payment pair when it has a cheque, else the received pair; with no cheque at all, the
    due date that is there. A stray first date never hides a filled received cheque."""
    paid, received = _code(values.get('pay_cheque')), _code(values.get('recv_cheque'))
    if paid:
        return paid, first_due
    if received:
        return received, second_due
    return '', first_due or second_due


def _read_rows(ws, header_row, cols, default_book, max_rows) -> ParsedJournal:
    rows, skipped, rejected, books = [], [], set(), set()
    zero = seen = 0
    named = [(col, pos) for col, pos in cols.items() if col != 'due']
    due_1, due_2 = (cols.get('due', []) + [None, None])[:2]

    for row_no, cells in enumerate(_sheet_rows(ws, min_row=header_row + 1), start=header_row + 1):
        v = {col: _cell(cells, pos) for col, pos in named}
        if all(v.get(c) in (None, '') for c in _VALUE_COLUMNS):
            continue   # a blank row is no row at all
        seen += 1
        if max_rows is not None and seen > max_rows:
            raise ParseError('too_many_rows')

        reason, side, amount = '', '', _ZERO
        try:
            side, amount = _side_amount(v, cols)
        except ValueError as e:
            reason = str(e)
        if _label(v.get('condition')) == _NOTHING and (side or reason == 'bad_condition'):
            reason = 'nothing_with_amount'   # says nothing, holds a figure: not ours to pick
        if not reason and not side:
            zero += 1
            continue
        day, account = _date(v.get('date')), _code(v.get('account'))
        cell_book = _text(v.get('book'))
        row_book = _book_in(cell_book) if cell_book else default_book
        cheque, due = _cheque_pair(v, _date(_cell(cells, due_1)), _date(_cell(cells, due_2)))
        parties = (_code(v.get('customer')), _code(v.get('supplier')), _code(v.get('employee')))
        reason = reason or ('no_date' if not day else 'no_account' if not account else
                            'party_too_long' if any(len(c) > MAX_PARTY_CODE for c in parties) else
                            'cheque_too_long' if len(cheque) > MAX_CHEQUE_NO else
                            '' if row_book else 'bad_book' if cell_book else 'no_book')
        desc = _text(v.get('description'))
        branch_code, branch_name = _code(v.get('branch_code')), _text(v.get('branch_name'))
        if reason:
            skipped.append({'row': row_no, 'reason': reason})
            if day and row_book:   # its group is short of this row: it can't be trusted to balance
                rejected.add((day, row_book, branch_name, branch_code, normalize_ar(desc)))
            continue

        books.add(row_book)
        rows.append(JournalRow(
            row_no=row_no, date=day, book=row_book, account_code=account, branch_code=branch_code,
            branch_name=branch_name, description=desc, shift=_code(v.get('shift')), side=side, amount=amount,
            customer_code=parties[0], supplier_code=parties[1], employee_code=parties[2],
            cheque_no=cheque, due_date=due))

    warnings = [f'{len(skipped)} صف مش هيتسجل: راجع قائمة الصفوف المرفوضة.'] if skipped else []
    the_book = 'mixed' if len(books) > 1 else (next(iter(books)) if books else default_book)
    return ParsedJournal(rows=rows, skipped=skipped, book=the_book, warnings=warnings, skipped_zero=zero,
                         rejected=rejected)


# ── settings and feeds ───────────────────────────────────────────────────────

def _link_accounts() -> set:
    value = SystemSetting.get('gl_import_link_accounts', list(DEFAULT_LINK_ACCOUNTS))
    if not isinstance(value, (list, tuple)):
        logger.warning('[GLManualImport] gl_import_link_accounts is not a list — using the default')
        value = DEFAULT_LINK_ACCOUNTS
    return {str(c) for c in value}


def _manual_account_sets() -> list:
    value = SystemSetting.get('gl_import_manual_account_sets', DEFAULT_MANUAL_ACCOUNT_SETS)
    try:
        if isinstance(value, (str, dict)) or any(isinstance(s, (str, dict)) for s in value):
            raise TypeError('not a list of lists')
        return [frozenset(str(c) for c in s) for s in value]
    except TypeError:
        logger.warning('[GLManualImport] gl_import_manual_account_sets is not a list of lists — using the default')
        return [frozenset(s) for s in DEFAULT_MANUAL_ACCOUNT_SETS]


def _branch_index() -> dict:
    by_name, by_softech = {}, {}
    for b in Branch.objects.all():
        by_softech[str(b.softech_branch_id)] = b
        for name in (b.name, b.name_ar):
            if name:
                by_name.setdefault(normalize_ar(name), b)
    extra = SystemSetting.get('gl_branch_aliases', {})
    if not isinstance(extra, dict):
        logger.warning('[GLManualImport] gl_branch_aliases is not a dictionary — using the defaults')
        extra = {}
    aliases = {normalize_ar(k): str(v) for k, v in {**DEFAULT_BRANCH_ALIASES, **extra}.items()}
    return {'by_name': by_name, 'by_softech': by_softech, 'aliases': aliases}


def resolve_branch(name: str, code: str = '', _index=None) -> Branch | None:
    """`normalize_ar` match on the branch's name, then SystemSetting `gl_branch_aliases`
    ({alias_or_finance_code: softech_branch_id}, added to finance's six branch names)."""
    idx = _index or _branch_index()
    name = normalize_ar(name)
    if name in idx['by_name']:
        return idx['by_name'][name]
    target = idx['aliases'].get(name) or idx['aliases'].get(normalize_ar(code))
    return idx['by_softech'].get(target) if target else None


def effective_feed(account, _fed=None) -> str:
    """'softech' | 'manual' | 'both': the account's override, else derived from what the active
    posting rules and source maps post to. `_fed` memoises that read for one import."""
    if account.feed != 'auto':
        return account.feed
    fed = plan2_adapter.softech_fed_account_codes() if _fed is None else _fed
    return 'softech' if account.code in fed else 'manual'


def _sha(raw: str, size: int) -> str:
    return hashlib.sha1(raw.encode('utf-8'), usedforsecurity=False).hexdigest()[:size]


def _source_key(day, book, branch, rows, merged) -> str:
    """manual_import:<lines>:<identity>. <lines> changes with any figure; the description is in each
    line, so two groups with the same figures that day stay two entries. <identity> is which group
    of the journal this is: it survives a re-export and an accountant's edit of the draft."""
    lines = sorted(f'{r.account_code}:{r.side}:{r.amount}:{r.customer_code}:{r.supplier_code}:{r.employee_code}:'
                   f'{r.cheque_no}:{normalize_ar(r.description)}' for r in rows)
    head = [day.isoformat(), book, branch]
    identity = MERGED_BY_DATE_BRANCH if merged else normalize_ar(rows[0].description)
    return f"{SOURCE_TYPE}:{_sha('|'.join(head + lines), 20)}:{_sha('|'.join(head + [identity]), 12)}"


def _identity(source_key: str) -> str:
    parts = source_key.split(':')
    return parts[2] if len(parts) == 3 else ''


def _live_imports_by_identity() -> dict:
    out = defaultdict(list)
    for e in LedgerEntry.objects.filter(source_key__startswith=f'{SOURCE_TYPE}:', status__in=('draft', 'approved')):
        out[_identity(e.source_key)].append(e)
    return out


class _Lookups:
    """Everything one import reads from the database: once, whatever the size of the file."""

    def __init__(self, rows):
        codes = {r.account_code for r in rows}
        self.accounts = {a.code: a for a in GLAccount.objects.filter(code__in=codes)}
        self.fed = plan2_adapter.softech_fed_account_codes()
        self.links = _link_accounts()
        self.branches = _branch_index()
        self.manual_sets = _manual_account_sets()
        self.live_by_identity = _live_imports_by_identity()
        self.not_open_months = set(FinancialPeriod.objects.filter(period_type='month').exclude(status='open')
                                   .values_list('year', 'month'))
        self._tokens = {}

    def branch_token(self, name, code) -> str:
        """The resolved branch, so a re-export gaining the code column keeps its groups and keys;
        an unknown branch stays apart under what the file says."""
        if (name, code) not in self._tokens:
            b = resolve_branch(name, code, _index=self.branches)
            self._tokens[(name, code)] = b.softech_branch_id if b else (code or normalize_ar(name))
        return self._tokens[(name, code)]

    def in_manual_set(self, codes) -> bool:
        others = set(codes) - self.links
        return bool(others) and any(others <= s for s in self.manual_sets)

    def usable(self, code) -> bool:
        a = self.accounts.get(code)
        return a is not None and a.is_active and a.is_posting

    def feed(self, code) -> str:
        return 'link' if code in self.links else effective_feed(self.accounts[code], self.fed)


# ── grouping ─────────────────────────────────────────────────────────────────

def _is_balanced(rows) -> bool:
    debit = sum((r.amount for r in rows if r.side == 'debit'), _ZERO)
    credit = sum((r.amount for r in rows if r.side == 'credit'), _ZERO)
    return debit == credit and debit > 0


def _merge_returns(buckets, rejected) -> list:
    """Credit-book fallback: per (date, book, branch), the unbalanced groups on return / discount
    accounts become one group when their union balances. -> [(rows, description, merged_by)]."""
    out, candidates = [], defaultdict(list)
    for key, rows in buckets.items():
        on_returns = {r.account_code for r in rows} <= _RETURN_ACCOUNTS
        if on_returns and not _is_balanced(rows) and key not in rejected:
            candidates[key[:3]].append(rows)
        else:
            out.append((rows, rows[0].description, ''))
    for day_groups in candidates.values():
        union = [r for rows in day_groups for r in rows]
        if _is_balanced(union) and any(r.account_code != _SUPPLIERS for r in union):
            with_text = sorted(day_groups, key=lambda rows: all(r.account_code == _SUPPLIERS for r in rows))
            desc = ' / '.join(dict.fromkeys(rows[0].description for rows in with_text if rows[0].description))
            out.append((sorted(union, key=lambda r: r.row_no), desc, MERGED_BY_DATE_BRANCH))
        else:
            out.extend((rows, rows[0].description, '') for rows in day_groups)
    return out


def _status(group, usable, lookups) -> str:
    if group.date < OPENING_DATE:
        return 'before_opening'
    if not usable:
        return 'unknown_account'
    others = {'manual'} if group.manual_set else group.feeds - {'link'}
    if others and 'manual' not in others:   # no manual line: a group we skip needs no one's attention
        return 'softech'
    if group.target_branch is None:
        return 'unknown_branch'
    if not group.balanced:
        return 'unbalanced'
    live = lookups.live_by_identity.get(_identity(group.key), ())
    if live and group.key not in {e.source_key for e in live}:
        group.existing_entry = live[0]
        return 'changed_since_import'   # the accountant reverses or deletes the old one, then re-imports
    # a draft there could never be approved; one imported before the close still reads `already_imported`
    if (group.date.year, group.date.month) in lookups.not_open_months and not live:
        return 'closed_period'
    return 'mixed' if others - {'manual'} else 'manual'


def _account_totals(rows, skip=()) -> dict:
    totals = defaultdict(lambda: [_ZERO, _ZERO])
    for r in rows:
        if r.account_code not in skip:
            totals[r.account_code][0 if r.side == 'debit' else 1] += r.amount
    return {code: tuple(t) for code, t in totals.items()}


def _flag_possible_duplicates(groups, lookups):
    """A group manual only through finance's list may be a transfer the engine already drafted from
    a SOFTECH voucher (Ruling P24): a live entry from any other source, same date and branch, with the
    same debit and credit on each of the group's accounts (link accounts aside) stops it until an
    accountant includes it. One query, over the file's date range and those accounts."""
    suspects = [g for g in groups if g.status == 'manual' and g.manual_set and g.feeds - {'manual', 'link'}
                and g.key not in {e.source_key for e in lookups.live_by_identity.get(_identity(g.key), ())}]
    if not suspects:
        return
    codes = {r.account_code for g in suspects for r in g.rows} - lookups.links
    lines = (LedgerLine.objects.select_related('entry', 'account')
             .filter(entry__status__in=('draft', 'approved'), entry__reverses__isnull=True,
                     entry__entry_date__gte=min(g.date for g in suspects),
                     entry__entry_date__lte=max(g.date for g in suspects), account__code__in=codes)
             .exclude(entry__source_type=SOURCE_TYPE))
    entries, totals, on_branch = {}, defaultdict(lambda: defaultdict(lambda: [_ZERO, _ZERO])), defaultdict(set)
    for ln in lines:
        entries[ln.entry_id] = ln.entry
        t = totals[ln.entry_id][ln.account.code]
        t[0] += ln.debit
        t[1] += ln.credit
        for branch_id in (ln.entry.branch_id, ln.branch_id):
            if branch_id:
                on_branch[(ln.entry.entry_date, branch_id)].add(ln.entry_id)
    for g in suspects:
        wanted = _account_totals(g.rows, skip=lookups.links)
        for entry_id in sorted(on_branch.get((g.date, g.target_branch.pk), ())):
            if all(tuple(totals[entry_id].get(c, (None, None))) == t for c, t in wanted.items()):
                g.status, g.existing_entry = 'possible_duplicate', entries[entry_id]
                break


def group_entries(rows, rejected=(), lookups=None) -> list:
    """`rejected`: `ParsedJournal.rejected`. A group that lost a reported row is never balanced."""
    lookups = lookups or _Lookups(rows)
    rejected = {(d, b, lookups.branch_token(name, code), desc) for d, b, name, code, desc in rejected}
    buckets = {}
    for r in rows:
        token = lookups.branch_token(r.branch_name, r.branch_code)
        buckets.setdefault((r.date, r.book, token, normalize_ar(r.description)), []).append(r)
    out = []
    for group_rows, description, merged_by in _merge_returns(buckets, rejected):
        first = group_rows[0]
        token = lookups.branch_token(first.branch_name, first.branch_code)
        g = JournalGroup(
            key=_source_key(first.date, first.book, token, group_rows, merged_by), date=first.date, book=first.book,
            branch=token, description=description, rows=group_rows, merged_by=merged_by,
            target_branch=resolve_branch(first.branch_name, first.branch_code, _index=lookups.branches))
        g.balanced = _is_balanced(group_rows) and (first.date, first.book, token,
                                                   normalize_ar(first.description)) not in rejected
        codes = {r.account_code for r in group_rows}
        usable = all(lookups.usable(c) for c in codes)
        g.feeds = {lookups.feed(c) for c in codes if c in lookups.accounts}
        g.manual_set = lookups.in_manual_set(codes)
        g.status = _status(g, usable, lookups)
        out.append(g)
    _flag_possible_duplicates(out, lookups)
    out.sort(key=lambda g: g.rows[0].row_no)
    return out


def _lines(group, lookups) -> list:
    """Plan 1 `save_draft` line dicts. The party is the one the account's party type asks for."""
    lines = []
    for r in group.rows:
        field_name = _PARTY_FIELD.get(lookups.accounts[r.account_code].party_type)
        lines.append({
            'account_code': r.account_code,
            'debit': r.amount if r.side == 'debit' else _ZERO,
            'credit': r.amount if r.side == 'credit' else _ZERO,
            'branch_id': group.target_branch.pk,
            'party_code': getattr(r, field_name) if field_name else '',
            'description': r.description[:500],
            'cheque_no': r.cheque_no,
            'due_date': r.due_date,
        })
    return lines


def _group_json(g) -> dict:
    return {'key': g.key, 'date': g.date, 'book': g.book, 'branch': g.branch,
            'branch_id': g.target_branch.pk if g.target_branch else None,
            'description': g.description, 'lines': len(g.rows), 'debit': g.debit, 'credit': g.credit,
            'accounts': sorted({r.account_code for r in g.rows}), 'balanced': g.balanced,
            'merged_by': g.merged_by, 'feeds': sorted(g.feeds), 'manual_set': g.manual_set, 'status': g.status,
            'existing_entry_id': g.existing_entry.pk if g.existing_entry else None,
            'existing_entry_number': g.existing_entry.number if g.existing_entry else None}


# ── preview ──────────────────────────────────────────────────────────────────

def _link_totals(rows, links) -> list:
    totals = defaultdict(lambda: [_ZERO, _ZERO])
    for r in rows:
        if r.account_code in links:
            totals[r.account_code][0 if r.side == 'debit' else 1] += r.amount
    return [{'code': code, 'debit': d, 'credit': c, 'net': d - c} for code, (d, c) in sorted(totals.items())]


def _softech_summary(groups) -> list:
    """What is being dropped because SOFTECH feeds it, per account set: finance checks this list."""
    sets = {}
    for g in groups:
        if g.status == 'softech':
            row = sets.setdefault(frozenset(r.account_code for r in g.rows), [0, _ZERO, _ZERO])
            row[0] += 1
            row[1] += g.debit
            row[2] += g.credit
    return [{'accounts': sorted(codes), 'groups': n, 'debit': d, 'credit': c}
            for codes, (n, d, c) in sorted(sets.items(), key=lambda kv: (-kv[1][0], sorted(kv[0])))]


def _party_missing(groups, lookups) -> int:
    """Lines of importable groups approval would refuse: blank party on a requires_party account."""
    n = 0
    for g in groups:
        if g.status in ('manual', *INCLUDABLE):
            for r in g.rows:
                account = lookups.accounts[r.account_code]
                field_name = _PARTY_FIELD.get(account.party_type)
                if account.requires_party and not (getattr(r, field_name) if field_name else ''):
                    n += 1
    return n


def preview(path, sheet_name=None, book=None, max_rows=None) -> dict:
    """What an import would do. Saves nothing."""
    parsed = parse_journal(path, sheet_name=sheet_name, book=book, max_rows=max_rows)
    lookups = _Lookups(parsed.rows)
    groups = group_entries(parsed.rows, parsed.rejected, lookups=lookups)
    manual = sorted(c for c in lookups.accounts if lookups.usable(c) and lookups.feed(c) == 'manual')
    links = _link_totals(parsed.rows, lookups.links)
    warnings = list(parsed.warnings)
    if parsed.book == 'mixed':   # with one book, the other half of every link entry is in the other file
        warnings += [f'حساب الوسيط {ln["code"]}: الصافي مش صفر في ملف فيه الدفترين.' for ln in links if ln['net']]
    party_missing = _party_missing(groups, lookups)
    if party_missing:
        warnings.append(f'{party_missing} سطر من غير كود طرف على حساب بيطلبه: الاعتماد هيرفضه لحد ما يتكمل.')
    counts = dict.fromkeys(STATUSES, 0)
    for g in groups:
        counts[g.status] += 1
    return {
        'book': parsed.book,
        'manual_accounts': [{'code': c, 'name': lookups.accounts[c].name} for c in manual],
        'groups': [_group_json(g) for g in groups],
        'counts': counts,
        'merged_count': sum(1 for g in groups if g.merged_by),
        'balanced_count': sum(1 for g in groups if g.balanced),
        'skipped_zero': parsed.skipped_zero,
        'skipped': parsed.skipped,
        'link_accounts': links,
        'softech_summary': _softech_summary(groups),
        'party_missing': party_missing,
        'warnings': warnings,
        'totals': {'rows': len(parsed.rows), 'groups': len(groups),
                   'debit': sum((g.debit for g in groups), _ZERO),
                   'credit': sum((g.credit for g in groups), _ZERO)},
    }


# ── import ───────────────────────────────────────────────────────────────────

def _live_keys(keys) -> set:
    keys, live = list(keys), set()
    for i in range(0, len(keys), 1000):
        live.update(LedgerEntry.objects.filter(source_key__in=keys[i:i + 1000], status__in=('draft', 'approved'))
                    .values_list('source_key', flat=True))
    return live


def _draft(group, lines, user, parked) -> LedgerEntry:
    """One draft, and in the same transaction the end of the group's parked exception if it has one."""
    with transaction.atomic():
        entry = save_draft(user=user, entry_date=group.date, description=group.description[:500], lines=lines,
                           book=group.book, branch=group.target_branch, source_type=SOURCE_TYPE,
                           source_key=group.key)
        if group.key in parked:
            plan2_adapter.settle_parked_manual_entry(group.key, entry=entry, user=user)
    return entry


def import_entries(path, *, user, include_mixed=(), sheet_name=None, book=None, max_rows=None) -> dict:
    """One draft per importable group; `include_mixed` keys (mixed or possible_duplicate groups) are
    imported with all their lines. A mixed group not included is parked once. Importing the same group
    again creates nothing."""
    parsed = parse_journal(path, sheet_name=sheet_name, book=book, max_rows=max_rows)
    lookups = _Lookups(parsed.rows)
    groups = group_entries(parsed.rows, parsed.rejected, lookups=lookups)
    include = set(include_mixed)
    live = _live_keys(g.key for g in groups if g.status in ('manual', *INCLUDABLE))
    parked = plan2_adapter.parked_manual_keys()

    counts = dict.fromkeys(('imported', 'included', 'already_imported', 'parked', 'parked_existing', 'softech',
                            *NOT_IMPORTABLE), 0)
    parked_keys, failed = [], []
    not_imported = defaultdict(list)
    for g in groups:
        included = g.status in INCLUDABLE and g.key in include
        if g.status == 'softech':
            counts['softech'] += 1
        elif g.status in NOT_IMPORTABLE and not included:
            counts[g.status] += 1
            not_imported[g.status].append(_group_json(g))
        elif g.key in live:
            counts['already_imported'] += 1
        elif g.status == 'manual' or included:
            try:
                _draft(g, _lines(g, lookups), user, parked)
                counts['included' if included else 'imported'] += 1
            except LedgerError as e:
                if e.code == 'source_conflict':   # landed since the check above
                    counts['already_imported'] += 1
                else:
                    failed.append({'key': g.key, 'code': e.code})
        else:
            state = plan2_adapter.park_mixed_manual_entry(
                key=g.key, entry_date=g.date, branch_code=g.target_branch.softech_branch_id, book=g.book,
                description=g.description, lines=_canon(_lines(g, lookups)), user=user)
            counts['parked' if state == 'created' else 'parked_existing'] += 1
            if state in ('created', 'open'):
                parked_keys.append(g.key)

    mixed_keys = {g.key for g in groups if g.status in INCLUDABLE}
    summary = {**counts, 'failed': len(failed), 'skipped_zero': parsed.skipped_zero, 'skipped': len(parsed.skipped)}
    _audit('gl_manual_import', user=user, obj=None, new_data=summary,
           extra={'file': os.path.basename(str(path)), 'book': parsed.book, 'include_mixed': sorted(include)},
           note='import of finance manual journal entries')
    return {**counts, 'book': parsed.book, 'skipped_zero': parsed.skipped_zero, 'skipped': parsed.skipped,
            'warnings': parsed.warnings, 'parked_keys': parked_keys, 'not_imported': dict(not_imported),
            'failed': failed, 'include_unmatched': sorted(include - mixed_keys),
            'softech_summary': _softech_summary(groups), 'party_missing': _party_missing(groups, lookups)}
