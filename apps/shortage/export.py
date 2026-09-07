"""
apps/shortage/export.py

Excel (xlsx) export for shortage lists.
Two export modes:
  1. Single list  — export_list_excel(shortage_list)
  2. Aggregated   — export_aggregated_excel(shortage_lists)  ← merges items
                    across multiple lists, sums quantities,
                    shows per-branch breakdown and source summary.
"""
from __future__ import annotations
import io
from collections import defaultdict
from datetime import datetime

import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter

# ── Style constants ────────────────────────────────────────────────────────────
_HEADER_FILL   = PatternFill('solid', fgColor='1F3864')   # dark navy
_SUBHDR_FILL   = PatternFill('solid', fgColor='2E75B6')   # brand blue
_ALT_FILL      = PatternFill('solid', fgColor='EBF3FB')
_GREEN_FILL    = PatternFill('solid', fgColor='E2EFDA')
_ORANGE_FILL   = PatternFill('solid', fgColor='FCE4D6')
_THIN_BORDER   = Border(
    left=Side(style='thin', color='BFBFBF'),
    right=Side(style='thin', color='BFBFBF'),
    top=Side(style='thin', color='BFBFBF'),
    bottom=Side(style='thin', color='BFBFBF'),
)
_WHITE_FONT    = Font(color='FFFFFF', bold=True, name='Calibri', size=11)
_BOLD_FONT     = Font(bold=True, name='Calibri', size=10)
_NORMAL_FONT   = Font(name='Calibri', size=10)
_RTL_ALIGN     = Alignment(horizontal='right', vertical='center', wrap_text=True, readingOrder=2)
_CENTER_ALIGN  = Alignment(horizontal='center', vertical='center')


def _style(cell, font=None, fill=None, align=None, border=True, number_format=None):
    if font:           cell.font           = font
    if fill:           cell.fill           = fill
    if align:          cell.alignment      = align
    if border:         cell.border         = _THIN_BORDER
    if number_format:  cell.number_format  = number_format


def _header_row(ws, row: int, cols: list[str]):
    for c, label in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=label)
        _style(cell, font=_WHITE_FONT, fill=_HEADER_FILL, align=_RTL_ALIGN)


def _set_col_widths(ws, widths: list[int]):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ── Source label helper ────────────────────────────────────────────────────────
_SOURCE_LABELS = {'manual': 'يدوي', 'voice': 'صوتي', 'ocr': 'OCR', 'bulk': 'نصي'}


def _source_label(src: str) -> str:
    return _SOURCE_LABELS.get(src, src)


# ── Single-list export ─────────────────────────────────────────────────────────

def export_list_excel(shortage_list) -> bytes:
    """
    Export one ShortageList to Excel.
    Sheet: Items (all rows) + metadata header block.
    Returns raw bytes ready for HttpResponse.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'نواقص'
    ws.sheet_view.rightToLeft = True

    branch_name = shortage_list.branch.name_ar or shortage_list.branch.name
    title       = shortage_list.title or f'نواقص {branch_name}'

    # ── Meta block ────────────────────────────────────────────────────────────
    ws.merge_cells('A1:H1')
    title_cell = ws['A1']
    title_cell.value     = title
    title_cell.font      = Font(name='Calibri', size=14, bold=True, color='FFFFFF')
    title_cell.fill      = _HEADER_FILL
    title_cell.alignment = _RTL_ALIGN
    ws.row_dimensions[1].height = 30

    meta = [
        ('الفرع', branch_name),
        ('التاريخ', shortage_list.created_at.strftime('%Y-%m-%d')),
        ('الحالة', dict(shortage_list.STATUS).get(shortage_list.status, shortage_list.status)),
        ('المصدر', shortage_list.source),
    ]
    for r, (k, v) in enumerate(meta, 2):
        kc = ws.cell(row=r, column=1, value=k)
        vc = ws.cell(row=r, column=2, value=v)
        _style(kc, font=_BOLD_FONT, align=_RTL_ALIGN)
        _style(vc, font=_NORMAL_FONT, align=_RTL_ALIGN)

    # ── Column headers ────────────────────────────────────────────────────────
    HDR_ROW = 7
    COLS = ['#', 'الاسم كما أُدخل', 'الصنف المطابق', 'كود ERP',
            'الكمية', 'الوحدة', 'مصدر الإدخال', 'نسبة التطابق', 'مُأكَّد', 'ملاحظات']
    _header_row(ws, HDR_ROW, COLS)
    _set_col_widths(ws, [5, 30, 35, 12, 10, 10, 12, 12, 8, 25])
    ws.row_dimensions[HDR_ROW].height = 22

    # ── Data rows ─────────────────────────────────────────────────────────────
    items = list(shortage_list.items.select_related('item').order_by('raw_name'))
    for i, si in enumerate(items, 1):
        row = HDR_ROW + i
        is_alt = (i % 2 == 0)
        fill   = _ALT_FILL if is_alt else None
        confirmed_fill = _GREEN_FILL if si.is_confirmed else (_ORANGE_FILL if si.is_unmatched else fill)

        data = [
            i,
            si.raw_name,
            si.item.name if si.item_id else '—',
            si.item.softech_id if si.item_id else '',
            float(si.quantity_needed),
            si.unit or '',
            _source_label(si.source),
            f'{si.match_score:.0%}' if si.match_score else '',
            'نعم' if si.is_confirmed else ('غير مطابق' if si.is_unmatched else 'لا'),
            si.notes or '',
        ]
        for c, val in enumerate(data, 1):
            cell = ws.cell(row=row, column=c, value=val)
            _style(cell, font=_NORMAL_FONT, fill=confirmed_fill, align=_RTL_ALIGN)
        ws.row_dimensions[row].height = 18

    # ── Summary row ───────────────────────────────────────────────────────────
    summary_row = HDR_ROW + len(items) + 2
    confirmed_count = sum(1 for si in items if si.is_confirmed)
    unmatched_count = sum(1 for si in items if si.is_unmatched)
    ws.cell(row=summary_row, column=1, value='الإجمالي:').font = _BOLD_FONT
    ws.cell(row=summary_row, column=2, value=f'{len(items)} صنف — {confirmed_count} مُأكَّد — {unmatched_count} غير مطابق').font = _NORMAL_FONT

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Aggregated export ──────────────────────────────────────────────────────────

def export_aggregated_excel(shortage_lists) -> bytes:
    """
    Merge items across multiple ShortageList objects.
    Deduplicates by item_code; sums quantities; shows per-branch breakdown.

    Columns:
      item_code | item_name | total_qty | branch_breakdown | sources | confirmed
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'نواقص مجمعة'
    ws.sheet_view.rightToLeft = True

    # ── Meta ──────────────────────────────────────────────────────────────────
    ws.merge_cells('A1:G1')
    hdr_cell = ws['A1']
    hdr_cell.value     = f'قائمة النواقص المجمعة — {datetime.now().strftime("%Y-%m-%d")}'
    hdr_cell.font      = Font(name='Calibri', size=13, bold=True, color='FFFFFF')
    hdr_cell.fill      = _HEADER_FILL
    hdr_cell.alignment = _RTL_ALIGN
    ws.row_dimensions[1].height = 28

    # ── Aggregate data ────────────────────────────────────────────────────────
    # key: (item_id or raw_name) → aggregated dict
    agg: dict[str, dict] = {}

    for sl in shortage_lists:
        branch_name = sl.branch.name_ar or sl.branch.name
        for si in sl.items.select_related('item').all():
            if si.item_id:
                key = f'item:{si.item_id}'
                if key not in agg:
                    agg[key] = {
                        'item_code':  si.item.softech_id,
                        'item_name':  si.item.name,
                        'total_qty':  0.0,
                        'branches':   defaultdict(float),   # branch_name → qty
                        'sources':    set(),
                        'confirmed':  True,
                        'unmatched':  False,
                    }
                agg[key]['total_qty'] += float(si.quantity_needed)
                agg[key]['branches'][branch_name] += float(si.quantity_needed)
                agg[key]['sources'].add(_source_label(si.source))
                if not si.is_confirmed:
                    agg[key]['confirmed'] = False
            else:
                # Unmatched — group by normalized raw name
                from .matching import _normalize
                key = f'raw:{_normalize(si.raw_name)}'
                if key not in agg:
                    agg[key] = {
                        'item_code':  '',
                        'item_name':  si.raw_name,
                        'total_qty':  0.0,
                        'branches':   defaultdict(float),
                        'sources':    set(),
                        'confirmed':  False,
                        'unmatched':  True,
                    }
                agg[key]['total_qty'] += float(si.quantity_needed)
                agg[key]['branches'][branch_name] += float(si.quantity_needed)
                agg[key]['sources'].add(_source_label(si.source))

    # ── Headers ───────────────────────────────────────────────────────────────
    HDR_ROW = 4
    COLS = ['كود ERP', 'اسم الصنف', 'إجمالي الكمية',
            'توزيع الفروع', 'مصادر الإدخال', 'مُأكَّد', 'ملاحظات']
    _header_row(ws, HDR_ROW, COLS)
    _set_col_widths(ws, [12, 40, 14, 40, 18, 8, 20])
    ws.row_dimensions[HDR_ROW].height = 22

    # ── Rows (confirmed first, then unmatched) ────────────────────────────────
    rows = sorted(agg.values(),
                  key=lambda x: (x['unmatched'], -x['total_qty']))

    for i, entry in enumerate(rows, 1):
        r    = HDR_ROW + i
        fill = _GREEN_FILL if entry['confirmed'] else (_ORANGE_FILL if entry['unmatched'] else (_ALT_FILL if i % 2 == 0 else None))
        branch_breakdown = '; '.join(
            f"{br}: {qty:.0f}" for br, qty in sorted(entry['branches'].items())
        )
        data = [
            entry['item_code'],
            entry['item_name'],
            entry['total_qty'],
            branch_breakdown,
            '+'.join(sorted(entry['sources'])),
            'نعم' if entry['confirmed'] else ('غير مطابق' if entry['unmatched'] else 'جزئي'),
            '',
        ]
        for c, val in enumerate(data, 1):
            cell = ws.cell(row=r, column=c, value=val)
            _style(cell, font=_NORMAL_FONT, fill=fill, align=_RTL_ALIGN)
            if c == 3:  # total qty
                cell.number_format = '#,##0.##'
        ws.row_dimensions[r].height = 18

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Supplier-aware exports (sourcing + ordering) ────────────────────────────────

_GUIDE_NOTE = ('إرشادي فقط — بيانات الموردين والأسعار تاريخية وقد تتغير؛ الحصرية غير شائعة '
               'والموزّعون يغيّرون أصنافهم باستمرار.')


def _sourced_items(shortage_list, restrict_supplier=''):
    """(list of ShortageItem, {softech_id: sourcing}) — only matched items are sourced."""
    from .supplier_sourcing import build_sourcing
    items = list(shortage_list.items.select_related('item').order_by('raw_name'))
    codes = [i.item.softech_id for i in items if i.item_id and i.item.softech_id]
    sourcing = build_sourcing(codes, restrict_supplier=restrict_supplier) if codes else {}
    return items, sourcing


def export_supplier_matrix(shortage_list) -> bytes:
    """COMPREHENSIVE: one row per item, a column for EACH main distributor showing
    that supplier's code (✓ = carries it, no code yet), plus last-bought supplier,
    last cost, cheapest historical cost, and how many suppliers carry it."""
    from .supplier_sourcing import main_supplier_columns
    items, sourcing = _sourced_items(shortage_list)
    mains = main_supplier_columns()   # [(personcode, name)]

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'موردون'
    ws.sheet_view.rightToLeft = True
    fixed = ['#', 'كود الصنف', 'اسم الصنف', 'الكمية']
    tail  = ['آخر شراء من', 'آخر تكلفة', 'أقل تكلفة تاريخية', 'عدد الموردين']
    cols  = fixed + [n.replace('EGY DRUG - ', 'ED-').replace(' - ', ' ')[:14] for _, n in mains] + tail
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    note = ws.cell(row=1, column=1, value=_GUIDE_NOTE)
    _style(note, font=_BOLD_FONT, fill=_ORANGE_FILL, align=_RTL_ALIGN)
    _header_row(ws, 2, cols)
    _set_col_widths(ws, [5, 12, 34, 8] + [12] * len(mains) + [18, 11, 14, 10])

    for r, si in enumerate(items, start=3):
        sid = si.item.softech_id if si.item_id else None
        src = sourcing.get(sid, {}) if sid else {}
        supps = src.get('suppliers', {}); hist = src.get('history', {}); lb = src.get('last_bought')
        costs = [h['cost'] for h in hist.values() if h.get('cost')]
        row = [r - 2, sid or '—',
               si.item.name if si.item_id else si.raw_name,
               float(si.quantity_needed or 0)]
        for pc, _ in mains:
            s = supps.get(pc)
            row.append(s['code'] if (s and s['code']) else ('✓' if s else ''))
        row += [(lb['name'] if lb else '—'),
                (lb['cost'] if lb else None),
                (min(costs) if costs else None),
                len(supps) or '']
        fill = _ALT_FILL if r % 2 == 0 else None
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=val)
            _style(cell, font=_NORMAL_FONT, fill=fill, align=_RTL_ALIGN)
            if c in (4, len(fixed) + len(mains) + 2, len(fixed) + len(mains) + 3):
                cell.number_format = '#,##0.##'
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def export_supplier_po(shortage_list, suppcode: str, supplier_name: str = '') -> bytes:
    """SINGLE SUPPLIER purchase order: every item with THIS supplier's own code
    (paste-ready for their ERP). Items with no code yet are still included with our
    name + a 'no code' flag so nothing is dropped."""
    supp = str(suppcode).strip()
    items, sourcing = _sourced_items(shortage_list, restrict_supplier=supp)

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = f'طلب {supp}'
    ws.sheet_view.rightToLeft = True
    cols = ['#', 'كود المورد', 'اسم الصنف', 'الاسم العلمي', 'كود الصنف لدينا',
            'الكمية', 'آخر تكلفة من المورد', 'ملاحظة']
    hdr = f'أمر شراء — {supplier_name or supp}   |   {_GUIDE_NOTE}'
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    note = ws.cell(row=1, column=1, value=hdr)
    _style(note, fill=_SUBHDR_FILL, align=_RTL_ALIGN); note.font = _WHITE_FONT
    _header_row(ws, 2, cols)
    _set_col_widths(ws, [5, 14, 34, 26, 13, 8, 16, 22])

    r = 3
    for si in items:
        sid = si.item.softech_id if si.item_id else None
        src = sourcing.get(sid, {}) if sid else {}
        s = src.get('suppliers', {}).get(supp)
        hist = src.get('history', {}).get(supp)
        code = s['code'] if (s and s['code']) else ''
        if not si.item_id:
            note_txt = 'صنف غير مطابق — راجع يدوياً'
        elif not s and not hist:
            note_txt = 'المورد لا يوفّر هذا الصنف (تاريخياً)'
        elif not code:
            note_txt = 'لا يوجد كود لدى هذا المورد بعد'
        else:
            note_txt = ''
        row = [r - 2, code,
               si.item.name if si.item_id else si.raw_name,
               (si.item.name_scientific or '') if si.item_id else '',
               sid or '—', float(si.quantity_needed or 0),
               (hist['cost'] if hist and hist.get('cost') else None), note_txt]
        fill = _ORANGE_FILL if note_txt else (_ALT_FILL if r % 2 == 0 else None)
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=val)
            _style(cell, font=_NORMAL_FONT, fill=fill, align=_RTL_ALIGN)
            if c in (6, 7):
                cell.number_format = '#,##0.##'
        r += 1
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
