"""Jan–Aug 2026 validation of the ledger against finance's workbook (finance-gl Plan 3, Task 9).

Read-only: nothing here writes to the ledger or to SOFTECH. The workbook's pivots carry signed
balances (debit +, credit −), the same sign as the ledger's debit − credit, so the two compare
directly. Only differences are listed; each account that differs gets a totals row. The accountants
write their explanation of every difference in the export (spec §11 step 4).

A workbook amount that is float noise from Excel (more than 2 decimals) is read to the cent once,
ROUND_HALF_UP — the ledger side is already exact cents.
"""
from __future__ import annotations

import datetime
import math
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO

import openpyxl
from django.db.models import Sum
from django.db.models.functions import Coalesce, ExtractMonth
from openpyxl.styles import Alignment, Font
from openpyxl.utils.exceptions import InvalidFileException

from core.export_safety import neutralise_formulas

from apps.branches.models import Branch
from apps.finance.models import GLAccount, GLParty

from .balances import COUNTED, YEAR_END_CLOSING, _base
from .exports import HEAD_FILL, MONEY, _bold_row, _num
from .manual_import import _branch_index, resolve_branch
from .names import normalize_ar

START = datetime.date(2026, 1, 1)
DEFAULT_THROUGH = datetime.date(2026, 8, 31)
TOLERANCE = Decimal('0.01')
HEADER_SCAN_ROWS = 20
_CENT = Decimal('0.01')
_ZERO = Decimal('0.00')

BRANCH_SHEET = 'ميزان الفروع'
MONTHLY_SHEET = 'المشتريات والمبيعات'
# sheet -> (kind, GL account, GLParty type, the header label of the code column)
PARTY_SHEETS = {
    'الموردين': ('suppliers', '2341', 'supplier', 'suppliar code'),
    'الدائنون': ('creditors', '2351', 'supplier', 'suppliar code'),
    'العملاء': ('customers', '1341', 'customer', 'customer code'),
    'مدينون': ('employees', '1351', 'employee', 'كود الموظف'),
}
_CODE_LABEL = normalize_ar('رقم العملية')
_NAME_LABEL = normalize_ar('Trans. Name')
_GRAND = normalize_ar('Grand Total')
_PARTY_LABELS = {normalize_ar(s[3]) for s in PARTY_SHEETS.values()}

MESSAGES = {
    'xls_not_supported': 'الملف بصيغة .xls القديمة — احفظه من Excel بصيغة .xlsx ثم أعد المحاولة.',
    'unreadable': 'تعذّر قراءة الملف — تأكد أنه ملف Excel بصيغة .xlsx سليم.',
    'sheet_not_found': 'الشيت المطلوب غير موجود في الملف',
    'header_not_found': 'لم يتم العثور على صف العناوين في الشيت',
}


class WorkbookError(Exception):
    def __init__(self, code: str, detail: str = ''):
        self.code = code
        self.message = MESSAGES.get(code, code) + (f': «{detail}»' if detail else '')
        super().__init__(self.message)


@dataclass(slots=True)
class BranchTBRow:
    code: str
    branch_label: str
    balance: Decimal


@dataclass(slots=True)
class MonthRow:
    code: str
    month: int
    amount: Decimal


@dataclass(slots=True)
class PartyRow:
    party_code: str
    name: str
    balance: Decimal


# ── workbook reading ─────────────────────────────────────────────────────────

def _open(path):
    if str(path).lower().endswith('.xls'):
        raise WorkbookError('xls_not_supported')
    try:
        return openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise WorkbookError('unreadable')


def _sheet(wb, name):
    """Sheet names carry a trailing space in finance's file: match on `normalize_ar`."""
    want = normalize_ar(name)
    for ws in wb.worksheets:
        if normalize_ar(ws.title) == want:
            return ws
    return None


def _norm_cell(v) -> str:
    return normalize_ar(v) if isinstance(v, str) else ''


def _rows_after_header(ws, labels):
    """-> (header cells, data rows) of the first row within the scan that holds one of `labels`."""
    rows = ws.iter_rows(values_only=True)
    for i, cells in enumerate(rows):
        if i >= HEADER_SCAN_ROWS:
            break
        if any(_norm_cell(c) in labels for c in cells):
            return list(cells), rows
    raise WorkbookError('header_not_found', ws.title)


def _code(v):
    """An account or party code cell: 5101.0 -> '5101'. Text such as a total label -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            v = float(v)
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (not math.isfinite(v) or v != int(v)):
            return None
        return str(int(v))
    return None


def _amount(v) -> Decimal:
    if v is None or v == '' or isinstance(v, bool):
        return _ZERO
    try:
        return Decimal(str(v).strip()).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return _ZERO


def _cell(cells, pos):
    return cells[pos] if pos is not None and pos < len(cells) else None


def _is_total(*cells) -> bool:
    return any(isinstance(c, str) and c.strip().lower().endswith('total') for c in cells)


def _pivot_rows(ws):
    """Account rows of a `رقم العملية` pivot -> (header cells, [(code, name, cells)]). The group sits
    only on its first row and the `Total` / `Grand Total` rows are skipped."""
    header, rows = _rows_after_header(ws, {_CODE_LABEL})
    norm = [_norm_cell(c) for c in header]
    code_i, name_i = norm.index(_CODE_LABEL), (norm.index(_NAME_LABEL) if _NAME_LABEL in norm else None)
    out = []
    for cells in rows:
        cells = list(cells)
        if _is_total(*cells[:code_i + 1]):
            continue
        code = _code(_cell(cells, code_i))
        if code:
            name = _cell(cells, name_i)
            out.append((code, str(name).strip() if name is not None else '', cells))
    return header, norm, out, (name_i if name_i is not None else code_i)


def parse_branch_trial_balance(path, sheet_name=BRANCH_SHEET) -> list[BranchTBRow]:
    """«ميزان الفروع»: one column per finance branch name, between `Trans. Name` and `Grand Total`."""
    wb = _open(path)
    try:
        ws = _sheet(wb, sheet_name)
        if ws is None:
            raise WorkbookError('sheet_not_found', sheet_name)
        header, norm, rows, name_i = _pivot_rows(ws)
        branch_cols = []
        for pos in range(name_i + 1, len(header)):
            label = header[pos]
            if norm[pos] == _GRAND:
                break
            if isinstance(label, str) and label.strip():
                branch_cols.append((pos, label.strip()))
        return [BranchTBRow(code, label, _amount(_cell(cells, pos)))
                for code, _name, cells in rows for pos, label in branch_cols
                if _cell(cells, pos) not in (None, '')]
    finally:
        wb.close()


def _month(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and 1 <= v <= 12 else None


def parse_monthly_sheet(path, sheet_name=MONTHLY_SHEET) -> list[MonthRow]:
    """«المشتريات والمبيعات»: integer month headers (1..12)."""
    wb = _open(path)
    try:
        ws = _sheet(wb, sheet_name)
        if ws is None:
            raise WorkbookError('sheet_not_found', sheet_name)
        header, _norm, rows, name_i = _pivot_rows(ws)
        months = [(pos, _month(label)) for pos, label in enumerate(header) if pos > name_i and _month(label)]
        return [MonthRow(code, month, _amount(_cell(cells, pos)))
                for code, _name, cells in rows for pos, month in months
                if _cell(cells, pos) not in (None, '')]
    finally:
        wb.close()


def parse_party_sheet(path, sheet_name) -> list[PartyRow]:
    """A party pivot: the code column is found by its label, the name is the cell to its right."""
    wb = _open(path)
    try:
        ws = _sheet(wb, sheet_name)
        if ws is None:
            raise WorkbookError('sheet_not_found', sheet_name)
        header, rows = _rows_after_header(ws, _PARTY_LABELS)
        norm = [_norm_cell(c) for c in header]
        code_i = next(i for i, n in enumerate(norm) if n in _PARTY_LABELS)
        pos = {n: i for i, n in enumerate(norm) if n}
        grand, debt, credit = pos.get(_GRAND), pos.get('debt', pos.get('debit')), pos.get('credit')
        out = []
        for cells in rows:
            cells = list(cells)
            code = _code(_cell(cells, code_i))
            if not code or _is_total(*cells[:code_i + 2]):
                continue
            if grand is not None and _cell(cells, grand) not in (None, ''):
                balance = _amount(_cell(cells, grand))
            else:
                balance = _amount(_cell(cells, debt)) - abs(_amount(_cell(cells, credit)))
            name = _cell(cells, code_i + 1)
            out.append(PartyRow(code, str(name).strip() if name is not None else '', balance))
        return out
    finally:
        wb.close()


# ── ledger side ──────────────────────────────────────────────────────────────

def _net(qs, *keys):
    """{key tuple: debit − credit} of a line queryset."""
    out = defaultdict(lambda: _ZERO)
    for r in qs.values(*keys).annotate(d=Sum('debit'), c=Sum('credit')):
        out[tuple(r[k] for k in keys)] += (r['d'] or _ZERO) - (r['c'] or _ZERO)
    return out


def _ledger_lines(start, end):
    return (_base().filter(entry__entry_date__gte=start, entry__entry_date__lte=end)
            .exclude(YEAR_END_CLOSING))


def _branch_label(b) -> str:
    if b is None:
        return 'بدون فرع'
    sid = (b.softech_branch_id or '').strip()
    return f'{sid} · {b.name}' if sid else b.name


def _row(diff_keys, ledger, workbook):
    return {**diff_keys, 'ledger': ledger, 'workbook': workbook, 'difference': ledger - workbook}


def _differs(d: Decimal) -> bool:
    return abs(d) > TOLERANCE


def _account_totals(rows, names):
    """One totals row per account that has a difference row."""
    acc = {}
    for r in rows:
        t = acc.setdefault(r['code'], {'code': r['code'], 'name': names.get(r['code'], r.get('name', '')),
                                       'ledger': _ZERO, 'workbook': _ZERO, 'difference': _ZERO})
        for k in ('ledger', 'workbook', 'difference'):
            t[k] += r[k]
    return sorted(acc.values(), key=lambda t: t['code'])


def _ytd(path, through, names, unmapped):
    """Per account and branch. Totals compare an account's ledger total with the sum of every branch
    column of the workbook, so a branch that could not be mapped still shows."""
    idx = _branch_index()
    branches = {b.pk: b for b in Branch.objects.all()}
    workbook, wb_total = defaultdict(lambda: _ZERO), defaultdict(lambda: _ZERO)
    for r in parse_branch_trial_balance(path):
        b = resolve_branch(r.branch_label, _index=idx)
        wb_total[r.code] += r.balance
        if b is None:
            if r.branch_label not in unmapped:
                unmapped.append(r.branch_label)
            continue
        workbook[(r.code, b.pk)] += r.balance
    lines = _ledger_lines(START, through).annotate(bid=Coalesce('branch_id', 'entry__branch_id'))
    ledger = _net(lines, 'account__code', 'bid')
    rows = []
    for code, bid in sorted(set(ledger) | set(workbook), key=lambda k: (k[0], k[1] or 0)):
        led, wbk = ledger.get((code, bid), _ZERO), workbook.get((code, bid), _ZERO)
        if _differs(led - wbk):
            rows.append(_row({'code': code, 'name': names.get(code, ''),
                              'branch': _branch_label(branches.get(bid))}, led, wbk))
    ledger_total = defaultdict(lambda: _ZERO)
    for (code, _bid), v in ledger.items():
        ledger_total[code] += v
    # a total row for every account with a branch difference or a total that differs (an unmapped branch)
    totals = [{'code': c, 'name': names.get(c, ''), 'ledger': ledger_total[c], 'workbook': wb_total[c],
               'difference': ledger_total[c] - wb_total[c]}
              for c in sorted(set(ledger_total) | set(wb_total))
              if c in {r['code'] for r in rows} or _differs(ledger_total[c] - wb_total[c])]
    return rows, totals


def _monthly(path, through, names):
    end = min(through, datetime.date(2026, 12, 31))
    workbook = defaultdict(lambda: _ZERO)
    for r in parse_monthly_sheet(path):
        if r.month <= end.month:
            workbook[(r.code, r.month)] += r.amount
    codes = {c for c, _m in workbook}
    lines = (_ledger_lines(START, end).filter(account__code__in=codes)
             .annotate(month=ExtractMonth('entry__entry_date')))
    ledger = _net(lines, 'account__code', 'month')
    rows = []
    for code, month in sorted(set(ledger) | set(workbook)):
        led, wbk = ledger.get((code, month), _ZERO), workbook.get((code, month), _ZERO)
        if _differs(led - wbk):
            rows.append(_row({'code': code, 'name': names.get(code, ''), 'month': month}, led, wbk))
    return rows, _account_totals(rows, names)


def _parties(path, through):
    rows, totals, missing, unmapped = [], [], [], []
    wb = _open(path)
    try:
        present = {name for name in PARTY_SHEETS if _sheet(wb, name) is not None}
    finally:
        wb.close()
    for sheet, (kind, account, party_type, _label) in PARTY_SHEETS.items():
        if sheet not in present:
            missing.append(sheet)
            continue
        workbook, names = defaultdict(lambda: _ZERO), {}
        for r in parse_party_sheet(path, sheet):
            workbook[r.party_code] += r.balance
            names.setdefault(r.party_code, r.name)
        ledger = _net(_ledger_lines(START, through).filter(account__code=account), 'party_code')
        ledger = {k[0]: v for k, v in ledger.items()}
        known = set(GLParty.objects.filter(party_type=party_type, code__in=workbook).values_list('code', flat=True))
        unmapped += [{'kind': kind, 'party_code': c, 'name': names[c]} for c in sorted(workbook) if c not in known]
        kind_rows = []
        for code in sorted(set(ledger) | set(workbook)):
            led, wbk = ledger.get(code, _ZERO), workbook.get(code, _ZERO)
            if _differs(led - wbk):
                kind_rows.append(_row({'kind': kind, 'party_code': code, 'name': names.get(code, '')}, led, wbk))
        rows += kind_rows
        led_total, wbk_total = sum(ledger.values(), _ZERO), sum(workbook.values(), _ZERO)
        totals.append({'kind': kind, 'account': account, 'ledger': led_total, 'workbook': wbk_total,
                       'difference': led_total - wbk_total, 'differences': len(kind_rows)})
    return rows, totals, missing, unmapped


def validate(path, *, through: datetime.date = DEFAULT_THROUGH) -> dict:
    names = dict(GLAccount.objects.values_list('code', 'name'))
    unmapped = []
    ytd, ytd_totals = _ytd(path, through, names, unmapped)
    monthly, monthly_totals = _monthly(path, through, names)
    parties, party_totals, missing, unmapped_parties = _parties(path, through)
    wb_codes = {r.code for r in parse_branch_trial_balance(path)} | {r.code for r in parse_monthly_sheet(path)}
    unknown = sorted(c for c in wb_codes if c not in names)
    return {
        'through': through.isoformat(),
        'ytd': ytd, 'monthly': monthly, 'parties': parties,
        'unmapped_branches': unmapped, 'unknown_accounts': unknown,
        'unmapped_parties': unmapped_parties, 'missing_sheets': missing,
        'totals': {'ytd': ytd_totals, 'monthly': monthly_totals, 'parties': party_totals,
                   'differences': len(ytd) + len(monthly) + len(parties)},
    }


# ── export ───────────────────────────────────────────────────────────────────

def _fill(ws, headers, widths):
    ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for i, w in enumerate(widths, start=1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal='center')
        ws.column_dimensions[c.column_letter].width = w
    ws.freeze_panes = 'A2'


def _money_cols(ws, cols):
    for row in ws.iter_rows(min_row=2):
        for i in cols:
            if isinstance(row[i].value, (int, float)):
                row[i].number_format = MONEY


def export_validation(result: dict) -> bytes:
    """xlsx: «حسب الفرع», «شهري» and «الأطراف», each with an empty «التفسير» column."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sheets = (
        ('حسب الفرع', ['الكود', 'الحساب', 'الفرع', 'دفتر الأستاذ', 'ملف المالية', 'الفرق', 'التفسير'],
         [10, 34, 26, 18, 18, 18, 50], result['ytd'], result['totals']['ytd'],
         lambda r, total: [r['code'], r['name'], 'الإجمالى' if total else r['branch']]),
        ('شهري', ['الكود', 'الحساب', 'الشهر', 'دفتر الأستاذ', 'ملف المالية', 'الفرق', 'التفسير'],
         [10, 34, 10, 18, 18, 18, 50], result['monthly'], result['totals']['monthly'],
         lambda r, total: [r['code'], r['name'], 'الإجمالى' if total else r['month']]),
    )
    for title, headers, widths, rows, totals, lead in sheets:
        sh = wb.create_sheet(title)
        _fill(sh, headers, widths)
        for t in totals:   # rows are sorted by code: each account's rows, then its totals row
            for r in (x for x in rows if x['code'] == t['code']):
                sh.append(lead(r, False) + [_num(r['ledger']), _num(r['workbook']), _num(r['difference']), ''])
            sh.append(lead(t, True) + [_num(t['ledger']), _num(t['workbook']), _num(t['difference']), ''])
            _bold_row(sh, sh.max_row)
        _money_cols(sh, (3, 4, 5))
    sh = wb.create_sheet('الأطراف')
    _fill(sh, ['النوع', 'الكود', 'الاسم', 'دفتر الأستاذ', 'ملف المالية', 'الفرق', 'التفسير'],
          [14, 12, 36, 18, 18, 18, 50])
    for r in result['parties']:
        sh.append([r['kind'], r['party_code'], r['name'], _num(r['ledger']), _num(r['workbook']),
                   _num(r['difference']), ''])
    for t in result['totals']['parties']:
        sh.append([t['kind'], '', 'الإجمالى', _num(t['ledger']), _num(t['workbook']), _num(t['difference']), ''])
        _bold_row(sh, sh.max_row)
    _money_cols(sh, (3, 4, 5))
    buf = BytesIO()
    neutralise_formulas(wb).save(buf)
    return buf.getvalue()
