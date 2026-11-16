"""Parse an uploaded issue (doc 125) spreadsheet into rows, and turn rows into RpaLine records."""
import csv
import datetime
import io
import re
from decimal import Decimal, InvalidOperation

from core.upload_safety import capped_rows

from .matching import match_items, normalise_code

HEADER_ALIASES = {
    'itemcode': ('كود', 'كود الصنف', 'itemcode', 'item code', 'code'),
    'qty': ('كمية', 'الكمية', 'qty', 'quantity'),
    'expiry': ('صلاحية', 'تاريخ الصلاحية', 'expiry', 'exp'),
}
BAD_EXPIRY = 'تاريخ صلاحية غير مفهوم'


def _col_map(header):
    names = {}
    for idx, cell in enumerate(header):
        key = str(cell or '').strip().lower()
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases and field not in names:
                names[field] = idx
    return names


def _cell(row, idx):
    return row[idx] if idx is not None and idx < len(row) else None


def _text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _blank(v):
    return v is None or str(v).strip() == ''


def _iter_raw_rows(file_bytes, filename):
    if filename.lower().endswith('.csv'):
        yield from csv.reader(io.StringIO(file_bytes.decode('utf-8-sig')))
        return
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        yield from wb.active.iter_rows(values_only=True)
    finally:
        wb.close()


def parse_issue_sheet(file_bytes: bytes, filename: str) -> list:
    """[{'row_no', 'itemcode', 'qty', 'expiry'}]; blank code+qty rows skipped; row_no = sheet row."""
    out = []
    cols = None
    for n, row in enumerate(capped_rows(_iter_raw_rows(file_bytes, filename)), start=1):
        if cols is None:
            cols = _col_map(row)
            if 'itemcode' not in cols or 'qty' not in cols:
                raise ValueError('لم يتم العثور على عمودي الكود والكمية في الملف')
            continue
        code, qty = _cell(row, cols['itemcode']), _cell(row, cols['qty'])
        if _blank(code) and _blank(qty):
            continue
        expiry = _cell(row, cols.get('expiry'))
        out.append({
            'row_no': n,
            'itemcode': _text(code),
            'qty': _text(qty),
            'expiry': None if _blank(expiry) else expiry,
        })
    return out


def _parse_expiry(v):
    """-> (date|None, ok)"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, True
    if isinstance(v, datetime.datetime):
        return v.date(), True
    if isinstance(v, datetime.date):
        return v, True
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})', str(v).strip())
    if not m:
        return None, False
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime.date(y, mo, d), True
    except ValueError:
        return None, False


def _parse_qty(v):
    try:
        q = Decimal(_text(v))
    except (InvalidOperation, ValueError):
        return None
    if not q.is_finite() or q <= 0:
        return None
    # RpaLine.qty is DecimalField(12, 5): at most 7 integer digits and 5 decimals.
    if q >= 10 ** 7 or q.normalize().as_tuple().exponent < -5:
        return None
    return q


def _jsonable(v):
    return v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v


def build_lines(document, rows) -> None:
    """Create RpaLine rows for a document; every sheet row is kept, problems are flagged."""
    from .models import RpaLine
    codes = {normalise_code(r['itemcode']) for r in rows}
    items = match_items(c for c in codes if c)
    seen = set()
    lines = []
    for r in rows:
        code = normalise_code(r['itemcode'])
        qty = _parse_qty(r['qty'])
        expiry, expiry_ok = _parse_expiry(r['expiry'])
        item = items.get(code)
        status, message, warning = 'matched', '', ''
        if qty is None:
            status, message = 'error', 'الكمية غير صالحة'
        elif not expiry_ok:
            status, message = 'error', BAD_EXPIRY
        elif item is None:
            status, message = 'unmatched', 'كود غير موجود'
        if code and expiry_ok:
            key = (code, expiry)
            if key in seen:
                warning = 'صنف مكرر في الملف'
            seen.add(key)
        lines.append(RpaLine(
            document=document, item=item, row_no=r['row_no'],
            raw={k: _jsonable(v) for k, v in r.items()},
            itemcode=code[:40], qty=qty if qty is not None else 0, expiry=expiry,
            status=status, message=message, warning=warning,
        ))
    RpaLine.objects.bulk_create(lines)
