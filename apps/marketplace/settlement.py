"""
apps/marketplace/settlement.py — platform payout/settlement file import and matching to orders (doc 38).

import_csv(channel, file, column_map, user, period_from=, period_to=) reads a .csv / .xlsx payout file into a
SettlementBatch + SettlementLine rows; match(batch) compares each line with the channel's ExternalOrder
(platform_total vs gross, tolerance 0.50 EGP) and adds a synthetic 'not_in_file' line for every delivered order of
the period the file never mentioned. match() is re-runnable. Orders are never edited; nothing touches SOFTECH.
"""
import csv
import io
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.audit.models import AuditLog

from .models import ExternalOrder, SettlementBatch, SettlementLine

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
TOLERANCE = Decimal('0.50')
MAP_KEYS = ('external_id', 'gross', 'commission', 'delivery_fee', 'net')
_AMOUNT_KEYS = ('gross', 'commission', 'delivery_fee', 'net')
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
_CLEAN = re.compile(r'[\s,،]')
BAD_AMOUNT_NOTE = 'قيمة غير رقمية'


def parse_amount(value):
    """Decimal from '1,234.50' / Arabic-Indic digits / a number; blank -> 0; garbage -> ValueError."""
    if value is None:
        return Decimal('0')
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(Decimal('0.01'))
    text = _CLEAN.sub('', str(value).translate(_DIGITS))
    if not text:
        return Decimal('0')
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError('bad_amount')
    if not amount.is_finite() or abs(amount) >= Decimal('1e10'):
        raise ValueError('bad_amount')
    return amount.quantize(Decimal('0.01'))


def _read_bytes(file):
    data = file.read(MAX_BYTES + 1)
    if isinstance(data, str):
        data = data.encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('file_too_large')
    return data


def _rows(file, name):
    """Dict rows (header -> cell) from a csv / xlsx upload; ValueError on anything else."""
    ext = os.path.splitext(name or '')[1].lower()
    if ext not in ('.csv', '.xlsx'):
        raise ValueError('bad_extension')
    data = _read_bytes(file)
    if ext == '.csv':
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('unreadable')
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        import openpyxl
        from openpyxl.utils.exceptions import InvalidFileException
        from apps.finance.gl.manual_import import READ_ERRORS
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except (InvalidFileException, OSError, *READ_ERRORS):
            raise ValueError('unreadable')
        try:
            it = wb.worksheets[0].iter_rows(values_only=True)
            header = next(it, None)
            if header is None:
                return []
            names = [str(h).strip() if h is not None else '' for h in header]
            rows = []
            for r in it:
                if len(rows) > MAX_ROWS:
                    break
                if r is None or all(c in (None, '') for c in r):
                    continue
                rows.append({n: c for n, c in zip(names, r) if n})
        finally:
            wb.close()
    if len(rows) > MAX_ROWS:
        raise ValueError('too_many_rows')
    return rows


@transaction.atomic
def import_csv(channel, file, column_map, user, period_from=None, period_to=None):
    """Read the payout file into a SettlementBatch (lines start 'unmatched'; call match() next)."""
    column_map = {k: column_map[k] for k in MAP_KEYS if column_map and column_map.get(k)}
    if 'external_id' not in column_map:
        raise ValueError('external_id_column_required')
    name = getattr(file, 'name', '') or ''
    rows = _rows(file, name)
    today = date.today()
    batch = SettlementBatch.objects.create(
        channel=channel, period_from=period_from or today, period_to=period_to or period_from or today,
        file_name=os.path.basename(name)[:255], uploaded_by=user, column_map=column_map)
    lines = []
    for row in rows:
        ext = str(row.get(column_map['external_id']) or '').strip()
        if not ext:
            continue
        vals, notes = {}, []
        for key in _AMOUNT_KEYS:
            col = column_map.get(key)
            try:
                vals[key] = parse_amount(row.get(col)) if col else Decimal('0')
            except ValueError:
                vals[key] = Decimal('0')
                notes.append(f'{BAD_AMOUNT_NOTE} في {col}')
        lines.append(SettlementLine(batch=batch, external_id=ext[:100], note='؛ '.join(notes),
                                    match_status=SettlementLine.UNMATCHED, **vals))
    SettlementLine.objects.bulk_create(lines)
    return batch


@transaction.atomic
def match(batch, user=None):
    """Compare every file line with the channel's orders; flag delivered orders missing from the file.
    Re-runnable: earlier 'not_in_file' lines are dropped and every status recomputed. Returns counts."""
    batch.lines.filter(match_status=SettlementLine.NOT_IN_FILE).delete()
    orders = {o.external_id: o for o in ExternalOrder.objects.filter(channel=batch.channel)}
    counts = {SettlementLine.MATCHED: 0, SettlementLine.UNMATCHED: 0,
              SettlementLine.AMOUNT_MISMATCH: 0, SettlementLine.NOT_IN_FILE: 0}
    seen = set()
    for line in batch.lines.all():
        seen.add(line.external_id)
        order = orders.get(line.external_id)
        note = line.note if BAD_AMOUNT_NOTE in line.note else ''
        if order is None or note:
            status = SettlementLine.UNMATCHED
        elif abs(order.platform_total - line.gross) <= TOLERANCE:
            status = SettlementLine.MATCHED
        else:
            status = SettlementLine.AMOUNT_MISMATCH
            note = f'إجمالي المنصة {order.platform_total} ≠ الملف {line.gross}'
        line.order, line.match_status, line.note = order, status, note
        line.save(update_fields=['order', 'match_status', 'note'])
        counts[status] += 1
    missing = (ExternalOrder.objects
               .filter(channel=batch.channel, status=ExternalOrder.STATUS_DELIVERED,
                       created_at__date__gte=batch.period_from, created_at__date__lte=batch.period_to)
               .exclude(external_id__in=seen))
    extra = [SettlementLine(batch=batch, external_id=o.external_id, order=o,
                            match_status=SettlementLine.NOT_IN_FILE, note='تم التوصيل ولا يوجد في ملف المنصة')
             for o in missing]
    SettlementLine.objects.bulk_create(extra)
    counts[SettlementLine.NOT_IN_FILE] = len(extra)
    AuditLog.log('marketplace_settlement_matched', user=user, obj=batch, new_data=counts,
                 extra={'channel': batch.channel.code, 'lines': len(seen)})
    return counts
