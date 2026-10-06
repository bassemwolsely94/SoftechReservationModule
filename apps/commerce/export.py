"""
apps/commerce/export.py — single-page A4 invoice / quotation export.

Deliberately small and self-contained (no dependency on the insurance exporter):
header block, a line table with the inclusive-VAT breakdown, and a totals box.
"""
import io

from django.http import HttpResponse

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except Exception:  # pragma: no cover
    HAS_OPENPYXL = False

_HEADER_FILL = 'FF1F4E79'
_TOTAL_FILL  = 'FFD6E4F0'
_THIN = Side(style='thin', color='FFBBBBBB')
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _rtl(ws):
    ws.sheet_view.rightToLeft = True


def _resp(wb, number):
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{number}.xlsx"'
    return resp


def generate_allocation_excel(doc) -> HttpResponse:
    """Items × branches grid: qty per branch, row total qty, row value."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = 'شبكة التوزيع'; _rtl(ws)
    ws.page_setup.paperSize = 9
    ws.page_setup.orientation = 'landscape'
    ws.page_margins.left = ws.page_margins.right = 0.3
    bold = Font(name='Arial', bold=True, size=11)
    wbold = Font(name='Arial', bold=True, size=10, color='FFFFFFFF')
    reg  = Font(name='Arial', size=10)
    ctr  = Alignment(horizontal='center', vertical='center', readingOrder=2)
    right = Alignment(horizontal='right', vertical='center', readingOrder=2)

    locs = list(doc.recipient.locations.filter(is_active=True)) if doc.recipient else []
    r = 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(locs) + 4)
    c = ws.cell(r, 1, f'{doc.doc_type.name} — {doc.number} — {doc.recipient.name if doc.recipient else ""}')
    c.font = Font(name='Arial', bold=True, size=14); c.alignment = ctr
    ws.cell(r, 1).alignment = ctr; ws.row_dimensions[r].height = 24; r += 1
    ws.cell(r, 1, f'التاريخ: {doc.doc_date}').font = reg; r += 2

    headers = ['الصنف', 'سعر الوحدة'] + [l.name for l in locs] + ['إجمالى الكمية', 'القيمة']
    ws.column_dimensions['A'].width = 30
    for i, h in enumerate(headers, start=1):
        cc = ws.cell(r, i, h); cc.font = wbold
        cc.fill = PatternFill('solid', fgColor=_HEADER_FILL); cc.alignment = ctr; cc.border = _BORDER
        if i > 2:
            ws.column_dimensions[get_column_letter(i)].width = 12
    r += 1

    col_sums = [0] * len(locs)
    for ln in doc.lines.all():
        cells = {ce.location_id: float(ce.quantity) for ce in ln.cells.all()}
        row_vals = [ln.item_name, float(ln.unit_price)]
        for j, l in enumerate(locs):
            v = cells.get(l.id, 0); col_sums[j] += v; row_vals.append(v)
        row_vals += [float(ln.quantity), float(ln.line_total)]
        for i, v in enumerate(row_vals, start=1):
            cc = ws.cell(r, i, v); cc.font = reg; cc.border = _BORDER
            cc.alignment = right if i == 1 else ctr
            if i == 2 or i >= len(headers) - 1:
                cc.number_format = '#,##0.00'
        r += 1

    # totals row
    tc = ws.cell(r, 1, 'الإجمالى'); tc.font = bold; tc.fill = PatternFill('solid', fgColor=_TOTAL_FILL); tc.border = _BORDER
    ws.cell(r, 2, '').fill = PatternFill('solid', fgColor=_TOTAL_FILL)
    for j, s in enumerate(col_sums):
        cc = ws.cell(r, 3 + j, s); cc.font = bold; cc.alignment = ctr
        cc.fill = PatternFill('solid', fgColor=_TOTAL_FILL); cc.border = _BORDER
    vc = ws.cell(r, len(headers), float(doc.total)); vc.font = bold; vc.number_format = '#,##0.00'
    vc.fill = PatternFill('solid', fgColor=_TOTAL_FILL); vc.border = _BORDER
    ws.cell(r, len(headers) - 1, '').fill = PatternFill('solid', fgColor=_TOTAL_FILL)
    return _resp(wb, doc.number)


def generate_invoice_excel(doc) -> HttpResponse:
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)
    if getattr(doc.doc_type, 'is_allocation', False):
        return generate_allocation_excel(doc)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = doc.doc_type.name[:28] or 'مستند'
    _rtl(ws)
    ws.page_setup.paperSize = 9  # A4
    ws.page_margins.left = ws.page_margins.right = 0.3
    ws.page_margins.top = ws.page_margins.bottom = 0.5

    rate = doc.vat_rate
    cols = [('م', 6), ('الصنف', 34), ('الكمية', 10), ('سعر الوحدة', 13),
            (f'ض.ق.م {rate}%', 13), ('الإجمالى', 14)]
    ncols = len(cols)
    for i, (_, w) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    bold = Font(name='Arial', bold=True, size=11)
    wbold = Font(name='Arial', bold=True, size=11, color='FFFFFFFF')
    reg  = Font(name='Arial', size=10)
    right = Alignment(horizontal='right', vertical='center', readingOrder=2)
    left  = Alignment(horizontal='left',  vertical='center', readingOrder=2)
    ctr   = Alignment(horizontal='center', vertical='center', readingOrder=2)

    r = 1
    # ── Title block ──────────────────────────────────────────────────────────
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    c = ws.cell(r, 1, f'{doc.doc_type.name} — {doc.number}')
    c.font = Font(name='Arial', bold=True, size=15); c.alignment = ctr
    ws.row_dimensions[r].height = 26; r += 1

    meta = [('الجهة', doc.recipient.name if doc.recipient else '—'),
            ('التاريخ', str(doc.doc_date)),
            ('الرقم الضريبي', doc.recipient.tax_id if doc.recipient else '')]
    if doc.valid_until:
        meta.append(('صالح حتى', str(doc.valid_until)))
    for label, val in meta:
        ws.cell(r, 1, label).font = bold
        ws.cell(r, 1).alignment = right
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=ncols)
        cc = ws.cell(r, 2, val); cc.font = reg; cc.alignment = right
        r += 1
    r += 1

    # ── Header row ───────────────────────────────────────────────────────────
    for i, (label, _) in enumerate(cols, start=1):
        cc = ws.cell(r, i, label); cc.font = wbold
        cc.fill = PatternFill('solid', fgColor=_HEADER_FILL)
        cc.alignment = ctr; cc.border = _BORDER
    ws.row_dimensions[r].height = 22; r += 1

    # ── Lines ────────────────────────────────────────────────────────────────
    for n, ln in enumerate(doc.lines.all(), start=1):
        vals = [n, ln.item_name, float(ln.quantity), float(ln.unit_price),
                float(ln.vat_amount(rate)), float(ln.line_total)]
        for i, v in enumerate(vals, start=1):
            cc = ws.cell(r, i, v)
            cc.font = reg; cc.border = _BORDER
            cc.alignment = ctr if i in (1, 3) else (left if i >= 4 else right)
            if i >= 4:
                cc.number_format = '#,##0.00'
        r += 1

    # ── Totals box ───────────────────────────────────────────────────────────
    r += 1
    for label, val in [('الإجمالى قبل الضريبة', doc.subtotal_ex_vat),
                       (f'ض.ق.م ({rate}%)', doc.vat_total),
                       ('الإجمالى شامل الضريبة', doc.total)]:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols - 1)
        lc = ws.cell(r, 1, label); lc.font = bold; lc.alignment = right
        lc.fill = PatternFill('solid', fgColor=_TOTAL_FILL)
        vc = ws.cell(r, ncols, float(val)); vc.font = bold; vc.alignment = left
        vc.number_format = '#,##0.00'; vc.fill = PatternFill('solid', fgColor=_TOTAL_FILL)
        r += 1

    if doc.notes:
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        nc = ws.cell(r, 1, f'ملاحظات: {doc.notes}'); nc.font = reg; nc.alignment = right

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{doc.number}.xlsx"'
    return resp
