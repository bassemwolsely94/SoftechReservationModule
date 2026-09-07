"""
apps/insurance/export.py

Excel export for insurance claims — 4 sheets.

يوميات:
  Column order (A→G, RTL display so G=right/م, A=left/صافى):
    A: صافى الفاتورة  B: الإجمالى قبل الخصم  C: المستورد  D: المحلى
    E: اسم المريض     F: تاريخ الصرف           G: م
  Structure per day:  header → data rows → subtotal → 4 blank rows
  Page breaks inserted before each day block that won't fit.
  Header/footer printed on every page.

مجمل اليوميات:
  One row per day + grand total.  Header/footer on every page.

الفاتورة النهائية المجمعة:
  Single summary row, landscape.

الغلاف:
  Claim metadata + discount breakdown table + total in digits and Arabic words.
"""
import io
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.pagebreak import Break
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from .invoice_builder import build_invoice_dataset
from .models import InsuranceClaim


# ═══════════════════════════════════════════════════════════════════════════════
# ARABIC NUMBER-TO-WORDS
# ═══════════════════════════════════════════════════════════════════════════════

def _ar_ones(n: int) -> str:
    return ['', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة',
            'ستة', 'سبعة', 'ثمانية', 'تسعة'][n]


def _ar_under100(n: int) -> str:
    if n == 0:   return ''
    if n <= 9:   return _ar_ones(n)
    if n == 10:  return 'عشرة'
    if n == 11:  return 'أحد عشر'
    if n == 12:  return 'اثنا عشر'
    if n <= 19:  return _ar_ones(n - 10) + ' عشر'
    tens = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون',
            'ستون', 'سبعون', 'ثمانون', 'تسعون'][n // 10]
    u = _ar_ones(n % 10)
    return (u + ' و ' + tens) if u else tens


def _ar_under1000(n: int) -> str:
    if n == 0: return ''
    h_words = ['', 'مائة', 'مئتان', 'ثلاثمائة', 'أربعمائة',
               'خمسمائة', 'ستمائة', 'سبعمائة', 'ثمانمائة', 'تسعمائة']
    h = h_words[n // 100]
    t = _ar_under100(n % 100)
    if h and t:
        return h + ' و ' + t
    return h or t


def _ar_under1m(n: int) -> str:
    """0–999,999"""
    if n == 0: return ''
    th, rem = divmod(n, 1000)
    if th == 0:
        return _ar_under1000(n)
    if th == 1:
        th_w = 'ألف'
    elif th == 2:
        th_w = 'ألفان'
    elif th <= 9:
        th_w = _ar_ones(th) + ' آلاف'
    else:
        th_w = _ar_under1000(th) + ' ألفاً'
    r = _ar_under1000(rem)
    return (th_w + ' و ' + r) if r else th_w


def _ar_full(n: int) -> str:
    """0–999,999,999"""
    if n == 0: return 'صفر'
    m, rem = divmod(n, 1_000_000)
    if m == 0:
        return _ar_under1m(n)
    if m == 1:
        m_w = 'مليون'
    elif m == 2:
        m_w = 'مليونان'
    elif m <= 9:
        m_w = _ar_ones(m) + ' ملايين'
    else:
        m_w = _ar_under1000(m) + ' مليوناً'
    r = _ar_under1m(rem)
    return (m_w + ' و ' + r) if r else m_w


def number_to_arabic_words(amount: float) -> str:
    """
    Convert EGP amount to Arabic words.

    646608.10 →
    'ستمائة و ستة و أربعون ألفاً و ستمائة و ثمانية جنيهاً و عشرة قروش فقط لا غير'
    """
    amount   = round(float(amount), 2)
    pounds   = int(amount)
    piastres = round((amount - pounds) * 100)

    # ── Pounds ──────────────────────────────────────────────────────────────
    p_base = _ar_full(pounds)
    if pounds == 1:
        p_text = p_base + ' جنيه'
    elif pounds == 2:
        p_text = 'جنيهان'
    elif pounds == 0:
        p_text = 'صفر جنيهاً'
    else:
        p_text = p_base + ' جنيهاً'

    # ── Piastres ─────────────────────────────────────────────────────────────
    if piastres == 0:
        return p_text + ' فقط لا غير'

    q_base = _ar_under100(piastres)
    if piastres == 1:
        q_text = q_base + ' قرش'
    elif piastres == 2:
        q_text = 'قرشان'
    elif piastres <= 10:
        q_text = q_base + ' قروش'
    else:
        q_text = q_base + ' قرشاً'

    return p_text + ' و ' + q_text + ' فقط لا غير'


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

H_HEADER    = 31.5
H_DATA      = 15.75
H_BLANK     = 15.75
N_BLANKS    = 4
H_COVER_HDR = 35.25
H_COVER_DATA = 15.0
H_COVER_TOT  = 17.1

# Conservative A4 portrait usable height after header/footer/margins (pts)
A4_USABLE = 620.0

# Column layouts are built dynamically: the ترسية (tarsia) column is inserted
# between الإجمالى قبل الخصم and المستورد قبل الخصم ONLY when the claim actually
# has tarsia items — matching the finance team's "New Edition" templates (which
# add the الترسية قبل الخصم column for tarsia-carrying motalbas, and omit it
# otherwise).

# Columns are defined in NATURAL logical order — م first (column A).  With the
# sheet's rightToLeft=True, column A lands on the RIGHT, so a printed Arabic
# motalba reads correctly (م, التاريخ, … on the right → الصافى on the left).  The
# same physical order also reads naturally when the user works in LTR.  (This was
# previously reversed, which printed م on the wrong side.)

def _yawmiyat_cols(has_tarsia: bool = False):
    cols = [
        ('م',                    'sequence',         6.5,  '0'),
        ('تاريخ الصرف',          'date',            12.0,  'YYYY-MM-DD'),
        ('اسم المريض',           'patient_name',    28.0,  None),
        ('المحلى قبل الخصم',    'local_before',    13.0,  '#,##0.00'),
        ('المستورد قبل الخصم',  'imported_before', 13.0,  '#,##0.00'),
    ]
    if has_tarsia:
        cols.append(('الترسية قبل الخصم', 'tarsia_before', 13.0, '#,##0.00'))
    cols += [
        ('الإجمالى قبل الخصم',  'gross_before',    15.0,  '#,##0.00'),
        ('صافى الفاتورة',        'net_after',       13.0,  '#,##0.00'),
    ]
    return cols


def _cover_cols(has_tarsia: bool = False):
    cols = [
        ('تاريخ الصرف',          'date',            23.0,  'YYYY-MM-DD'),
        ('عدد الروشتات',         'rx_count',        17.0,  '0'),
        ('المحلى قبل الخصم',    'local_before',    22.0,  '#,##0.00'),
        ('المستورد قبل الخصم',  'imported_before', 23.0,  '#,##0.00'),
    ]
    if has_tarsia:
        cols.append(('الترسية قبل الخصم', 'tarsia_before', 20.0, '#,##0.00'))
    cols += [
        ('الإجمالى قبل الخصم',  'gross_before',    23.0,  '#,##0.00'),
        ('صافى الفاتورة',        'net_after',       17.0,  '#,##0.00'),
    ]
    return cols


def _claim_has_tarsia(dataset: dict) -> bool:
    """True if the claim carries any tarsia value (cover or any day)."""
    try:
        if abs(float(dataset.get('cover', {}).get('tarsia_before', 0) or 0)) > 0.005:
            return True
        for d in dataset.get('days', []):
            if abs(float(d.get('day_totals', {}).get('tarsia_before', 0) or 0)) > 0.005:
                return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _f(bold=False, size=10, color='000000'):
    return Font(name='Arial', bold=bold, size=size, color=color)

def _a(h='right', v='center', wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap, readingOrder=2)

def _fill(hex_c):
    return PatternFill('solid', fgColor=hex_c)

def _bdr():
    s = Side(style='thin', color='BBBBBB')
    return Border(left=s, right=s, top=s, bottom=s)

FONT_HEADER   = _f(bold=True, size=10, color='FFFFFF')
FILL_HEADER   = _fill('1F4E79')
ALIGN_CENTER  = _a('center', 'center')
ALIGN_RIGHT   = _a('right',  'center')
FONT_SUBTOTAL = _f(bold=True, size=10)
FILL_SUBTOTAL = _fill('D6E4F0')
FONT_GRAND    = _f(bold=True, size=11)
FILL_GRAND    = _fill('E2EFDA')
FONT_DATA     = _f(size=10)
FILL_COVER_HDR = _fill('2E75B6')
FONT_COVER_HDR = _f(bold=True, size=11, color='FFFFFF')
BORDER         = _bdr()

AR_MONTHS = ['', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
             'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

# ── Fixed cover-letter (مطالبة سداد) text — identical on every motalba ───────────
COVER_TAX_CARD_LABEL  = 'بطاقة ضريبية'
COVER_TAX_CARD_NUMBER = '499336534'
COVER_COMM_REG_LABEL  = 'سجل تجاري'
COVER_COMM_REG_NUMBER = '85195'
COVER_TITLE           = 'مطالبة سداد'
COVER_RECIPIENT       = 'السيد الاستاذ الدكتور / مدير عام الادارة الطبية – شركة الخدمات الطبية'
COVER_GREETING        = 'تحية طيبة وبعد ،،،،،،'
COVER_SIG_ROLES       = ['ادارة التعاقدات', 'المراجعة المالية', 'الادارة المالية']
COVER_SIG_PARENS      = '(                    )'
COVER_CHEQUE_LINE     = 'يصدر الشيك بأسم /  مجموعة الرزيقى لادارة الصيدليات (الرزيقى جروب )'
COVER_REGARDS         = 'وتفضلوا بقبول فائق الاحترام ،،،،،،'
COVER_RECEIPT_LINE    = 'استلمت اصل المطالبة والروشتات واصل الفاتورة الالكترونية للمراجعة والسداد'
COVER_RECEIVER_NAME   = 'اسم المستلم /'
COVER_RECEIVER_SIGN   = 'التوقيع /'
COVER_RECEIVER_STAMP  = 'الختم'
COVER_TBL_HEADER      = ['التصنيف', 'نسبة الخصم', 'القيمة قبل الخصم', 'قيمة الخصم', 'صافى القيمة']


def _ddmmyyyy(iso) -> str:
    """'2026-06-01' → '01/06/2026'."""
    try:
        y, m, d = str(iso)[:10].split('-')
        return f'{d}/{m}/{y}'
    except Exception:
        return str(iso)


def _month_year_ar(iso) -> str:
    """'2026-06-01' → 'يونيو 2026'."""
    try:
        y, m, _ = str(iso)[:10].split('-')
        return f'{AR_MONTHS[int(m)]} {y}'
    except Exception:
        return str(iso)


def _pct_str(p) -> str:
    return f'{float(p or 0):g}%'


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMIZABLE STYLE RESOLUTION  (from InsuranceExportProfile)
# ═══════════════════════════════════════════════════════════════════════════════

def _placeholder_ctx(dataset: dict) -> dict:
    """Build the placeholder values for header/footer substitution."""
    claim = dataset.get('claim', {})
    cover = dataset.get('cover', {})
    pf = (claim.get('period_from') or '')[:10]
    month = ''
    try:
        y, m, _ = pf.split('-')
        month = f'{AR_MONTHS[int(m)]} {y}'
    except Exception:
        pass
    # Call-center numbers from the pharmacy profile (reuse)
    call_center = ''
    try:
        from apps.config.models import PharmacyProfile
        call_center = (PharmacyProfile.get().call_center_numbers or '').replace('\n', ' - ')
    except Exception:
        pass
    return {
        'client':       claim.get('client_name', ''),
        'subclient':    claim.get('subclient_name', ''),
        'claim_number': claim.get('claim_number', ''),
        'month':        month,
        'period_from':  pf,
        'period_to':    (claim.get('period_to') or '')[:10],
        'rx_count':     str(cover.get('rx_count', '')),
        'net':          f"{float(cover.get('net_after', 0) or 0):,.2f}",
        'call_center':  call_center,
    }


def _subst_hf(template: str, ctx: dict, font_name: str) -> str:
    """Substitute {placeholders} and map {page}/{pages} → openpyxl &P/&N codes."""
    if not template:
        return ''
    text = template
    for k, v in ctx.items():
        text = text.replace('{' + k + '}', str(v))
    text = text.replace('{page}', '&P').replace('{pages}', '&N')
    # Print header/footer font is fixed to Calibri Bold 12 across all sheets.
    return '&"Calibri,Bold"&12' + text


def _apply_watermark(ws, st: dict):
    """Insert the profile's watermark image (a pre-faded PNG) onto the sheet."""
    wm = (st or {}).get('watermark')
    if not wm:
        return
    try:
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(wm['path'])
        # Scale to the requested width (cm → px at 96 DPI), keep aspect ratio
        target_px = int(float(wm['width_cm']) * 37.8)
        if img.width:
            ratio = target_px / float(img.width)
            img.width  = target_px
            img.height = int(img.height * ratio)
        ws.add_image(img, wm.get('anchor', 'C15'))
    except Exception:
        pass


def _border_for(style_name: str) -> Border:
    if style_name == 'none':
        return Border()
    s = Side(style=style_name, color='BBBBBB' if style_name == 'thin' else '888888')
    return Border(left=s, right=s, top=s, bottom=s)


def resolve_style(claim, dataset: dict) -> dict:
    """
    Resolve the export style for a claim from its InsuranceExportProfile
    (subclient-specific → global default → built-in constants).
    Returns a dict of openpyxl objects + header/footer texts + layout values.
    """
    try:
        from .models import InsuranceExportProfile
        prof = InsuranceExportProfile.resolve_for_claim(claim) if claim else None
    except Exception:
        prof = None

    if not prof:
        # Built-in defaults (current behavior preserved)
        return {
            'profile':       None,
            'watermark':     None,
            'font_header':   FONT_HEADER,   'fill_header':   FILL_HEADER,
            'font_subtotal': FONT_SUBTOTAL, 'fill_subtotal': FILL_SUBTOTAL,
            'font_grand':    FONT_GRAND,    'fill_grand':    FILL_GRAND,
            'font_data':     FONT_DATA,     'border':        BORDER,
            'n_blanks':      N_BLANKS,      'repeat_header': True,
            'hf':            None,          # → use legacy _header_footer text
        }

    fn = prof.font_name or 'Arial'
    ctx = _placeholder_ctx(dataset)

    # Watermark: resolve the file path if an image is set
    wm = None
    try:
        if prof.watermark_image and prof.watermark_image.path:
            import os as _os
            if _os.path.exists(prof.watermark_image.path):
                wm = {
                    'path':     prof.watermark_image.path,
                    'width_cm': float(prof.watermark_width_cm or 8),
                    'anchor':   prof.watermark_anchor or 'C15',
                }
    except Exception:
        wm = None

    return {
        'profile':       prof,
        'watermark':     wm,
        'font_header':   _f(bold=True, size=prof.header_font_size, color=prof.header_font_color),
        'fill_header':   _fill(prof.header_fill),
        'font_subtotal': Font(name=fn, bold=True, size=prof.subtotal_font_size),
        'fill_subtotal': _fill(prof.subtotal_fill),
        'font_grand':    Font(name=fn, bold=True, size=prof.total_font_size),
        'fill_grand':    _fill(prof.total_fill),
        'font_data':     Font(name=fn, size=prof.header_font_size),
        'border':        _border_for(prof.border_style),
        'n_blanks':      prof.day_block_blank_rows,
        'repeat_header': prof.repeat_header_each_page,
        'hf': {
            'left':   _subst_hf(prof.header_left,   ctx, fn),
            'center': _subst_hf(prof.header_center, ctx, fn),
            'right':  _subst_hf(prof.header_right,  ctx, fn),
            'fleft':   _subst_hf(prof.footer_left,   ctx, fn),
            'fcenter': _subst_hf(prof.footer_center, ctx, fn),
            'fright':  _subst_hf(prof.footer_right,  ctx, fn),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE SETUP HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _margins(ws, orientation='portrait'):
    """Apply consistent A4 margins with minimal side margins and visible header/footer."""
    ws.page_setup.paperSize   = 9          # A4
    ws.page_setup.orientation = orientation
    # Side margins: very narrow (0.2 in ≈ 0.5 cm)
    ws.page_margins.left   = 0.20
    ws.page_margins.right  = 0.20
    # Top/bottom: must exceed header/footer gap to keep them fully visible.
    # header gap 0.35" → content starts at 0.80" → 0.45" (≈32 pt) for header text.
    # footer gap 0.30" → content ends at 0.65" → 0.35" (≈25 pt) for footer text.
    ws.page_margins.top    = 0.80
    ws.page_margins.bottom = 0.65
    ws.page_margins.header = 0.35
    ws.page_margins.footer = 0.30


def _header_footer(ws, claim_meta: dict, sheet_title: str, repeat_header_row: bool = True,
                   st: dict = None):
    """
    Set print header and footer on every page.

    When a custom profile is active (st['hf'] present) the user-defined 3-section
    header + footer are used (with placeholders already substituted).  Otherwise
    the built-in default layout is applied (backward compatible).
    """
    hf = (st or {}).get('hf')
    if hf:
        ws.oddHeader.left.text   = hf['left']
        ws.oddHeader.center.text = hf['center']
        ws.oddHeader.right.text  = hf['right']
        ws.oddFooter.left.text   = hf['fleft']
        ws.oddFooter.center.text = hf['fcenter']
        ws.oddFooter.right.text  = hf['fright']
        if repeat_header_row and (st or {}).get('repeat_header', True):
            ws.print_title_rows = '1:1'
        return

    # ── Built-in default layout ───────────────────────────────────────────────
    client   = claim_meta.get('client_name', '')
    sub      = claim_meta.get('subclient_name', '')
    p_from   = claim_meta.get('period_from', '')[:10]
    p_to     = claim_meta.get('period_to', '')[:10]
    claim_no = claim_meta.get('claim_number', '')

    # All print header/footer sections use Calibri Bold 12 (chain-wide standard).
    # The font/size code (&"Calibri,Bold"&12) must appear ONCE at the start of
    # each section and be followed by a non-digit — otherwise Excel's parser
    # swallows leading digits (e.g. a date's year) into the size token.
    cb = '&"Calibri,Bold"&12'

    ws.oddHeader.right.text  = f'{cb}شركة الرزيقي لإدارة الصيدليات\n{client} — {sub}'
    ws.oddHeader.center.text = f'{cb}{sheet_title}\n{p_from}  –  {p_to}'
    ws.oddHeader.left.text   = f'{cb}رقم المطالبة:\n{claim_no}'

    ws.oddFooter.center.text = f'{cb}صفحة &P من &N'

    if repeat_header_row:
        ws.print_title_rows = '1:1'


# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL CELL WRITER
# ═══════════════════════════════════════════════════════════════════════════════

def _w(ws, row, col, val, *, font=None, fill=None, align=None, fmt=None, border=None):
    cell = ws.cell(row=row, column=col, value=val)
    cell.font      = font  or FONT_DATA
    cell.alignment = align or ALIGN_RIGHT
    cell.border    = border if border is not None else BORDER
    if fill:
        cell.fill = fill
    if fmt and val is not None:
        cell.number_format = fmt
    return cell


def _set_row_height(ws, row_num, height):
    ws.row_dimensions[row_num].height = height


def _to_date(val):
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except Exception:
            pass
    return val


def _to_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return val


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET 1 — يوميات
# ═══════════════════════════════════════════════════════════════════════════════

class _PageTracker:
    def __init__(self, usable=A4_USABLE, n_blanks=N_BLANKS):
        self._usable  = usable
        self._current = 0.0
        self._n_blanks = n_blanks

    def day_block_height(self, n_rx: int) -> float:
        return H_HEADER + n_rx * H_DATA + H_HEADER + self._n_blanks * H_BLANK

    def fits(self, block_h: float) -> bool:
        if self._current == 0:
            return True
        if block_h > self._usable:
            return True
        return (self._current + block_h) <= self._usable

    def add(self, h: float):
        self._current += h

    def new_page(self):
        self._current = 0.0


def _write_global_header(ws, row, st, cols):
    _set_row_height(ws, row, H_HEADER)
    for col, (hdr, _, _, _) in enumerate(cols, start=1):
        _w(ws, row, col, hdr, font=st['font_header'], fill=st['fill_header'],
           align=ALIGN_CENTER, border=st['border'])
    return row + 1


def _write_day_header(ws, row, st, cols):
    return _write_global_header(ws, row, st, cols)


def _write_data_row(ws, row, rx, day_date, st, cols, seq_val=None):
    _set_row_height(ws, row, H_DATA)
    date_val = _to_date(day_date)
    values = {
        'net_after':       _to_float(rx.get('net_after')),
        'gross_before':    _to_float(rx.get('gross_before')),
        'tarsia_before':   _to_float(rx.get('tarsia_before')),
        'imported_before': _to_float(rx.get('imported_before')),
        'local_before':    _to_float(rx.get('local_before')),
        'patient_name':    rx.get('patient_name', ''),
        'date':            date_val,
        'sequence':        seq_val if seq_val is not None else rx.get('sequence'),
    }
    # NOTE: the SOFTECH-mismatch highlight is intentionally NOT applied to the
    # Excel output — it lives only in the frontend.  The printed/exported sheets
    # stay clean.
    for col, (_, key, _, fmt) in enumerate(cols, start=1):
        _w(ws, row, col, values.get(key), fmt=fmt, font=st['font_data'],
           border=st['border'])
    return row + 1


# Numeric keys carry a number format on the subtotal row; label keys don't.
_SUBTOTAL_NUMERIC_KEYS = {'net_after', 'gross_before', 'tarsia_before',
                         'imported_before', 'local_before'}


def _write_subtotal(ws, row, dt: dict, day_key: str, rx_count: int, st, cols):
    _set_row_height(ws, row, H_HEADER)
    if day_key and day_key not in ('ملحق سابق', 'ملحق لاحق', 'before_claim', 'after_claim'):
        try:
            d = date.fromisoformat(day_key[:10])
            date_label = d.strftime('%Y-%m-%d')
        except Exception:
            date_label = day_key
    else:
        date_label = 'ملحق'
    values = {
        'net_after':       _to_float(dt.get('net_after')),
        'gross_before':    _to_float(dt.get('gross_before')),
        'tarsia_before':   _to_float(dt.get('tarsia_before')),
        'imported_before': _to_float(dt.get('imported_before')),
        'local_before':    _to_float(dt.get('local_before')),
        'patient_name':    f'عدد الروشتات: {rx_count}',
        'date':            f'إجمالى يوم: {date_label}',
        'sequence':        None,
    }
    for col, (_, key, _, fmt) in enumerate(cols, start=1):
        use_fmt = fmt if key in _SUBTOTAL_NUMERIC_KEYS else None
        _w(ws, row, col, values.get(key), font=st['font_subtotal'],
           fill=st['fill_subtotal'], fmt=use_fmt, border=st['border'])
    return row + 1


def _write_blanks(ws, row, ncols, n=N_BLANKS):
    for i in range(n):
        _set_row_height(ws, row + i, H_BLANK)
        for col in range(1, ncols + 1):
            ws.cell(row=row + i, column=col, value=None)
    return row + n


def _build_sheet_yawmiyat(wb, dataset: dict, st: dict = None):
    st = st or resolve_style(None, dataset)
    n_blanks = st['n_blanks']
    ws = wb.create_sheet('يوميات')
    ws.sheet_view.rightToLeft = True

    _margins(ws, 'portrait')
    # Always apply the full header + footer (custom profile when active, else the
    # built-in default layout). The per-day header rows repeat inside the body, so
    # we don't also repeat row 1 as a print-title row here.
    _header_footer(ws, dataset['claim'], 'يوميات المطالبة', repeat_header_row=False, st=st)

    cols  = _yawmiyat_cols(_claim_has_tarsia(dataset))
    ncols = len(cols)
    for col, (_, _, width, _) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    row     = 1
    tracker = _PageTracker(n_blanks=n_blanks)
    serial  = 0   # continuous 1..N serial for the م column (independent of day grouping)

    # 1. Global header row
    row = _write_global_header(ws, row, st, cols)
    tracker.add(H_HEADER)

    before_supp_days = [d for d in dataset['days'] if d.get('is_supplement')
                        and d.get('supplement_type') in ('before_claim', None)
                        and d.get('prescriptions')]
    main_days        = [d for d in dataset['days']
                        if not (d.get('is_supplement')
                                and d.get('supplement_type') in ('before_claim', None))]

    # 2. Before-supplement blocks
    for sup_day in before_supp_days:
        rxs  = sup_day['prescriptions']
        dt   = sup_day['day_totals']
        n_rx = len(rxs)
        day_k = sup_day['date']
        for rx in rxs:
            serial += 1
            row = _write_data_row(ws, row, rx, day_k, st, cols, seq_val=serial)
            tracker.add(H_DATA)
        row = _write_subtotal(ws, row, dt, 'ملحق', n_rx, st, cols)
        tracker.add(H_HEADER)
        row = _write_blanks(ws, row, ncols, n_blanks)
        tracker.add(n_blanks * H_BLANK)

    # 3. Main day blocks
    for day in main_days:
        rxs  = day.get('prescriptions', [])
        if not rxs:
            continue
        dt    = day['day_totals']
        n_rx  = dt.get('rx_count', len(rxs))
        day_k = day['date']
        block_h = tracker.day_block_height(len(rxs))
        if not tracker.fits(block_h):
            ws.row_breaks.append(Break(id=row - 1))
            tracker.new_page()
        row = _write_day_header(ws, row, st, cols)
        tracker.add(H_HEADER)
        for rx in rxs:
            serial += 1
            row = _write_data_row(ws, row, rx, day_k, st, cols, seq_val=serial)
            tracker.add(H_DATA)
        row = _write_subtotal(ws, row, dt, day_k, n_rx, st, cols)
        tracker.add(H_HEADER)
        row = _write_blanks(ws, row, ncols, n_blanks)
        tracker.add(n_blanks * H_BLANK)

    # 4. After-supplement blocks
    after_supp_days = [d for d in dataset['days'] if d.get('is_supplement')
                       and d.get('supplement_type') == 'after_claim'
                       and d.get('prescriptions')]
    for sup_day in after_supp_days:
        rxs  = sup_day['prescriptions']
        dt   = sup_day['day_totals']
        n_rx = len(rxs)
        day_k = sup_day['date']
        block_h = tracker.day_block_height(len(rxs))
        if not tracker.fits(block_h):
            ws.row_breaks.append(Break(id=row - 1))
            tracker.new_page()
        row = _write_day_header(ws, row, st, cols)
        tracker.add(H_HEADER)
        for rx in rxs:
            serial += 1
            row = _write_data_row(ws, row, rx, day_k, st, cols, seq_val=serial)
            tracker.add(H_DATA)
        row = _write_subtotal(ws, row, dt, 'ملحق', n_rx, st, cols)
        tracker.add(H_HEADER)
        row = _write_blanks(ws, row, ncols, n_blanks)
        tracker.add(n_blanks * H_BLANK)


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET 1 (alt) — يوميات FLAT: one continuous list, custom-sorted, NO day grouping
# ═══════════════════════════════════════════════════════════════════════════════

_FLAT_SORT_KEYS = {
    'patient_name': lambda r: (r.get('patient_name') or '').strip(),
    'date':         lambda r: r.get('_date') or '',
    'net':          lambda r: _to_float(r.get('net_after')),
    'gross':        lambda r: _to_float(r.get('gross_before')),
    'docnumber':    lambda r: (r.get('docnumber') or ''),
}


def _build_sheet_flat(wb, dataset: dict, st: dict = None,
                      sort_by: str = 'patient_name', sort_dir: str = 'asc'):
    """
    يوميات as a single flat, custom-sorted table — every prescription is one row,
    all columns kept, NO per-day header/subtotal blocks, one grand total at the end.
    Used for special client requests (e.g. order alphabetically by patient name).
    """
    st = st or resolve_style(None, dataset)
    ws = wb.create_sheet('يوميات')
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'portrait')
    _header_footer(ws, dataset['claim'], 'يوميات المطالبة', repeat_header_row=False, st=st)

    cols  = _yawmiyat_cols(_claim_has_tarsia(dataset))
    ncols = len(cols)
    for col, (_, _, width, _) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    # Flatten every displayed row across all days, keeping each row's own date.
    rows = []
    for d in dataset.get('days', []):
        day_date = d.get('date')
        for rx in d.get('prescriptions', []):
            rx = dict(rx)
            rx['_date'] = day_date
            rows.append(rx)

    keyfn = _FLAT_SORT_KEYS.get(sort_by, _FLAT_SORT_KEYS['patient_name'])
    try:
        rows.sort(key=keyfn, reverse=(sort_dir == 'desc'))
    except TypeError:
        rows.sort(key=lambda r: str(keyfn(r)), reverse=(sort_dir == 'desc'))

    row = 1
    row = _write_global_header(ws, row, st, cols)
    serial = 0
    for rx in rows:
        serial += 1
        row = _write_data_row(ws, row, rx, rx.get('_date'), st, cols, seq_val=serial)

    # Single grand total row
    gt = dataset['claim_totals']
    _set_row_height(ws, row, H_HEADER)
    gvalues = {
        'net_after':       _to_float(gt.get('net_after')),
        'gross_before':    _to_float(gt.get('gross_before')),
        'tarsia_before':   _to_float(gt.get('tarsia_before')),
        'imported_before': _to_float(gt.get('imported_before')),
        'local_before':    _to_float(gt.get('local_before')),
        'patient_name':    f'إجمالى: {serial} روشتة',
        'date':            'الإجمالى الكلى',
        'sequence':        None,
    }
    for col, (_, key, _, fmt) in enumerate(cols, start=1):
        use_fmt = fmt if key in _SUBTOTAL_NUMERIC_KEYS else None
        _w(ws, row, col, gvalues.get(key), font=st['font_subtotal'],
           fill=st['fill_subtotal'], fmt=use_fmt, border=st['border'])


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET 2 — مجمل اليوميات
# ═══════════════════════════════════════════════════════════════════════════════

def _build_sheet_cover_ready(wb, dataset: dict, st: dict = None):
    st = st or resolve_style(None, dataset)
    ws = wb.create_sheet('مجمل اليوميات')
    ws.sheet_view.rightToLeft = True

    _margins(ws, 'portrait')
    # repeat_header_row=True: this sheet is one continuous table with a
    # single header row, so repeating row 1 on every page is correct.
    _header_footer(ws, dataset['claim'], 'مجمل اليوميات', repeat_header_row=True, st=st)

    cols = _cover_cols(_claim_has_tarsia(dataset))
    for col, (_, _, width, _) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    row = 1

    # Table header
    _set_row_height(ws, row, H_COVER_HDR)
    for col, (hdr, _, _, _) in enumerate(cols, start=1):
        _w(ws, row, col, hdr, font=FONT_COVER_HDR, fill=FILL_COVER_HDR, align=ALIGN_CENTER)
    row += 1

    def _row_values(src: dict, date_or_label):
        return {
            'net_after':       _to_float(src.get('net_after')),
            'gross_before':    _to_float(src.get('gross_before')),
            'tarsia_before':   _to_float(src.get('tarsia_before')),
            'imported_before': _to_float(src.get('imported_before')),
            'local_before':    _to_float(src.get('local_before')),
            'rx_count':        src.get('rx_count', 0),
            'date':            date_or_label,
        }

    def _write_cover_row(day_data: dict, is_sup=False):
        nonlocal row
        _set_row_height(ws, row, H_COVER_DATA)
        dt    = day_data['day_totals']
        day_k = day_data['date']
        date_val = (_to_date(day_k)
                    if day_k not in ('ملحق سابق', 'ملحق لاحق', 'before_claim', 'after_claim')
                    else 'ملحق')
        vals = _row_values(dt, date_val)
        fill = FILL_SUBTOTAL if is_sup else None
        for col, (_, key, _, fmt) in enumerate(cols, start=1):
            val = vals.get(key)
            use_fmt = fmt if not isinstance(val, str) else None
            _w(ws, row, col, val, fill=fill, fmt=use_fmt)
        row += 1

    for day in dataset['days']:
        if not day.get('prescriptions'):
            continue
        _write_cover_row(day, is_sup=day.get('is_supplement', False))

    # Grand total row
    ct = dataset['claim_totals']
    _set_row_height(ws, row, H_COVER_TOT)
    gvals = _row_values(ct, 'الإجمالى')
    for col, (_, key, _, fmt) in enumerate(cols, start=1):
        val = gvals.get(key)
        use_fmt = fmt if not isinstance(val, str) else None
        _w(ws, row, col, val, font=FONT_GRAND, fill=FILL_GRAND, fmt=use_fmt)


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET 3 — الفاتورة النهائية المجمعة
# ═══════════════════════════════════════════════════════════════════════════════

def _build_sheet_grand_total(wb, dataset: dict, st: dict = None):
    st = st or resolve_style(None, dataset)
    ws = wb.create_sheet('الفاتورة النهائية المجمعة')
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')
    _header_footer(ws, dataset['claim'], 'الفاتورة النهائية المجمعة', repeat_header_row=False, st=st)

    COLS = [
        ('رقم المطالبة',        'claim_number',    22, None),
        ('اسم الجهة',           'client_name',     28, None),
        ('الفئة',               'subclient_name',  20, None),
        ('من تاريخ',            'period_from',     14, 'YYYY-MM-DD'),
        ('إلى تاريخ',           'period_to',       14, 'YYYY-MM-DD'),
        ('عدد الروشتات',         'rx_count',        12, '0'),
        ('الإجمالى قبل الخصم',  'gross_before',    17, '#,##0.00'),
        ('إجمالى الخصم',         'total_discount',  17, '#,##0.00'),
        ('صافى الفاتورة',        'net_after',       17, '#,##0.00'),
    ]

    for col, (_, _, w, _) in enumerate(COLS, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    _set_row_height(ws, 1, 25.0)
    for col, (hdr, _, _, _) in enumerate(COLS, start=1):
        _w(ws, 1, col, hdr, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)

    claim = dataset['claim']
    cover = dataset['cover']
    vals  = {
        'claim_number':   claim['claim_number'],
        'client_name':    claim['client_name'],
        'subclient_name': claim['subclient_name'],
        'period_from':    _to_date(claim['period_from']),
        'period_to':      _to_date(claim['period_to']),
        'rx_count':       cover['rx_count'],
        'gross_before':   cover['gross_before'],
        'total_discount': cover['total_discount'],
        'net_after':      cover['net_after'],
    }
    _set_row_height(ws, 2, 22.0)
    for col, (_, key, _, fmt) in enumerate(COLS, start=1):
        _w(ws, 2, col, vals[key], font=FONT_GRAND, fill=FILL_GRAND, fmt=fmt)


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET 4 — الغلاف
# ═══════════════════════════════════════════════════════════════════════════════

def _build_sheet_cover_letter(wb, dataset: dict, st: dict = None):
    """
    الغلاف — official مطالبة سداد cover letter, mirroring the pharmacy chain's
    pre-printed letterhead (and the .docx produced by apps/insurance/letter.py).
    Fixed text is constant; figures/period/client/rx-count/amount are dynamic.
    """
    st = st or resolve_style(None, dataset)
    ws = wb.create_sheet('الغلاف')
    ws.sheet_view.rightToLeft = True
    ws.page_setup.paperSize   = 9          # A4
    ws.page_setup.orientation = 'portrait'
    # Minimal side margins; large top for the pre-printed letterhead area.
    ws.page_margins.left   = 0.20
    ws.page_margins.right  = 0.20
    ws.page_margins.top    = 1.85
    ws.page_margins.bottom = 0.55
    ws.page_margins.header = 0.0
    ws.page_margins.footer = 0.0

    # 5 columns = the discount table (التصنيف | نسبة | قبل | خصم | صافى)
    ws.column_dimensions['A'].width = 16
    ws.column_dimensions['B'].width = 13
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 16
    ws.column_dimensions['E'].width = 18

    claim = dataset['claim']
    cover = dataset['cover']
    bdr   = _bdr()

    AR  = 'Arial'
    NUM = 'Calibri'

    def _line(row, text, *, size=14, bold=True, align='right', font=AR, height=20):
        """Full-width (A:E) merged line of letter text."""
        _set_row_height(ws, row, height)
        cell = ws.cell(row=row, column=1, value=text)
        cell.font = Font(name=font, bold=bold, size=size)
        cell.alignment = Alignment(horizontal=align, vertical='center',
                                   wrap_text=True, readingOrder=2)
        ws.merge_cells(f'A{row}:E{row}')
        return row + 1

    # Dynamic substitutions
    client_full = claim.get('client_name', '')
    if claim.get('subclient_name'):
        client_full = f'{client_full} - {claim["subclient_name"]}'
    month_year = _month_year_ar(claim['period_from'])
    pf = _ddmmyyyy(claim['period_from'])
    pt = _ddmmyyyy(claim['period_to'])
    net = cover['net_after']
    net_digits = f'{float(net or 0):,.2f}'
    net_words  = number_to_arabic_words(net)

    row = 1
    # ── Tax card + commercial register (fixed) ────────────────────────────────
    row = _line(row, COVER_TAX_CARD_LABEL,  height=18)
    row = _line(row, COVER_TAX_CARD_NUMBER, font=NUM, height=18)
    row = _line(row, COVER_COMM_REG_LABEL,  height=18)
    row = _line(row, COVER_COMM_REG_NUMBER, font=NUM, height=18)
    row += 1

    # ── Title / recipient / greeting (fixed) ──────────────────────────────────
    row = _line(row, COVER_TITLE, align='center', height=24)
    row = _line(row, COVER_RECIPIENT, height=22)
    row = _line(row, COVER_GREETING, align='center', height=22)
    row += 1

    # ── Body (dynamic) ────────────────────────────────────────────────────────
    row = _line(row, f'مرسل لسيادتكم الروشتات الخاصة بمطالبة شهر {month_year} ({client_full})', height=36)
    row = _line(row, f'عن الفترة من {pf} الى {pt}', height=20)
    row = _line(row, f'والتي تم صرفها من مجموعة صيدلياتنا وعدد الروشتات ({cover["rx_count"]}) .', height=20)
    row = _line(row, f'بصافى القيمة  ( {net_digits}) فقط / {net_words}) .', height=40)
    row += 1

    # ── Discount breakdown table (header fixed, figures dynamic) ──────────────
    _set_row_height(ws, row, 24)
    for col, hdr in enumerate(COVER_TBL_HEADER, 1):
        c = ws.cell(row=row, column=col, value=hdr)
        c.font      = FONT_COVER_HDR
        c.fill      = FILL_COVER_HDR
        c.alignment = ALIGN_CENTER
        c.border    = bdr
    row += 1

    cat_rows = [
        ('محلى',     _pct_str(cover['local_disc_pct']),    cover['local_before'],    cover['local_discount'],    cover['local_net'],    False),
        ('مستورد',   _pct_str(cover['imported_disc_pct']), cover['imported_before'], cover['imported_discount'], cover['imported_net'], False),
        ('الترسية',  _pct_str(cover['tarsia_disc_pct']),   cover['tarsia_before'],   cover['tarsia_discount'],   cover['tarsia_net'],   False),
        ('الاجمالى', '',                                   cover['gross_before'],    cover['total_discount'],    cover['net_after'],    True),
    ]
    for label, pct, before, disc, after, is_grand in cat_rows:
        _set_row_height(ws, row, 22)
        fill = FILL_GRAND if is_grand else None
        # col 1: category label (Arial)
        c = ws.cell(row=row, column=1, value=label)
        c.font = Font(name=AR, bold=is_grand, size=12); c.alignment = ALIGN_CENTER; c.border = bdr
        if fill: c.fill = fill
        # col 2: pct (Calibri)
        c = ws.cell(row=row, column=2, value=pct)
        c.font = Font(name=NUM, bold=is_grand, size=12); c.alignment = ALIGN_CENTER; c.border = bdr
        if fill: c.fill = fill
        # cols 3-5: figures (Calibri, 2dp)
        for col, val in ((3, before), (4, disc), (5, after)):
            c = ws.cell(row=row, column=col, value=float(val or 0))
            c.font = Font(name=NUM, bold=is_grand, size=12)
            c.alignment = ALIGN_CENTER; c.border = bdr; c.number_format = '#,##0.00'
            if fill: c.fill = fill
        row += 1

    row += 2

    # ── Signature roles + parens (fixed, 3 columns spread across A:E) ─────────
    role_cols = ['A', 'C', 'E']
    _set_row_height(ws, row, 22)
    for letter, role in zip(role_cols, COVER_SIG_ROLES):
        col = ord(letter) - 64
        c = ws.cell(row=row, column=col, value=role)
        c.font = Font(name=AR, bold=True, size=12); c.alignment = ALIGN_CENTER
    row += 1
    _set_row_height(ws, row, 22)
    for letter in role_cols:
        col = ord(letter) - 64
        c = ws.cell(row=row, column=col, value=COVER_SIG_PARENS)
        c.font = Font(name=AR, bold=True, size=12); c.alignment = ALIGN_CENTER
    row += 2

    # ── Cheque + regards + receipt block (fixed) ──────────────────────────────
    row = _line(row, COVER_CHEQUE_LINE, align='center', height=22)
    row = _line(row, COVER_REGARDS, align='center', height=22)
    row += 1
    row = _line(row, COVER_RECEIPT_LINE, height=22)
    row = _line(row, COVER_RECEIVER_NAME, height=20)
    row = _line(row, COVER_RECEIVER_SIGN, height=20)
    row = _line(row, COVER_RECEIVER_STAMP, height=20)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_excel(claim: InsuranceClaim, template: str = 'all',
                   billing_group=None, layout: str = 'daily',
                   sort_by: str = 'patient_name', sort_dir: str = 'asc') -> HttpResponse:
    """
    Generate the claim's Excel workbook.

    billing_group: optional InsuranceClaimBillingGroup. When provided, only
    prescriptions assigned to that group are included — produces a separate
    invoice for that sub-category (sub-personcode).

    layout: 'daily' (default, day-grouped يوميات) or 'flat' (one continuous list
    sorted by `sort_by`/`sort_dir`, no day subtotals) — for special client
    requests like ordering alphabetically by patient name.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    dataset = build_invoice_dataset(claim, billing_group=billing_group)

    # Resolve the customizable print style once (profile → default → built-ins)
    st = resolve_style(claim, dataset)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    if layout == 'flat':
        def _yawmiyat_builder(wb, ds, st):
            return _build_sheet_flat(wb, ds, st, sort_by=sort_by, sort_dir=sort_dir)
    else:
        _yawmiyat_builder = _build_sheet_yawmiyat

    builders = {
        'daily_detail':  _yawmiyat_builder,
        'daily_summary': _build_sheet_cover_ready,
        'grand_total':   _build_sheet_grand_total,
        'cover':         _build_sheet_cover_letter,
    }

    if template in builders:
        builders[template](wb, dataset, st)
    else:
        for fn in builders.values():
            fn(wb, dataset, st)

    # Apply the watermark (if any) to every generated sheet
    if st.get('watermark'):
        for ws in wb.worksheets:
            _apply_watermark(ws, st)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    period   = claim.period_from.strftime('%Y%m') if claim.period_from else ''
    client   = claim.subclient.client.name_short or claim.subclient.client.name
    grp_tag  = f'_{billing_group.code}' if billing_group else ''
    filename = f'مطالبة_{client}_{period}_{claim.claim_number}{grp_tag}.xlsx'

    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# PIVOT EXPORT — reuses the same style helpers as the claim invoices
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pivot_excel(result: dict, title: str = 'تحليل البيانات') -> HttpResponse:
    """
    Render a pivot result (from pivot.build_pivot) as a styled Excel sheet.

    Handles both shapes:
      • Simple summary : dimension column + one measure column
      • Cross-tab      : dimension column + one column per col-value + row total
    A bold totals row is appended.  Reuses FONT_*/FILL_* style constants.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'تحليل'
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')

    # ── Multi-dimension shape (rows have `dims` list; from build_pivot_multi) ──
    if result.get('row_dims') is not None:
        rdims = result['row_dims']            # [{key,label}]
        col_defs = result.get('columns', [])  # [{key, labels:[...]}]
        has_cols = bool(col_defs)
        headers = [d['label'] for d in rdims]
        if has_cols:
            headers += [' / '.join(c['labels']) for c in col_defs] + ['الإجمالى']
        else:
            headers += [result.get('measure_label', 'القيمة')]
        ws.row_dimensions[1].height = 28
        for ci, h in enumerate(headers, start=1):
            _w(ws, 1, ci, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        for ci in range(1, len(rdims) + 1):
            ws.column_dimensions[get_column_letter(ci)].width = 24
        for ci in range(len(rdims) + 1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(ci)].width = 16
        r = 2
        n_rd = len(rdims)
        for row in result.get('rows', []):
            ws.row_dimensions[r].height = 16
            for j, dv in enumerate(row.get('dims', []), start=1):
                _w(ws, r, j, dv, align=ALIGN_RIGHT)
            if has_cols:
                vals = row.get('values', {})
                for j, c in enumerate(col_defs, start=n_rd + 1):
                    _w(ws, r, j, float(vals.get(c['key'], 0) or 0), align=_a('left', 'center'), fmt='#,##0.00')
                _w(ws, r, len(headers), float(row.get('_total', 0) or 0),
                   font=FONT_SUBTOTAL, fill=FILL_SUBTOTAL, align=_a('left', 'center'), fmt='#,##0.00')
            else:
                _w(ws, r, n_rd + 1, float(row.get('_total', 0) or 0), align=_a('left', 'center'), fmt='#,##0.00')
            r += 1
        ws.row_dimensions[r].height = 20
        _w(ws, r, 1, 'الإجمالى الكلي', font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)
        for j in range(2, n_rd + 1):
            _w(ws, r, j, None, font=FONT_GRAND, fill=FILL_GRAND)
        totals = result.get('totals', {})
        if has_cols:
            for j, c in enumerate(col_defs, start=n_rd + 1):
                _w(ws, r, j, float(totals.get(c['key'], 0) or 0),
                   font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')
            _w(ws, r, len(headers), float(result.get('grand_total', 0) or 0),
               font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')
        else:
            _w(ws, r, n_rd + 1, float(result.get('grand_total', 0) or 0),
               font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')
        ws.print_title_rows = '1:1'
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        safe_title = (title or 'تحليل').replace('/', '-').replace('\\', '-')
        resp = HttpResponse(buf.getvalue(),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="{safe_title}.xlsx"'
        return resp

    cross = bool(result.get('columns'))
    col_defs = result.get('columns', [])
    measure_label = result.get('measure_label', 'القيمة')

    # ── Header row ────────────────────────────────────────────────────────────
    headers = [result.get('row_label', 'البند')]
    if cross:
        headers += [c['label'] for c in col_defs]
        headers += ['الإجمالى']
    else:
        headers += [measure_label]

    ws.row_dimensions[1].height = 28
    for col_idx, h in enumerate(headers, start=1):
        _w(ws, 1, col_idx, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)

    # Column widths: dimension wide, value cols medium
    ws.column_dimensions[get_column_letter(1)].width = 30
    for col_idx in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 16

    # ── Data rows ─────────────────────────────────────────────────────────────
    r = 2
    for row in result.get('rows', []):
        ws.row_dimensions[r].height = 16
        _w(ws, r, 1, row.get('dimension', '—'), align=ALIGN_RIGHT)
        if cross:
            for j, c in enumerate(col_defs, start=2):
                _w(ws, r, j, float(row.get(c['key'], 0) or 0),
                   align=_a('left', 'center'), fmt='#,##0.00')
            _w(ws, r, len(headers), float(row.get('_total', 0) or 0),
               font=FONT_SUBTOTAL, fill=FILL_SUBTOTAL,
               align=_a('left', 'center'), fmt='#,##0.00')
        else:
            _w(ws, r, 2, float(row.get('_total', 0) or 0),
               align=_a('left', 'center'), fmt='#,##0.00')
        r += 1

    # ── Totals row ────────────────────────────────────────────────────────────
    ws.row_dimensions[r].height = 20
    _w(ws, r, 1, 'الإجمالى الكلي', font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)
    totals = result.get('totals', {})
    if cross:
        for j, c in enumerate(col_defs, start=2):
            _w(ws, r, j, float(totals.get(c['key'], 0) or 0),
               font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')
        _w(ws, r, len(headers), float(result.get('grand_total', 0) or 0),
           font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')
    else:
        _w(ws, r, 2, float(result.get('grand_total', 0) or 0),
           font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt='#,##0.00')

    # Repeat header row on every printed page
    ws.print_title_rows = '1:1'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_title = (title or 'تحليل').replace('/', '-').replace('\\', '-')
    filename = f'{safe_title}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# DISCREPANCY EXPORT — frozen snapshot vs current master (reuses pivot style)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_discrepancy_excel(report: dict, claim_number: str = '') -> HttpResponse:
    """
    Render the value-discrepancy report (from discrepancy.compute_claim_discrepancy)
    as a styled Excel sheet: a summary block + a per-line drift table.
    Reuses the FONT_*/FILL_*/_w/_margins helpers.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    s = report.get('summary', {})
    rows = report.get('lines', [])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'الفروقات'
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')

    # ── Summary block ─────────────────────────────────────────────────────────
    ws.row_dimensions[1].height = 22
    _w(ws, 1, 1, 'ملخص الفروقات', font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)
    summary_pairs = [
        ('عدد البنود', s.get('total_lines', 0)),
        ('بنود متغيّرة', s.get('changed_lines', 0)),
        ('تغيّر تصنيف', s.get('category_changes', 0)),
        ('تغيّر سعر', s.get('price_changes', 0)),
        ('إجمالى مجمّد', s.get('frozen_gross', 0)),
        ('إجمالى حالي', s.get('current_gross', 0)),
        ('صافى مجمّد', s.get('frozen_net', 0)),
        ('صافى حالي', s.get('current_net', 0)),
        ('فرق الصافى', s.get('net_delta', 0)),
    ]
    r = 2
    for label, val in summary_pairs:
        _w(ws, r, 1, label, font=_f(bold=True), align=ALIGN_RIGHT)
        _w(ws, r, 2, val, align=_a('left', 'center'),
           fmt='#,##0.00' if isinstance(val, float) else None)
        r += 1

    r += 1  # spacer

    # ── Line table header ─────────────────────────────────────────────────────
    headers = ['الفاتورة', 'الصنف', 'الكمية',
               'سعر مجمّد', 'سعر حالي', 'فرق السعر',
               'تصنيف مجمّد', 'تصنيف حالي',
               'صافى مجمّد', 'صافى حالي', 'فرق الصافى', 'السبب']
    widths  = [12, 30, 8, 12, 12, 12, 12, 12, 12, 12, 12, 14]
    for col_idx, (h, w) in enumerate(zip(headers, widths), start=1):
        _w(ws, r, col_idx, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    header_row = r
    r += 1

    reason_label = {
        'category_change': 'تغيّر التصنيف', 'price_change': 'تغيّر السعر',
        'both': 'تصنيف + سعر', 'rate_change': 'تغيّر النسبة',
        'item_not_found': 'صنف غير موجود',
    }
    money = '#,##0.00'
    for row in rows:
        ws.row_dimensions[r].height = 15
        _w(ws, r, 1,  f"#{row.get('docnumber','')}", align=ALIGN_CENTER)
        _w(ws, r, 2,  row.get('item_name', ''), align=ALIGN_RIGHT)
        _w(ws, r, 3,  float(row.get('quantity', 0) or 0), align=ALIGN_CENTER, fmt='#,##0')
        _w(ws, r, 4,  float(row.get('frozen_unit_price', 0) or 0),  align=_a('left','center'), fmt=money)
        _w(ws, r, 5,  float(row.get('current_unit_price', 0) or 0), align=_a('left','center'), fmt=money)
        _w(ws, r, 6,  float(row.get('price_delta', 0) or 0),        align=_a('left','center'), fmt=money)
        _w(ws, r, 7,  row.get('frozen_category_label', ''),  align=ALIGN_CENTER)
        _w(ws, r, 8,  row.get('current_category_label', ''), align=ALIGN_CENTER)
        _w(ws, r, 9,  float(row.get('frozen_net', 0) or 0),  align=_a('left','center'), fmt=money)
        _w(ws, r, 10, float(row.get('current_net', 0) or 0), align=_a('left','center'), fmt=money)
        _w(ws, r, 11, float(row.get('net_delta', 0) or 0),
           font=FONT_SUBTOTAL, fill=FILL_SUBTOTAL, align=_a('left','center'), fmt=money)
        _w(ws, r, 12, reason_label.get(row.get('reason'), row.get('reason', '')), align=ALIGN_CENTER)
        r += 1

    ws.print_title_rows = f'{header_row}:{header_row}'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'فروقات_{claim_number or "مطالبة"}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
