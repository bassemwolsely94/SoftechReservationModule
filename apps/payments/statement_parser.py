"""
apps/payments/statement_parser.py — read a bank / wallet statement file into line dicts.

Pure and deterministic: it only reads the file. It never touches ExternalPayment, matching or
SOFTECH — the upload view stores the lines and «تشغيل المطابقة» matches them later.

    lines, warnings = parse_statement(fileobj, 'statement.xlsx', date_from, date_to)

Each line is a dict with BankStatementLine field names (transaction_date, value_date, reference,
description, debit, credit, balance). A missing required column, an unreadable date or amount on a
money row, or an unsupported format raises StatementParseError with an Arabic message.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from core.upload_safety import capped_rows

MAX_STATEMENT_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = ('csv', 'xlsx', 'xls')
HEADER_SEARCH_ROWS = 15


UNREADABLE_FILE = 'تعذّر قراءة الملف — تأكد أنه CSV أو Excel سليم'


class StatementParseError(ValueError):
    """The file cannot be read as a statement; the message is shown to the user as-is."""


# ── Text normalisation ───────────────────────────────────────────────────────────────────────

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _norm(text) -> str:
    """Lower-case, Arabic letter variants folded, punctuation → space, spaces collapsed."""
    s = str(text or '').translate(_DIGITS).lower()
    s = s.replace('ـ', '')                                   # tatweel
    s = re.sub('[أإآٱ]', 'ا', s).replace('ى', 'ي').replace('ة', 'ه')
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ── Header aliases ───────────────────────────────────────────────────────────────────────────

HEADER_ALIASES = {
    'date':        ['التاريخ', 'تاريخ الحركة', 'تاريخ العملية', 'Date', 'Transaction Date', 'Txn Date',
                    'Posting Date'],
    'value_date':  ['تاريخ القيمة', 'Value Date'],
    'reference':   ['المرجع', 'رقم المرجع', 'رقم العملية', 'Reference', 'Ref', 'Ref No', 'Transaction ID',
                    'Cheque No'],
    'description': ['البيان', 'الوصف', 'التفاصيل', 'Description', 'Details', 'Narrative', 'Remarks'],
    'debit':       ['مدين', 'سحب', 'منه', 'Debit', 'Withdrawal', 'Dr'],
    'credit':      ['دائن', 'إيداع', 'له', 'Credit', 'Deposit', 'Cr'],
    'amount':      ['المبلغ', 'Amount'],
    'balance':     ['الرصيد', 'Balance'],
}
_ALIAS_TO_FIELD = {_norm(a): field for field, aliases in HEADER_ALIASES.items() for a in aliases}

# Footer / summary rows. Balance phrases are skipped wherever they sit; total phrases only when
# the row has no readable date (a dated "Total…" description is a real transaction).
_BALANCE_PHRASES = [_norm(p) for p in (
    'Opening balance', 'Closing balance', 'Balance brought forward', 'Balance carried forward',
    'Brought forward', 'Carried forward', 'رصيد افتتاحي', 'الرصيد الافتتاحي', 'رصيد ختامي',
    'الرصيد الختامي', 'رصيد أول المدة', 'رصيد آخر المدة')]
_TOTAL_PHRASES = [_norm(p) for p in (
    'الإجمالي', 'إجمالي', 'المجموع', 'Total', 'Grand total', 'Sub total', 'Subtotal')]


def _starts_with_phrase(text: str, phrases) -> bool:
    return any(text == p or text.startswith(p + ' ') for p in phrases)


def _map_header(row) -> dict:
    """{field: column index} for the cells of `row` that are known aliases (first one wins)."""
    cols = {}
    for i, cell in enumerate(row):
        field = _ALIAS_TO_FIELD.get(_norm(cell))
        if field and field not in cols:
            cols[field] = i
    return cols


def _is_header(cols: dict) -> bool:
    return 'date' in cols and bool({'debit', 'credit', 'amount'} & cols.keys())


# ── Cell values ──────────────────────────────────────────────────────────────────────────────

_EXCEL_EPOCH = date(1899, 12, 30)
_MONTHS = {m: i for i, m in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), start=1)}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def parse_date(v):
    """A date from a datetime cell, an Excel serial, or text (day-first). None if unreadable."""
    if _blank(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return _serial(v)
    s = str(v).translate(_DIGITS).strip()
    s = re.sub(r'[\sT]+\d{1,2}:\d{2}.*$', '', s)               # drop a time part
    if re.fullmatch(r'\d{5}(\.\d+)?', s):
        return _serial(float(s))
    try:
        m = re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})', s)
        if m:                                                   # day-first (Egypt)
            y = int(m[3])
            return date(y + 2000 if y < 100 else y, int(m[2]), int(m[1]))
        m = re.fullmatch(r'(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ,]+(\d{2}|\d{4})', s)
        if m and m[2].lower() in _MONTHS:
            y = int(m[3])
            return date(y + 2000 if y < 100 else y, _MONTHS[m[2].lower()], int(m[1]))
    except ValueError:
        return None
    return None


def _serial(n: float):
    if 20000 <= n <= 80000:                                     # 1954 … 2119
        return _EXCEL_EPOCH + timedelta(days=int(n))
    return None


_CURRENCY = re.compile(r'(ج\s*\.?\s*م\.?|جنيه(ات)?|جم|egp|l\.?e\.?|e£|£)', re.IGNORECASE)


def parse_amount(v):
    """Signed Decimal (2 dp) from a number or text: thousands separators and currency text dropped,
    Arabic-Indic digits converted, (123) and 123- read as negative. Blank → Decimal 0.
    Raises ValueError on anything else."""
    if _blank(v):
        return Decimal('0')
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        s = str(v).translate(_DIGITS).replace('٫', '.').replace('٬', '').strip()
        s = _CURRENCY.sub('', s)
        s = s.replace(',', '').replace(' ', '').replace(' ', '')
        neg = False
        if s.startswith('(') and s.endswith(')'):
            neg, s = True, s[1:-1]
        if s.endswith('-'):
            neg, s = True, s[:-1]
        if s.startswith('-'):
            neg, s = not neg, s[1:]
        if s.startswith('+'):
            s = s[1:]
        if not re.fullmatch(r'\d+(\.\d+)?|\.\d+', s):
            raise ValueError(v)
        d = Decimal(s)
        if neg:
            d = -d
    try:
        return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(v)


def _text(v, limit: int) -> str:
    if _blank(v):
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)                                              # 123456.0 → "123456"
    if isinstance(v, (datetime, date)):
        v = v.isoformat()
    return str(v).strip()[:limit]


# ── File readers ─────────────────────────────────────────────────────────────────────────────

def _read_csv(data: bytes):
    for enc in ('utf-8-sig', 'cp1256'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise StatementParseError('تعذّر قراءة ملف CSV — احفظه بترميز UTF-8.')
    if '\x00' in text:                                         # a binary / corrupt file
        raise StatementParseError(UNREADABLE_FILE)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    return list(capped_rows(csv.reader(io.StringIO(text), dialect)))


def _read_xlsx(data: bytes):
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise StatementParseError('تعذّر فتح ملف Excel — تأكد أنه ملف xlsx سليم.')
    try:
        ws = wb.worksheets[0]
        return [list(r) for r in capped_rows(ws.iter_rows(values_only=True))]
    finally:
        wb.close()


def _read_xls(data: bytes):
    try:
        import xlrd
    except ImportError:
        raise StatementParseError('صيغة xls القديمة غير مدعومة — احفظ الملف بصيغة xlsx أو csv.')
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception:
        raise StatementParseError('تعذّر فتح ملف Excel — احفظ الملف بصيغة xlsx أو csv.')
    sh = book.sheet_by_index(0)
    rows = []
    for r in capped_rows(range(sh.nrows)):
        row = []
        for c in range(sh.ncols):
            cell = sh.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
            else:
                row.append(cell.value)
        rows.append(row)
    return rows


def file_extension(filename: str) -> str:
    return (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''


def read_rows(data: bytes, filename: str):
    ext = file_extension(filename)
    if ext == 'csv':
        return _read_csv(data)
    if ext == 'xlsx':
        return _read_xlsx(data)
    if ext == 'xls':
        return _read_xls(data)
    raise StatementParseError('نوع الملف غير مدعوم — ارفع ملف csv أو xlsx.')


# ── Main entry ───────────────────────────────────────────────────────────────────────────────

def _cell(row, cols, field):
    i = cols.get(field)
    return row[i] if i is not None and i < len(row) else None


def parse_statement(fileobj, filename: str, statement_from=None, statement_to=None):
    """(lines, warnings) — see the module docstring."""
    try:
        fileobj.seek(0)
    except Exception:
        pass
    data = fileobj.read()
    try:
        rows = read_rows(data, filename)
    except ValueError as exc:                                   # capped_rows / parse errors
        raise StatementParseError(str(exc)) from exc

    header_idx, cols = None, {}
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        found = _map_header(row)
        if _is_header(found):
            header_idx, cols = i, found
            break
    if header_idx is None:
        candidates = [r for r in rows[:HEADER_SEARCH_ROWS] if any(not _blank(c) for c in r)]
        best = max(candidates, key=lambda r: sum(1 for c in r if isinstance(c, str) and c.strip()),
                   default=[])
        seen = '، '.join(f'«{str(c).strip()}»' for c in best if not _blank(c)) or 'لا شيء'
        raise StatementParseError(
            'لم أجد أعمدة الكشف المطلوبة: عمود التاريخ، ومعه «مدين» و«دائن» أو عمود «المبلغ». '
            f'العناوين الموجودة في الملف: {seen}.')

    lines, out_of_period, zero_rows, notes = [], 0, 0, 0
    for n, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if all(_blank(c) for c in row):
            continue
        labels = [_norm(_cell(row, cols, f)) for f in ('date', 'reference', 'description')]
        if any(_starts_with_phrase(t, _BALANCE_PHRASES) for t in labels if t):
            continue
        raw_date = _cell(row, cols, 'date')
        tx_date = parse_date(raw_date)
        if tx_date is None:
            if any(_starts_with_phrase(t, _TOTAL_PHRASES) for t in labels if t):
                continue
            has_money = False
            for f in ('debit', 'credit', 'amount'):
                try:
                    has_money = has_money or parse_amount(_cell(row, cols, f)) != 0
                except ValueError:
                    pass
            if not has_money:
                notes += 1                                      # a note / footer line without money
                continue
            raise StatementParseError(f'السطر {n}: التاريخ «{_text(raw_date, 40)}» غير مفهوم — '
                                      'استخدم يوم/شهر/سنة أو سنة-شهر-يوم.')

        def money(field):
            v = _cell(row, cols, field)
            try:
                return parse_amount(v)
            except ValueError:
                raise StatementParseError(f'السطر {n}: المبلغ «{_text(v, 40)}» غير مفهوم.')

        debit = credit = Decimal('0')
        if 'debit' in cols or 'credit' in cols:
            # the column decides the side, never the sign (some banks print debits as negatives)
            debit, credit = abs(money('debit')), abs(money('credit'))
        else:
            a = money('amount')
            credit, debit = (a, Decimal('0')) if a > 0 else (Decimal('0'), -a)
        if debit == 0 and credit == 0:
            zero_rows += 1
            continue

        balance = None
        if 'balance' in cols and not _blank(_cell(row, cols, 'balance')):
            try:
                balance = parse_amount(_cell(row, cols, 'balance'))
            except ValueError:
                balance = None

        if (statement_from and tx_date < statement_from) or (statement_to and tx_date > statement_to):
            out_of_period += 1
        lines.append({
            'transaction_date': tx_date,
            'value_date':       parse_date(_cell(row, cols, 'value_date')),
            'reference':        _text(_cell(row, cols, 'reference'), 200),
            'description':      _text(_cell(row, cols, 'description'), 500),
            'debit':            debit,
            'credit':           credit,
            'balance':          balance,
        })

    warnings = []
    if out_of_period:
        warnings.append(f'{out_of_period} سطر تاريخه خارج فترة الكشف ({statement_from} ← {statement_to}) — '
                        'اتحفظ ولكن راجع الفترة.')
    if zero_rows:
        warnings.append(f'تم تجاهل {zero_rows} سطر بدون مبلغ.')
    if notes:
        warnings.append(f'تم تجاهل {notes} سطر بدون تاريخ ولا مبلغ (ملاحظات / تذييل).')
    if not lines:
        raise StatementParseError('الملف لا يحتوي على أي حركة بمبلغ وتاريخ تحت صف العناوين.')
    return lines, warnings
