"""
apps/invoices/export.py

Export a SupplierInvoice to Excel (xlsx) or CSV.

  export_invoice_excel(invoice)  → bytes
  export_invoice_csv(invoice)    → str  (UTF-8 with BOM for Excel compatibility)
"""
from __future__ import annotations
import csv
import io
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Styles ─────────────────────────────────────────────────────────────────────
_HEADER_FILL  = PatternFill('solid', fgColor='1F3864')
_GREEN_FILL   = PatternFill('solid', fgColor='E2EFDA')
_ORANGE_FILL  = PatternFill('solid', fgColor='FCE4D6')
_ALT_FILL     = PatternFill('solid', fgColor='EBF3FB')
_THIN_BORDER  = Border(
    left   = Side(style='thin', color='BFBFBF'),
    right  = Side(style='thin', color='BFBFBF'),
    top    = Side(style='thin', color='BFBFBF'),
    bottom = Side(style='thin', color='BFBFBF'),
)
_WHITE_FONT   = Font(color='FFFFFF', bold=True, name='Calibri', size=11)
_BOLD_FONT    = Font(bold=True, name='Calibri', size=10)
_NORMAL_FONT  = Font(name='Calibri', size=10)
_RTL_ALIGN    = Alignment(horizontal='right', vertical='center', wrap_text=True, readingOrder=2)
_CENTER_ALIGN = Alignment(horizontal='center', vertical='center')


def _style(cell, font=None, fill=None, align=None, border=True, number_format=None):
    if font:          cell.font          = font
    if fill:          cell.fill          = fill
    if align:         cell.alignment     = align
    if border:        cell.border        = _THIN_BORDER
    if number_format: cell.number_format = number_format


# ── Excel export ───────────────────────────────────────────────────────────────

def export_invoice_excel(invoice) -> bytes:
    """Export a SupplierInvoice with all its lines to an xlsx workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'فاتورة مورد'
    ws.sheet_view.rightToLeft = True

    branch_name   = getattr(invoice.branch, 'name_ar', None) or getattr(invoice.branch, 'name', '')
    supplier_name = invoice.supplier_name or 'غير محدد'
    title_text    = f'فاتورة {supplier_name} — {branch_name}'

    # ── Title row ─────────────────────────────────────────────────────────────
    ws.merge_cells('A1:R1')
    tc = ws['A1']
    tc.value     = title_text
    tc.font      = Font(name='Calibri', size=14, bold=True, color='FFFFFF')
    tc.fill      = _HEADER_FILL
    tc.alignment = _RTL_ALIGN
    ws.row_dimensions[1].height = 32

    # ── Meta block (rows 2-6) ─────────────────────────────────────────────────
    meta = [
        ('المورد',         supplier_name),
        ('رقم الفاتورة',   invoice.invoice_number or '—'),
        ('تاريخ الفاتورة', str(invoice.invoice_date) if invoice.invoice_date else '—'),
        ('الفرع',          branch_name),
        ('الحالة',         dict(invoice.STATUS).get(invoice.status, invoice.status)),
    ]
    for r, (k, v) in enumerate(meta, 2):
        kc = ws.cell(row=r, column=1, value=k)
        vc = ws.cell(row=r, column=2, value=v)
        _style(kc, font=_BOLD_FONT, align=_RTL_ALIGN)
        _style(vc, font=_NORMAL_FONT, align=_RTL_ALIGN)

    # ── Column headers (row 8) ────────────────────────────────────────────────
    HDR_ROW = 8
    COLS = [
        '#', 'اسم الصنف', 'الصنف في ERP', 'كود ERP',
        'المصنع', 'التشغيلة', 'الصلاحية',
        'الكمية', 'كود المورد', 'سعر الجمهور', 'خصم مطابقة%', 'خصم إضافي%',
        'سعر الصيدلي', 'ض.ق.م%', 'هامش الموزع (ج.م)', 'هامش ربح الصيدلي (ج.م)', 'الإجمالي', 'مُأكَّد',
    ]
    col_widths = [4, 36, 36, 11, 22, 12, 11, 9, 13, 13, 12, 12, 13, 9, 16, 18, 13, 7]
    for c, (label, w) in enumerate(zip(COLS, col_widths), 1):
        cell = ws.cell(row=HDR_ROW, column=c, value=label)
        _style(cell, font=_WHITE_FONT, fill=_HEADER_FILL, align=_RTL_ALIGN)
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[HDR_ROW].height = 22

    # ── Data rows ─────────────────────────────────────────────────────────────
    lines = list(invoice.lines.select_related('item').order_by('order', 'id'))
    NUM_COLS = {8, 9, 10, 11, 13, 14, 15, 16, 17}  # columns that get number format
    for i, ln in enumerate(lines, 1):
        row  = HDR_ROW + i
        fill = _GREEN_FILL if ln.is_confirmed else (_ORANGE_FILL if not ln.item_id else (_ALT_FILL if i % 2 == 0 else None))
        data = [
            i,
            ln.manual_name or ln.raw_text,
            ln.item.name          if ln.item_id else '—',
            ln.item.softech_id    if ln.item_id else '',
            ln.manufacturer,
            ln.batch_number,
            ln.expiry_date,
            float(ln.quantity),
            ln.vendor_item_code,
            float(ln.public_price),
            float(ln.discount_pct),
            float(ln.extra_discount_pct),
            float(ln.unit_price),
            float(ln.vat_pct),
            float(ln.distributor_margin_amt),
            float(ln.pharmacist_margin_amt),
            float(ln.line_total or 0),
            'نعم' if ln.is_confirmed else 'لا',
        ]
        for c, val in enumerate(data, 1):
            cell = ws.cell(row=row, column=c, value=val)
            _style(cell, font=_NORMAL_FONT, fill=fill, align=_RTL_ALIGN)
            if c in NUM_COLS:
                cell.number_format = '#,##0.###'
        ws.row_dimensions[row].height = 18

    # ── Totals block ─────────────────────────────────────────────────────────
    TOTAL_COL = len(COLS)  # last numeric column = إجمالي
    sum_row = HDR_ROW + len(lines) + 2
    ws.cell(row=sum_row, column=1, value='الإجمالي قبل الخصم العام:').font = _BOLD_FONT
    ws.cell(row=sum_row, column=TOTAL_COL, value=float(invoice.total_before_discount)).font = _BOLD_FONT
    ws.cell(row=sum_row, column=TOTAL_COL).number_format = '#,##0.###'

    disc_row = sum_row + 1
    ws.cell(row=disc_row, column=1, value=f'خصم عام: {invoice.global_discount_pct}% + {invoice.global_discount_amt}').font = _NORMAL_FONT

    total_row = sum_row + 2
    ws.cell(row=total_row, column=1, value='الإجمالي النهائي:').font = _BOLD_FONT
    tc2 = ws.cell(row=total_row, column=TOTAL_COL, value=float(invoice.total_after_discount))
    tc2.font   = Font(bold=True, name='Calibri', size=12, color='1F3864')
    tc2.number_format = '#,##0.###'

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── CSV export ─────────────────────────────────────────────────────────────────

def export_invoice_csv(invoice) -> bytes:
    """
    Export to CSV (UTF-8 with BOM so Excel opens Arabic correctly).
    Returns raw bytes.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header metadata
    writer.writerow(['فاتورة مورد'])
    writer.writerow(['المورد',       invoice.supplier_name or '—'])
    writer.writerow(['رقم الفاتورة', invoice.invoice_number or '—'])
    writer.writerow(['التاريخ',      str(invoice.invoice_date) if invoice.invoice_date else '—'])
    writer.writerow(['الفرع',        getattr(invoice.branch, 'name_ar', '') or invoice.branch.name])
    writer.writerow([])

    # Column headers
    writer.writerow([
        '#', 'اسم الصنف', 'الصنف في ERP', 'كود ERP',
        'المصنع', 'التشغيلة', 'الصلاحية',
        'الكمية', 'كود المورد', 'سعر الجمهور', 'خصم مطابقة%', 'خصم إضافي%',
        'سعر الصيدلي', 'ض.ق.م%', 'هامش الموزع (ج.م)', 'هامش ربح الصيدلي (ج.م)', 'الإجمالي', 'مُأكَّد',
    ])

    for i, ln in enumerate(invoice.lines.select_related('item').order_by('order', 'id'), 1):
        writer.writerow([
            i,
            ln.manual_name or ln.raw_text,
            ln.item.name       if ln.item_id else '—',
            ln.item.softech_id if ln.item_id else '',
            ln.manufacturer,
            ln.batch_number,
            ln.expiry_date,
            float(ln.quantity),
            ln.vendor_item_code,
            float(ln.public_price),
            float(ln.discount_pct),
            float(ln.extra_discount_pct),
            float(ln.unit_price),
            float(ln.vat_pct),
            float(ln.distributor_margin_amt),
            float(ln.pharmacist_margin_amt),
            float(ln.line_total or 0),
            'نعم' if ln.is_confirmed else 'لا',
        ])

    writer.writerow([])
    writer.writerow(['الإجمالي قبل الخصم'] + [''] * 15 + [float(invoice.total_before_discount)])
    writer.writerow(['الإجمالي النهائي']    + [''] * 15 + [float(invoice.total_after_discount)])

    # Return UTF-8 with BOM
    return ('﻿' + buf.getvalue()).encode('utf-8')
