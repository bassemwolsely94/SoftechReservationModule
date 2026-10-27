"""
apps/insurance/letter.py

Official cover-letter (خطاب تقديم) generator for an insurance claim — Word (.docx).

Word renders Arabic shaping + RTL natively, so no reshaper is needed; the user
can print to PDF from Word.  Reuses build_invoice_dataset() for the figures and
number_to_arabic_words() for the legal amount-in-words.

Also exposes build_submission_package(): a ZIP bundling the cover letter (.docx)
+ the full 4-sheet workbook (.xlsx), ready to hand to the insurer.
"""
import io
import zipfile
from datetime import date

from django.http import HttpResponse

try:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

from .invoice_builder import build_invoice_dataset
from .export import number_to_arabic_words, generate_excel, AR_MONTHS
from .models import InsuranceClaim


# ════════════════════════════════════════════════════════════════════════════════
# FIXED LETTER TEXT (identical on every motalba — do not change without sign-off)
# ════════════════════════════════════════════════════════════════════════════════

TAX_CARD_LABEL   = 'بطاقة ضريبية'
TAX_CARD_NUMBER  = '499336534'
COMM_REG_LABEL   = 'سجل تجاري'
COMM_REG_NUMBER  = '85195'

TITLE            = 'مطالبة سداد'
RECIPIENT        = 'السيد الاستاذ الدكتور / مدير عام الادارة الطبية – شركة الخدمات الطبية'
GREETING         = 'تحية طيبة وبعد ،،،،،،'

SIG_ROLES        = ['ادارة التعاقدات', 'المراجعة المالية', 'الادارة المالية']
SIG_PARENS       = '(                    )'
CHEQUE_LINE      = 'يصدر الشيك بأسم /  مجموعة الرزيقى لادارة الصيدليات (الرزيقى جروب )'
REGARDS          = 'وتفضلوا بقبول فائق الاحترام ،،،،،،'
RECEIPT_LINE     = 'استلمت اصل المطالبة والروشتات واصل الفاتورة الالكترونية للمراجعة والسداد'
RECEIVER_NAME    = 'اسم المستلم /'
RECEIVER_SIGN    = 'التوقيع /'
RECEIVER_STAMP   = 'الختم'

# Discount-table fixed header + category labels
TBL_HEADER       = ['التصنيف', 'نسبة الخصم', 'القيمة قبل الخصم', 'قيمة الخصم', 'صافى القيمة']
CAT_LOCAL        = 'محلى'
CAT_IMPORTED     = 'مستورد'
CAT_TARSIA       = 'الترسية'
CAT_TOTAL        = 'الاجمالى'

LETTER_FONT      = 'Arial'      # Arabic body font
NUM_FONT         = 'Calibri'    # numbers, matching the reference cover


# ── RTL / Arabic helpers ────────────────────────────────────────────────────────

def _set_rtl(paragraph):
    """Mark a paragraph right-to-left."""
    pPr = paragraph._p.get_or_add_pPr()
    bidi = pPr.makeelement(qn('w:bidi'), {})
    pPr.append(bidi)


def _font_run(run, size=14, bold=True, font=LETTER_FONT, color=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = rpr.makeelement(qn('w:rFonts'), {})
        rpr.append(rfonts)
    rfonts.set(qn('w:cs'), font)
    rfonts.set(qn('w:ascii'), font)
    rfonts.set(qn('w:hAnsi'), font)
    if color is not None:
        run.font.color.rgb = color


def _para(doc, text='', *, size=14, bold=True, align='right', color=None,
          space_after=4, font=LETTER_FONT):
    p = doc.add_paragraph()
    _set_rtl(p)
    p.alignment = {
        'right': WD_ALIGN_PARAGRAPH.RIGHT, 'center': WD_ALIGN_PARAGRAPH.CENTER,
        'left': WD_ALIGN_PARAGRAPH.LEFT, 'justify': WD_ALIGN_PARAGRAPH.JUSTIFY,
    }.get(align, WD_ALIGN_PARAGRAPH.RIGHT)
    p.paragraph_format.space_after = Pt(space_after)
    if text:
        _font_run(p.add_run(text), size=size, bold=bold, color=color, font=font)
    return p


def _set_cell_borders(cell, color='000000', sz=6):
    """Apply thin black borders to a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:color'), color)
        borders.append(el)
    tcPr.append(borders)


def _fmt(n):
    return f'{float(n or 0):,.2f}'


def _pct(p):
    p = float(p or 0)
    return f'{p:g}%'


def _ddmmyyyy(iso):
    """'2026-06-01' → '01/06/2026'."""
    try:
        y, m, d = iso[:10].split('-')
        return f'{d}/{m}/{y}'
    except Exception:
        return iso


def _month_year(iso):
    """'2026-06-01' → 'يونيو 2026'."""
    try:
        y, m, _ = iso[:10].split('-')
        return f'{AR_MONTHS[int(m)]} {y}'
    except Exception:
        return iso


def build_cover_letter_docx(claim: InsuranceClaim) -> bytes:
    """
    Official مطالبة سداد cover letter (.docx) matching the pharmacy chain's
    pre-printed letterhead format.  Fixed text is constant on every motalba;
    figures, period, client name, rx count and amount come from the claim.
    """
    if not HAS_DOCX:
        raise RuntimeError('python-docx not installed')

    ds    = build_invoice_dataset(claim)
    cover = ds['cover']
    meta  = ds['claim']

    client_full = meta.get('client_name', '')
    if meta.get('subclient_name'):
        client_full = f'{client_full} - {meta["subclient_name"]}'
    month_year = _month_year(meta['period_from'])
    pf = _ddmmyyyy(meta['period_from'])
    pt = _ddmmyyyy(meta['period_to'])
    net_digits = _fmt(cover['net_after'])
    net_words  = number_to_arabic_words(cover['net_after'])

    doc = Document()
    sec = doc.sections[0]
    sec.page_width   = Cm(21.0)
    sec.page_height  = Cm(29.7)
    sec.left_margin  = Cm(1.0)
    sec.right_margin = Cm(1.0)
    sec.top_margin   = Cm(4.75)   # space for the pre-printed company letterhead
    sec.bottom_margin = Cm(1.9)

    # ── Tax card + commercial register (fixed, top of page) ───────────────────
    _para(doc, TAX_CARD_LABEL,  space_after=0)
    _para(doc, TAX_CARD_NUMBER, space_after=0)
    _para(doc, COMM_REG_LABEL,  space_after=0)
    _para(doc, COMM_REG_NUMBER, space_after=8)

    # ── Title + recipient + greeting (fixed) ──────────────────────────────────
    _para(doc, TITLE, align='center', space_after=8)
    _para(doc, RECIPIENT, space_after=2)
    _para(doc, GREETING, align='center', space_after=10)

    # ── Body (dynamic) ────────────────────────────────────────────────────────
    _para(doc,
          f'مرسل لسيادتكم الروشتات الخاصة بمطالبة شهر {month_year} ({client_full})',
          align='justify', space_after=2)
    _para(doc, f'عن الفترة من {pf} الى {pt}', space_after=2)
    _para(doc, f'والتي تم صرفها من مجموعة صيدلياتنا وعدد الروشتات ({cover["rx_count"]}) .',
          space_after=2)

    # net value line — keep the digits run in Calibri like the reference
    p = doc.add_paragraph(); _set_rtl(p)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(10)
    _font_run(p.add_run('بصافى القيمة  ( '))
    _font_run(p.add_run(net_digits), font=NUM_FONT)
    _font_run(p.add_run(f') فقط / {net_words}) .'))

    # ── Discount breakdown table (dynamic figures) ────────────────────────────
    tbl_rows = [
        (CAT_LOCAL,    _pct(cover['local_disc_pct']),    cover['local_before'],
         cover['local_discount'],    cover['local_net']),
        (CAT_IMPORTED, _pct(cover['imported_disc_pct']), cover['imported_before'],
         cover['imported_discount'], cover['imported_net']),
        (CAT_TARSIA,   _pct(cover['tarsia_disc_pct']),   cover['tarsia_before'],
         cover['tarsia_discount'],   cover['tarsia_net']),
        (CAT_TOTAL,    '',                               cover['gross_before'],
         cover['total_discount'],    cover['net_after']),
    ]
    table = doc.add_table(rows=1 + len(tbl_rows), cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # RTL table direction
    tblPr = table._tbl.tblPr
    bidi = OxmlElement('w:bidiVisual'); tblPr.append(bidi)

    # Header row
    for j, htxt in enumerate(TBL_HEADER):
        cell = table.rows[0].cells[j]
        cell.text = ''
        _set_cell_borders(cell)
        pp = cell.paragraphs[0]; _set_rtl(pp); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font_run(pp.add_run(htxt), size=12, bold=True)

    # Data rows
    for i, (label, pct, before, disc, net) in enumerate(tbl_rows, start=1):
        is_total = (label == CAT_TOTAL)
        vals = [label, pct, _fmt(before), _fmt(disc), _fmt(net)]
        for j, v in enumerate(vals):
            cell = table.rows[i].cells[j]
            cell.text = ''
            _set_cell_borders(cell)
            pp = cell.paragraphs[0]; _set_rtl(pp); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # numeric columns (2,3,4) in Calibri
            fnt = NUM_FONT if j >= 2 else LETTER_FONT
            _font_run(pp.add_run(v), size=12, bold=is_total, font=fnt)

    doc.add_paragraph()

    # ── Signature roles (fixed, 3 columns) ────────────────────────────────────
    sig = doc.add_table(rows=2, cols=3)
    sig.alignment = WD_TABLE_ALIGNMENT.CENTER
    sbidi = OxmlElement('w:bidiVisual'); sig._tbl.tblPr.append(sbidi)
    for j, role in enumerate(SIG_ROLES):
        c = sig.rows[0].cells[j]; c.text = ''
        pp = c.paragraphs[0]; _set_rtl(pp); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font_run(pp.add_run(role), size=14, bold=True)
    for j in range(3):
        c = sig.rows[1].cells[j]; c.text = ''
        pp = c.paragraphs[0]; _set_rtl(pp); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font_run(pp.add_run(SIG_PARENS), size=14, bold=True)

    doc.add_paragraph()

    # ── Cheque + regards + receipt block (fixed) ──────────────────────────────
    _para(doc, CHEQUE_LINE, align='center', space_after=2)
    _para(doc, REGARDS, align='center', space_after=12)
    _para(doc, RECEIPT_LINE, space_after=6)
    _para(doc, RECEIVER_NAME, space_after=4)
    _para(doc, RECEIVER_SIGN, space_after=4)
    _para(doc, RECEIVER_STAMP, space_after=2)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_cover_letter(claim: InsuranceClaim) -> HttpResponse:
    if not HAS_DOCX:
        return HttpResponse('python-docx not installed', status=500)
    data = build_cover_letter_docx(claim)
    client = claim.subclient.client.name_short or claim.subclient.client.name
    filename = f'خطاب_تقديم_{client}_{claim.claim_number}.docx'
    resp = HttpResponse(
        data,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def generate_submission_package(claim: InsuranceClaim) -> HttpResponse:
    """ZIP bundle: cover letter (.docx) + full 4-sheet workbook (.xlsx)."""
    client = claim.subclient.client.name_short or claim.subclient.client.name
    base   = f'مطالبة_{client}_{claim.claim_number}'

    # Full workbook via the existing exporter (template='all')
    xlsx_resp = generate_excel(claim, template='all')
    xlsx_bytes = xlsx_resp.content

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{base}/الجداول_{claim.claim_number}.xlsx', xlsx_bytes)
        if HAS_DOCX:
            z.writestr(f'{base}/خطاب_تقديم_{claim.claim_number}.docx',
                       build_cover_letter_docx(claim))
    zbuf.seek(0)

    resp = HttpResponse(zbuf.getvalue(), content_type='application/zip')
    resp['Content-Disposition'] = f'attachment; filename="{base}.zip"'
    return resp
