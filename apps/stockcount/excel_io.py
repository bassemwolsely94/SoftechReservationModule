"""
apps/stockcount/excel_io.py

Excel / CSV export and import for stock count sheets.

Export  → generate_count_sheet(session)  → bytes (xlsx)
Import  → parse_count_sheet(file_bytes, filename) → list[{item_code, counted_qty}]

Excel format
------------
Row 1 : Title row  (merged, bold)
Row 2 : Header row (bold, locked background)
Row 3+: Data rows  — columns A-E frozen
  A  item_code     (gray / locked visually)
  B  item_name     (gray / locked visually)
  C  item_medicine (gray / locked visually)
  D  expected_qty  (gray / locked visually)
  E  counted_qty   (yellow / user fills this)

A hidden column F holds the session_id for validation on re-import.
"""
import csv
import io
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.stockcount')

# ── Try openpyxl (best); fall back to CSV-only mode if not installed ──────────
try:
    import openpyxl
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side, Protection
    )
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False
    logger.warning('openpyxl not installed — Excel export will fall back to CSV')


# ── Colour palette ────────────────────────────────────────────────────────────
_HEADER_BG    = 'FF1F3864'   # dark navy
_HEADER_FG    = 'FFFFFFFF'   # white
_LOCKED_BG    = 'FFF2F2F2'   # light gray  (read-only columns)
_EDITABLE_BG  = 'FFFFFFCC'   # pale yellow (counted_qty)
_TITLE_BG     = 'FF2E75B6'   # blue
_SURPLUS_BG   = 'FFE2EFDA'   # light green
_DEFICIT_BG   = 'FFFCE4D6'   # light red/orange


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def generate_count_sheet(session, include_variance: bool = False) -> tuple:
    """
    Build the count sheet file for a session.

    Rows are ordered by the branch's STOCKING zones (ترصيص — shelf layout,
    managed at /pick-zones with purpose=ترصيص, falling back to the picking
    config then the defaults), so the counting walk follows the shelves.
    Zone stripe rows separate sections; they are re-import-safe (the parser
    skips rows without an item code / counted qty).

    Parameters
    ----------
    session          : StockCountSession instance (snapshots must be created)
    include_variance : if True, fill the expected/counted/difference columns
                       (used for the variance / adjustment export)

    Returns
    -------
    (bytes, filename, content_type)
    """
    snapshots = list(
        session.snapshots.order_by('item_name')
    )
    zone_map = _stocking_zone_map(session, snapshots)
    if zone_map:
        snapshots.sort(key=lambda s: _zone_sort_key(zone_map.get(s.item_code))
                       + (s.item_name or '',))
    pack_map = _pack_qty_map(snapshots)

    if _HAS_OPENPYXL:
        return _export_xlsx(session, snapshots, include_variance,
                            zone_map, pack_map)
    else:
        return _export_csv(session, snapshots, include_variance)


def _stocking_zone_map(session, snapshots) -> dict:
    """
    item_code → stocking zone for the session's branch, via the shared
    replenishment classifier. Empty dict on any failure → name ordering.
    """
    try:
        from apps.branches.models import Branch
        from apps.transits.export import classify_for_stocking

        branch = Branch.objects.filter(
            softech_branch_id=str(session.branch_code).strip()).first()
        return classify_for_stocking(
            [s.item_code for s in snapshots], branch=branch)
    except Exception as exc:
        logger.warning('stock-count zone ordering unavailable '
                       '(falling back to name order): %s', exc)
        return {}


def _zone_sort_key(zone) -> tuple:
    return (zone.sort_key, zone.name) if zone else (9999, '')


def _pack_qty_map(snapshots) -> dict:
    """
    item_code → pack_qty (sub-units per pack), so a fractional expected
    quantity can be spelled out as packs + units on the count sheet.
    """
    try:
        from apps.catalog.models import Item
        codes = [s.item_code for s in snapshots]
        return dict(
            Item.objects.filter(softech_id__in=codes)
            .values_list('softech_id', 'pack_qty')
        )
    except Exception as exc:
        logger.warning('pack_qty lookup failed (partial-qty detail off): %s', exc)
        return {}


def _export_xlsx(session, snapshots, include_variance: bool,
                 zone_map=None, pack_map=None):
    """Generate a nicely formatted .xlsx workbook (zone-striped when ordered)."""
    # shared: partial-pack wording + exact-decimal number format
    from apps.transits.export import _num_format, _qty_parts

    pack_map = pack_map or {}
    _PARTIAL_FILL = PatternFill('solid', fgColor='FFFFE9C7')   # amber
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'ورقة الجرد'
    ws.sheet_view.rightToLeft = True   # RTL for Arabic

    # ── Styles ────────────────────────────────────────────────────────────────
    header_font  = Font(name='Arial', bold=True, color=_HEADER_FG, size=11)
    header_fill  = PatternFill('solid', fgColor=_HEADER_BG)
    locked_fill  = PatternFill('solid', fgColor=_LOCKED_BG)
    editable_fill = PatternFill('solid', fgColor=_EDITABLE_BG)
    title_font   = Font(name='Arial', bold=True, color=_HEADER_FG, size=13)
    title_fill   = PatternFill('solid', fgColor=_TITLE_BG)
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    right_align  = Alignment(horizontal='right', vertical='center', wrap_text=True)
    thin_border  = Border(
        left=Side(style='thin', color='FFD0D0D0'),
        right=Side(style='thin', color='FFD0D0D0'),
        top=Side(style='thin', color='FFD0D0D0'),
        bottom=Side(style='thin', color='FFD0D0D0'),
    )

    # ── Row 1: Title ──────────────────────────────────────────────────────────
    ws.merge_cells('A1:H1' if include_variance else 'A1:G1')
    title_cell = ws['A1']
    title_cell.value = (
        f'ورقة الجرد المادي — {session.name}  |  فرع: {session.branch_code}  '
        f'|  جلسة رقم: {session.pk}'
        + ('  |  مرتبة حسب مناطق الترصيص 🗄️' if zone_map else '')
    )
    title_cell.font      = title_font
    title_cell.fill      = title_fill
    title_cell.alignment = center_align
    ws.row_dimensions[1].height = 28

    # ── Row 2: Headers ────────────────────────────────────────────────────────
    # NOTE: the re-import parser locates columns BY HEADER NAME, so the
    # 'تفصيل المتوقع' column can be inserted safely.
    headers = [
        'كود الصنف',
        'اسم الصنف',
        'نوع الدواء',
        'الكمية المتوقعة',
        'تفصيل المتوقع',
        'الكمية المعدودة ✏',
        'رقم الجلسة (لا تعدّل)',
    ]
    if include_variance:
        headers = [
            'كود الصنف', 'اسم الصنف', 'نوع الدواء',
            'الكمية المتوقعة', 'تفصيل المتوقع', 'الكمية المعدودة',
            'الفارق', 'نوع الانحراف',
        ]

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = center_align
        cell.border    = thin_border
    ws.row_dimensions[2].height = 22

    # ── Column widths — budgeted to ONE A4 portrait page ──────────────────────
    # Column B (item name) wraps and absorbs the slack, so long names stay
    # fully readable when printed. See apps/transits/export._fit_widths.
    from apps.transits.export import _fit_widths

    # كود، اسم، نوع الدواء، المتوقعة، تفصيل المتوقع، المعدودة، [الجلسة/الفارق…]
    if include_variance:
        plan, flex, spill = [11, 40, 8, 11, 13, 11, 9, 11], 1, 4
    else:
        # Column G (session_id) is hidden → it must not consume page width,
        # so spare width goes to the hand-written counted-qty column instead.
        plan, flex, spill = [11, 40, 8, 11, 13, 15, 0.1], 1, 5
    col_widths, pages_wide = _fit_widths(
        plan, flex_index=flex, ncols=len(plan) - (0 if include_variance else 1),
        landscape=False, flex_min=24, flex_max=46, spill_index=spill,
    )
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = round(w, 2)

    # Hide column G (session_id) in normal mode
    if not include_variance:
        ws.column_dimensions['G'].hidden = True

    # ── Print setup: one A4 page across, no side margins ──────────────────────
    ws.page_setup.paperSize   = ws.PAPERSIZE_A4
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.fitToWidth  = pages_wide
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.1
    ws.page_margins.top  = ws.page_margins.bottom = 0.3
    ws.page_margins.header = ws.page_margins.footer = 0
    ws.print_title_rows = '1:2'      # repeat title + header on every page

    # ── Data rows ─────────────────────────────────────────────────────────────
    SURPLUS_FILL = PatternFill('solid', fgColor=_SURPLUS_BG)
    DEFICIT_FILL = PatternFill('solid', fgColor=_DEFICIT_BG)
    ZONE_FILL    = PatternFill('solid', fgColor='FFD9E2F3')   # stocking-zone stripe

    ncols = len(headers)
    row_idx = 2
    prev_zone_name = object()
    for snap in snapshots:
        row_idx += 1

        # Zone stripe on zone change (ترصيص walk section). Merged from column
        # B so column A (item_code) stays empty → the re-import parser skips it.
        zone = (zone_map or {}).get(snap.item_code)
        zone_name = zone.name if zone else None
        if zone_map and zone_name != prev_zone_name:
            label = zone.sheet_label if zone else 'غير مصنف'
            ws.merge_cells(start_row=row_idx, start_column=2,
                           end_row=row_idx, end_column=ncols)
            zc = ws.cell(row=row_idx, column=2, value=f'🗄️ {label}')
            zc.font = Font(name='Arial', bold=True, size=11)
            zc.fill = ZONE_FILL
            zc.alignment = right_align
            prev_zone_name = zone_name
            row_idx += 1
        # Locked info columns (col 5 = تفصيل المتوقع — packs + sub-units)
        qty_text, is_partial = _qty_parts(
            snap.expected_qty, pack_map.get(snap.item_code, 1), snap.item_name)
        locked_values = [
            snap.item_code,
            snap.item_name,
            snap.item_medicine or '',
            float(snap.expected_qty),
            qty_text,
        ]
        for col_idx, val in enumerate(locked_values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill      = locked_fill
            cell.alignment = right_align
            cell.border    = thin_border
            if col_idx == 4:
                cell.number_format = _num_format(val)
            elif col_idx == 5 and is_partial:
                # partial pack → make it impossible to miss while counting
                cell.fill = _PARTIAL_FILL
                cell.font = Font(name='Arial', bold=True, size=9, color='FF9A3412')

        if include_variance:
            # Variance export: fill all columns
            ws.cell(row=row_idx, column=6, value=float(snap.counted_qty) if snap.counted_qty is not None else None)
            ws.cell(row=row_idx, column=7, value=float(snap.difference) if snap.difference is not None else None)
            ws.cell(row=row_idx, column=8, value=snap.get_variance_type_display() or '—')
            for col_idx in range(6, 9):
                c = ws.cell(row=row_idx, column=col_idx)
                c.alignment = right_align
                c.border    = thin_border
                if col_idx in (6, 7):
                    c.number_format = _num_format(c.value)
            # Colour-code variance
            if snap.variance_type == 'surplus':
                for col_idx in range(1, 9):
                    ws.cell(row=row_idx, column=col_idx).fill = SURPLUS_FILL
            elif snap.variance_type == 'deficit':
                for col_idx in range(1, 9):
                    ws.cell(row=row_idx, column=col_idx).fill = DEFICIT_FILL
        else:
            # Count sheet: only counted_qty is editable — 'General' so whatever
            # the counter types (5 or 2.5) shows cleanly, no forced trailing dot
            cnt_cell = ws.cell(row=row_idx, column=6, value=None)
            cnt_cell.fill      = editable_fill
            cnt_cell.alignment = right_align
            cnt_cell.border    = thin_border
            cnt_cell.number_format = 'General'

            # Hidden session_id
            ws.cell(row=row_idx, column=7, value=session.pk)

    # ── Freeze panes (header row + first 2 columns) ───────────────────────────
    ws.freeze_panes = 'C3'

    # ── Auto-filter on header row ─────────────────────────────────────────────
    last_col = get_column_letter(len(headers))
    ws.auto_filter.ref = f'A2:{last_col}{row_idx}'

    # ── Output ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    suffix = '_variance' if include_variance else '_count_sheet'
    fname  = f'stockcount_{session.pk}_{session.branch_code}{suffix}.xlsx'
    return buf.read(), fname, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _export_csv(session, snapshots, include_variance: bool):
    """Fallback CSV export (when openpyxl is not installed)."""
    buf = io.StringIO()
    w   = csv.writer(buf)

    if include_variance:
        w.writerow(['item_code', 'item_name', 'item_medicine',
                    'expected_qty', 'counted_qty', 'difference', 'variance_type'])
        for snap in snapshots:
            w.writerow([
                snap.item_code, snap.item_name, snap.item_medicine,
                snap.expected_qty, snap.counted_qty, snap.difference, snap.variance_type,
            ])
    else:
        w.writerow(['item_code', 'item_name', 'item_medicine',
                    'expected_qty', 'counted_qty', 'session_id'])
        for snap in snapshots:
            w.writerow([
                snap.item_code, snap.item_name, snap.item_medicine,
                snap.expected_qty, '',   # blank counted_qty
                session.pk,
            ])

    content  = '﻿' + buf.getvalue()   # UTF-8 BOM for Excel
    suffix   = '_variance' if include_variance else '_count_sheet'
    fname    = f'stockcount_{session.pk}_{session.branch_code}{suffix}.csv'
    return content.encode('utf-8'), fname, 'text/csv; charset=utf-8-sig'


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT
# ─────────────────────────────────────────────────────────────────────────────

def parse_count_sheet(file_bytes: bytes, filename: str) -> list:
    """
    Parse an uploaded count sheet (xlsx or csv).
    Only reads item_code and counted_qty columns.
    expected_qty column is intentionally ignored to prevent tampering.

    Returns list of dicts: [{item_code, counted_qty}]
    Raises ValueError with a descriptive message on structural errors.
    """
    fname_lower = (filename or '').lower()

    if fname_lower.endswith('.csv'):
        return _parse_csv(file_bytes)

    if fname_lower.endswith(('.xlsx', '.xls', '.xlsm')):
        if not _HAS_OPENPYXL:
            raise ValueError('openpyxl غير مثبت — يرجى رفع ملف CSV بدلاً منه')
        return _parse_xlsx(file_bytes)

    # Auto-detect: try xlsx then csv
    if _HAS_OPENPYXL:
        try:
            return _parse_xlsx(file_bytes)
        except Exception:
            pass
    return _parse_csv(file_bytes)


def _parse_xlsx(file_bytes: bytes) -> list:
    """Parse .xlsx upload; find item_code and counted_qty columns by header name."""
    buf = io.BytesIO(file_bytes)
    wb  = openpyxl.load_workbook(buf, read_only=True, data_only=True)
    ws  = wb.active

    rows_iter = ws.iter_rows(values_only=True)

    # Skip title row if it looks like a title (non-header content)
    header_row = None
    for row in rows_iter:
        # Find the row containing 'item_code' or 'كود الصنف'
        row_lower = [str(c).lower().strip() if c is not None else '' for c in row]
        if any(x in ('item_code', 'كود الصنف') for x in row_lower):
            header_row = row_lower
            break

    if header_row is None:
        raise ValueError(
            'لم يتم العثور على صف الترويسة — تأكد أن الملف يحتوي على عمود "item_code" أو "كود الصنف"'
        )

    # Locate column indices
    item_code_col  = _find_col(header_row, ['item_code', 'كود الصنف'])
    counted_qty_col = _find_col(header_row, [
        'counted_qty', 'الكمية المعدودة', 'الكمية المعدودة ✏',
    ])

    if item_code_col is None:
        raise ValueError('عمود كود الصنف (item_code) غير موجود في الملف')
    if counted_qty_col is None:
        raise ValueError('عمود الكمية المعدودة (counted_qty) غير موجود في الملف')

    results = []
    for row in rows_iter:
        if row[item_code_col] is None:
            continue
        code     = str(row[item_code_col]).strip()
        raw_qty  = row[counted_qty_col]
        if not code:
            continue
        qty = _safe_decimal(raw_qty)
        if qty is None:
            continue   # blank counted_qty = not yet counted, skip
        results.append({'item_code': code, 'counted_qty': qty})

    wb.close()
    return results


def _parse_csv(file_bytes: bytes) -> list:
    """Parse .csv upload; supports UTF-8 with or without BOM and cp1256."""
    for encoding in ('utf-8-sig', 'utf-8', 'cp1256'):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('تعذّر قراءة الملف — تأكد من أن الترميز UTF-8 أو cp1256')

    reader = csv.DictReader(io.StringIO(text))

    # Normalise header names
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not fieldnames:
        raise ValueError('الملف فارغ أو لا يحتوي على ترويسة')

    item_col   = _find_col(fieldnames, ['item_code', 'كود الصنف'])
    qty_col    = _find_col(fieldnames, ['counted_qty', 'الكمية المعدودة', 'الكمية المعدودة ✏'])

    if item_col is None:
        raise ValueError('عمود كود الصنف (item_code) غير موجود في الملف')
    if qty_col is None:
        raise ValueError('عمود الكمية المعدودة (counted_qty) غير موجود في الملف')

    # Map normalised name back to original
    orig_fields = list(reader.fieldnames or [])
    orig_item   = orig_fields[item_col]
    orig_qty    = orig_fields[qty_col]

    results = []
    for row in reader:
        code    = str(row.get(orig_item, '')).strip()
        raw_qty = row.get(orig_qty, '')
        if not code:
            continue
        qty = _safe_decimal(raw_qty)
        if qty is None:
            continue
        results.append({'item_code': code, 'counted_qty': qty})

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_col(header_row: list, candidates: list):
    """Return 0-based index of the first matching candidate in header_row."""
    for i, h in enumerate(header_row):
        if h in candidates:
            return i
    return None


def _safe_decimal(value):
    """Convert to Decimal; return None if blank or non-numeric."""
    if value is None:
        return None
    s = str(value).strip()
    if s == '' or s.lower() in ('-', 'none', 'null', 'nan'):
        return None
    # Remove commas used as thousands separator
    s = s.replace(',', '')
    try:
        return Decimal(s).quantize(Decimal('0.001'))
    except (InvalidOperation, ValueError):
        return None
