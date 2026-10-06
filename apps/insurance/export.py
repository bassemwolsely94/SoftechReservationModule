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
import logging
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

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
from apps.finance.recon_labels import branch_label as BL      # '170' → '170 · name'

logger = logging.getLogger('elrezeiky.insurance')


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

# A4 portrait usable body height (pts) after the print margins below.
# A4 = 842pt tall; top 2.9cm (82pt) + bottom 1.9cm (54pt) → ~706pt usable.
# We keep a small safety buffer so a day never spills by a stray row.
A4_USABLE = 695.0

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
    # Widths tuned so the whole table fills — but does not exceed — one A4-portrait
    # page width (~748px at 0.6cm side margins).  اسم المريض takes the slack; the
    # money columns hold up to "9,999,999.99".  fit-to-width in _margins is only a
    # safety clamp, so at these widths the print stays at ~100 % scale.
    cols = [
        ('م',                    'sequence',         5.5,  '0'),
        ('تاريخ الصرف',          'date',            11.5,  'YYYY-MM-DD'),
        ('اسم المريض',           'patient_name',    30.0,  None),
        ('المحلى قبل الخصم',    'local_before',    12.0,  '#,##0.00'),
        ('المستورد قبل الخصم',  'imported_before', 12.0,  '#,##0.00'),
    ]
    if has_tarsia:
        cols.append(('الترسية قبل الخصم', 'tarsia_before', 12.0, '#,##0.00'))
    cols += [
        ('الإجمالى قبل الخصم',  'gross_before',    13.0,  '#,##0.00'),
        ('صافى الفاتورة',        'net_after',       12.0,  '#,##0.00'),
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
        # A failure here would silently drop the ترسية column from a claim that
        # actually has tarsia — log it loudly instead of hiding it.
        logger.warning('[export] _claim_has_tarsia check failed; defaulting to no-tarsia layout',
                       exc_info=True)
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
    except (ValueError, KeyError, IndexError):
        logger.debug('[export] month label parse failed for %r', pf)
    # Call-center numbers from the pharmacy profile (reuse)
    call_center = ''
    try:
        from apps.config.models import PharmacyProfile
        call_center = (PharmacyProfile.get().call_center_numbers or '').replace('\n', ' - ')
    except Exception:
        logger.debug('[export] call-center numbers unavailable', exc_info=True)
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
        logger.debug('[export] watermark image could not be applied', exc_info=True)


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
    """Apply the finance team's A4 print margins + fit-to-width scaling.

    Margins (from the reviewed Page-Setup): narrow sides so the columns fill the
    sheet, a tall 3 cm top for the multi-line print header, and 1.7 cm bottom.
    All values are inches (openpyxl unit); cm equivalents noted.
    """
    ws.page_setup.paperSize   = 9          # A4
    ws.page_setup.orientation = orientation
    ws.page_margins.left   = 0.2362        # 0.6 cm
    ws.page_margins.right  = 0.2362        # 0.6 cm
    ws.page_margins.top    = 1.1417        # 2.9 cm — roomy header block
    ws.page_margins.bottom = 0.7480        # 1.9 cm
    ws.page_margins.header = 0.3150        # 0.8 cm
    ws.page_margins.footer = 0.3150        # 0.8 cm

    # Fit ALL columns onto ONE page width (never spill horizontally onto a 2nd
    # page), leaving the height unconstrained so days flow down as many pages as
    # needed.  Columns are sized to ~fit already, so the scale stays near 100 %
    # (font/row-height unchanged); this is only a safety clamp for the widest
    # (tarsia) layout.
    from openpyxl.worksheet.properties import PageSetupProperties
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth  = 1
    ws.page_setup.fitToHeight = 0


# Excel rejects a print header/footer whose whole odd(Header|Footer) string —
# ALL sections plus their &-format codes — exceeds 255 characters: it flags the
# file as corrupt on open ("we found a problem…") and strips the header/footer on
# repair.  We keep a safety margin below 255.
_HF_MAX = 250


def _dedup_client_sub(client: str, sub: str) -> str:
    """One label for client/subclient — avoids printing an identical name twice
    (a common data shape here that alone can blow the header past Excel's limit)."""
    client = (client or '').strip()
    sub    = (sub or '').strip()
    if not sub or sub == client or sub in client:
        return client
    if client and client in sub:
        return sub
    return f'{client} — {sub}' if client else sub


def _cap_hf_sections(sections: dict, font_code: str, limit: int = _HF_MAX) -> None:
    """Trim section TEXTS in place so the assembled header/footer string
    (font codes + &L/&C/&R markers + text) stays within Excel's limit.

    `sections` maps 'left'/'center'/'right' → raw text (no font code).  When the
    budget is exceeded the longest section is shortened with an ellipsis so the
    header still renders instead of being dropped wholesale by Excel."""
    def _assembled_len():
        # openpyxl serialises each newline as the 7-char escape '_x000a_', so a
        # line break costs 7 (not 1) in the stored oddHeader string.  Count it
        # that way to stay under Excel's limit however Excel measures it.
        total = 0
        for txt in sections.values():
            if txt:
                total += 2 + len(font_code) + len(txt) + 6 * txt.count('\n')
        return total
    guard = 0
    while _assembled_len() > limit and guard < 100:
        over = _assembled_len() - limit
        key  = max(sections, key=lambda k: len(sections[k] or ''))
        txt  = sections[key] or ''
        if len(txt) <= 1:
            break
        # Cut decisively: drop `over` chars (+1 for the ellipsis) in one step so
        # very long text converges immediately instead of nibbling one char/loop.
        cut  = min(len(txt) - 1, over + 1)
        sections[key] = txt[:len(txt) - cut].rstrip() + '…'
        guard += 1


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
        # Custom profiles already embed their own font codes, so cap the whole
        # section text (font code counted as 0 extra) to stay under Excel's limit.
        hsec = {'left': hf['left'], 'center': hf['center'], 'right': hf['right']}
        fsec = {'left': hf['fleft'], 'center': hf['fcenter'], 'right': hf['fright']}
        _cap_hf_sections(hsec, '', _HF_MAX)
        _cap_hf_sections(fsec, '', _HF_MAX)
        ws.oddHeader.left.text   = hsec['left']
        ws.oddHeader.center.text = hsec['center']
        ws.oddHeader.right.text  = hsec['right']
        ws.oddFooter.left.text   = fsec['left']
        ws.oddFooter.center.text = fsec['center']
        ws.oddFooter.right.text  = fsec['right']
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

    # Build raw section texts, then cap the TOTAL below Excel's 255-char limit
    # (the client name can be long — and is sometimes duplicated — which alone
    # pushes the header over the edge and makes Excel strip it entirely).
    party = _dedup_client_sub(client, sub)
    sections = {
        'right':  f'شركة الرزيقي لإدارة الصيدليات\n{party}',
        'center': f'{sheet_title}\n{p_from}  –  {p_to}',
        'left':   f'رقم المطالبة:\n{claim_no}',
    }
    _cap_hf_sections(sections, cb, _HF_MAX)

    ws.oddHeader.right.text  = f'{cb}{sections["right"]}'
    ws.oddHeader.center.text = f'{cb}{sections["center"]}'
    ws.oddHeader.left.text   = f'{cb}{sections["left"]}'

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
    """Tracks the used height of the current physical page to paginate day blocks
    for BOTH paper efficiency and least page-spread per day:

      • Days flow continuously — a day is written right after the previous one and
        Excel breaks pages naturally, so every page fills up (no wasted bottom
        band).  A day may cross a page boundary.
      • BUT a manual break is inserted before a day ONLY when starting it fresh on
        the next page makes it span FEWER pages than letting it flow from here.
        So a day that fits on one page is never split across two; a day bigger
        than a page flows from wherever we are (using the leftover space) and
        still spans the minimum number of pages.
      • The n_blanks reviser-comment rows after each day are counted in the
        running position but NOT in the fit decision, so we never burn a break
        just to keep blank rows together (they harmlessly top the next page).
    """
    def __init__(self, usable=A4_USABLE, n_blanks=N_BLANKS):
        self._usable  = usable
        self._current = 0.0
        self._n_blanks = n_blanks

    def _day_rows(self, n_rx: int) -> list:
        # header + data rows + subtotal (the day's own content — NOT the trailing
        # blank spacer rows, which may harmlessly top the next page).
        return [H_HEADER] + [H_DATA] * n_rx + [H_HEADER]

    def _sim_pages(self, start: float, rows: list) -> int:
        """Pages a sequence of rows spans starting at page offset `start`,
        modelling Excel's ROW-boundary breaks (a row that would cross the page
        edge moves whole to the next page) — so the estimate matches print exactly."""
        cur, pages = start, 1
        for h in rows:
            if cur + h > self._usable + 1e-6:
                pages += 1
                cur = 0.0
            cur += h
        return pages

    def should_break(self, n_rx: int) -> bool:
        if self._current <= 0.5:
            return False                       # already at the top of a page
        rows = self._day_rows(n_rx)
        # Break only if a fresh page makes the day span FEWER pages.
        return self._sim_pages(0.0, rows) < self._sim_pages(self._current, rows)

    def place_day(self, n_rx: int):
        """Advance the tracked position by a whole day block (content + trailing
        blank spacers), row by row, exactly as Excel will paginate it."""
        rows = self._day_rows(n_rx) + [H_BLANK] * self._n_blanks
        for h in rows:
            if self._current + h > self._usable + 1e-6:
                self._current = 0.0
            self._current += h

    def add(self, h: float):
        if self._current + h > self._usable + 1e-6:
            self._current = 0.0
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
    # Each row prints its OWN dispensing date; the block label (e.g. "ملحق سابق")
    # is only used on the subtotal, never in a data row's تاريخ الصرف cell.
    date_val = _to_date(rx.get('date') or day_date)
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
    serial  = 0   # continuous 1..N serial for the م column (independent of day grouping)
    tracker = _PageTracker(n_blanks=n_blanks)

    # Days flow continuously so pages fill up (paper-efficient).  A manual break is
    # inserted before a day ONLY when starting it fresh spans fewer pages than
    # letting it flow from here — best effort to keep each day on the least number
    # of pages without wasting paper.  Each day is trailed by n_blanks rows giving
    # revisers room to note deductions between one day and the next.
    def _write_day(rxs, dt, day_k, subtotal_label):
        nonlocal row, serial
        n_rx = len(rxs)
        if tracker.should_break(n_rx):
            ws.row_breaks.append(Break(id=row - 1))
            tracker.new_page()
        row = _write_day_header(ws, row, st, cols)
        for rx in rxs:
            serial += 1
            row = _write_data_row(ws, row, rx, day_k, st, cols, seq_val=serial)
        row = _write_subtotal(ws, row, dt, subtotal_label, n_rx if dt.get('rx_count') is None
                              else dt.get('rx_count', n_rx), st, cols)
        row = _write_blanks(ws, row, ncols, n_blanks)
        tracker.place_day(n_rx)

    # 1. Global header row
    row = _write_global_header(ws, row, st, cols)
    tracker.add(H_HEADER)

    before_supp_days = [d for d in dataset['days'] if d.get('is_supplement')
                        and d.get('supplement_type') in ('before_claim', None)
                        and d.get('prescriptions')]
    main_days        = [d for d in dataset['days']
                        if not (d.get('is_supplement')
                                and d.get('supplement_type') in ('before_claim', None))]

    # 2. Before-supplement blocks (ملحق سابق)
    for sup_day in before_supp_days:
        _write_day(sup_day['prescriptions'], sup_day['day_totals'], sup_day['date'], 'ملحق')

    # 3. Main day blocks
    for day in main_days:
        rxs = day.get('prescriptions', [])
        if not rxs:
            continue
        _write_day(rxs, day['day_totals'], day['date'], day['date'])

    # 4. After-supplement blocks (ملحق لاحق)
    after_supp_days = [d for d in dataset['days'] if d.get('is_supplement')
                       and d.get('supplement_type') == 'after_claim'
                       and d.get('prescriptions')]
    for sup_day in after_supp_days:
        _write_day(sup_day['prescriptions'], sup_day['day_totals'], sup_day['date'], 'ملحق')


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


def _build_sheet_flat_paged(wb, dataset: dict, st: dict = None,
                            sort_by: str = 'patient_name', sort_dir: str = 'asc'):
    """
    Flat, custom-sorted يوميات like _build_sheet_flat, but with a SUBTOTAL row at the
    bottom of every printed page (إجمالى الصفحة) and one grand total at the very end.
    Uses a fixed rows-per-page with manual page breaks so each subtotal sits exactly
    at the page foot and the column header repeats atop each page — deterministic and
    print-accurate (fit-to-width, natural row height, same as the day-grouped sheet).
    """
    st = st or resolve_style(None, dataset)
    ws = wb.create_sheet('يوميات (إجماليات الصفحات)')
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'portrait')
    _header_footer(ws, dataset['claim'], 'يوميات المطالبة', repeat_header_row=False, st=st)

    cols = _yawmiyat_cols(_claim_has_tarsia(dataset))
    for col, (_, _, width, _) in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    rows = []
    for d in dataset.get('days', []):
        day_date = d.get('date')
        for rx in d.get('prescriptions', []):
            rx = dict(rx); rx['_date'] = day_date
            rows.append(rx)
    keyfn = _FLAT_SORT_KEYS.get(sort_by, _FLAT_SORT_KEYS['patient_name'])
    try:
        rows.sort(key=keyfn, reverse=(sort_dir == 'desc'))
    except TypeError:
        rows.sort(key=lambda r: str(keyfn(r)), reverse=(sort_dir == 'desc'))

    # header (31.5) + N data (15.75) + page-subtotal (31.5) must fit A4_USABLE (695)
    rows_per_page = max(1, int((A4_USABLE - H_HEADER - H_HEADER) / H_DATA))
    _SUM_KEYS = ('net_after', 'gross_before', 'tarsia_before', 'imported_before', 'local_before')

    def _write_subtotal(r, sums, n, label):
        _set_row_height(ws, r, H_HEADER)
        vals = {k: sums[k] for k in _SUM_KEYS}
        vals.update({'patient_name': f'{label}: {n} روشتة', 'date': label, 'sequence': None})
        for col, (_, key, _, fmt) in enumerate(cols, start=1):
            use_fmt = fmt if key in _SUBTOTAL_NUMERIC_KEYS else None
            _w(ws, r, col, vals.get(key), font=st['font_subtotal'],
               fill=st['fill_subtotal'], fmt=use_fmt, border=st['border'])
        return r + 1

    row = 1
    row = _write_global_header(ws, row, st, cols)
    serial = 0
    n_on_page = 0
    page_sums = {k: 0.0 for k in _SUM_KEYS}
    for rx in rows:
        if n_on_page == rows_per_page:                       # page is full → foot it
            row = _write_subtotal(row, page_sums, n_on_page, 'إجمالى الصفحة')
            ws.row_breaks.append(Break(id=row - 1))          # break after the subtotal
            page_sums = {k: 0.0 for k in _SUM_KEYS}; n_on_page = 0
            row = _write_global_header(ws, row, st, cols)     # repeat header on new page
        serial += 1
        row = _write_data_row(ws, row, rx, rx.get('_date'), st, cols, seq_val=serial)
        for k in _SUM_KEYS:
            page_sums[k] += _to_float(rx.get(k))
        n_on_page += 1
    if n_on_page > 0:
        row = _write_subtotal(row, page_sums, n_on_page, 'إجمالى الصفحة')

    # Grand total (authoritative claim_totals) at the very end
    gt = dataset['claim_totals']
    grand = {k: _to_float(gt.get(k)) for k in _SUM_KEYS}
    row = _write_subtotal(row, grand, serial, 'الإجمالى الكلى')


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
    elif layout == 'flat_paged':
        def _yawmiyat_builder(wb, ds, st):
            return _build_sheet_flat_paged(wb, ds, st, sort_by=sort_by, sort_dir=sort_dir)
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


def generate_reprice_runs_excel(runs, claim_number: str = '') -> HttpResponse:
    """
    Export the SOFTECH re-price runs log (سجل تعديلات سوفتك) as a styled Excel sheet.
    `runs` is an iterable of SoftechRepriceRun.  Includes applied, reverted AND FAILED
    runs so the failed modifications are auditable/exportable; failed rows are tinted.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'تعديلات سوفتك'
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')

    ws.row_dimensions[1].height = 22
    _w(ws, 1, 1, 'سجل تعديلات أسعار سوفتك', font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)

    headers = ['#', 'التاريخ', 'الإيصال', 'الفرع', 'الأسعار الجديدة',
               'الحالة', 'فرق الصافى', 'العُقد', 'أُعيد الرصيد', 'المستخدم', 'الخطأ']
    widths  = [7, 18, 12, 8, 26, 12, 12, 14, 10, 16, 40]
    r = 3
    for col_idx, (h, w) in enumerate(zip(headers, widths), start=1):
        _w(ws, r, col_idx, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    header_row = r
    r += 1

    status_label = {'preview': 'معاينة', 'applied': 'مُطبَّق',
                    'reverted': 'مُتراجَع', 'failed': 'فشل'}
    fail_fill = PatternFill('solid', fgColor='FCE4E4')
    money = '#,##0.00'
    for run in runs:
        prices = ' · '.join(f'{k}={v}' for k, v in (run.new_prices or {}).items())
        is_fail = run.status == 'failed'
        fill = fail_fill if is_fail else None
        try:
            who = getattr(run.applied_by, 'full_name', None) or getattr(run.applied_by, 'username', '') or ''
        except Exception:
            who = ''
        _w(ws, r, 1,  run.pk, align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 2,  timezone.localtime(run.applied_at).strftime('%Y-%m-%d %H:%M') if run.applied_at else '',
           align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 3,  f'#{run.docnumber}', align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 4,  BL(run.branchcode), align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 5,  prices, align=ALIGN_RIGHT, fill=fill)
        _w(ws, r, 6,  status_label.get(run.status, run.status), align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 7,  float(run.net_delta or 0), align=_a('left', 'center'), fmt=money, fill=fill)
        _w(ws, r, 8,  ' / '.join(run.nodes or []), align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 9,  'نعم' if run.rebalanced else '—', align=ALIGN_CENTER, fill=fill)
        _w(ws, r, 10, who, align=ALIGN_RIGHT, fill=fill)
        _w(ws, r, 11, (run.error or '')[:300], align=ALIGN_RIGHT, fill=fill)
        r += 1

    ws.print_title_rows = f'{header_row}:{header_row}'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'تعديلات_سوفتك_{claim_number or "مطالبة"}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def generate_statistical_excel(claim: InsuranceClaim) -> HttpResponse:
    """
    Government monthly-statistics listing (الاحصائية الشهرية للصيدلية) for a motalba.
    Columns: م · اسم المريض رباعى · التاريخ · اجمالى الروشتة · اسم الصيدلية · ملاحظات.
    ملاحظات carries the motalba head-title (جهة التأمين) + sub-category (الفئة).
    One row per non-excluded prescription, ordered by date; A4-paginated with the
    column header repeated atop each page.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    from .models import InsuranceClaimExclusion
    try:
        from apps.branches.models import Branch
        branch_names = {b.softech_branch_id: (b.name_ar or b.name)
                        for b in Branch.objects.all()}
    except Exception:
        branch_names = {}

    # head-title (جهة التأمين) + sub-category (الفئة) → remarks
    try:
        head_title = claim.subclient.client.name
        sub_cat    = claim.subclient.name
    except Exception:
        head_title = sub_cat = ''
    remark = ' — '.join([x for x in (head_title, sub_cat) if x])

    excluded_ids = set(
        InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
        .values_list('prescription_id', flat=True))
    rows = [rx for rx in claim.prescriptions.all().order_by('softech_docdate', 'sequence')
            if rx.id not in excluded_ids]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'الاحصائية الشهرية'
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'portrait')

    # Title band (motalba identity)
    period = ''
    try:
        period = f'{claim.period_from} — {claim.period_to}'
    except Exception:
        pass
    _w(ws, 1, 1, f'الاحصائية الشهرية — {remark}  ({period})',
       font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)

    headers = ['م', 'اسم المريض رباعى', 'التاريخ', 'اجمالى الروشتة', 'اسم الصيدلية', 'ملاحظات']
    widths  = [5, 34, 13, 14, 22, 30]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    def _write_header(r):
        _set_row_height(ws, r, H_HEADER)
        for col, h in enumerate(headers, start=1):
            _w(ws, r, col, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        return r + 1

    # title(row1) + header + N data must fit A4
    rows_per_page = max(1, int((A4_USABLE - H_HEADER - H_HEADER) / H_DATA))
    money = '#,##0.00'
    r = 2
    r = _write_header(r)
    header_row = r - 1
    serial = 0
    n_on_page = 0
    for rx in rows:
        if n_on_page == rows_per_page:
            ws.row_breaks.append(Break(id=r - 1))
            r = _write_header(r)
            n_on_page = 0
        serial += 1
        _set_row_height(ws, r, H_DATA)
        _w(ws, r, 1, serial, align=ALIGN_CENTER)
        _w(ws, r, 2, rx.patient_name or '', align=ALIGN_RIGHT)
        _w(ws, r, 3, rx.softech_docdate.strftime('%Y-%m-%d') if rx.softech_docdate else '',
           align=ALIGN_CENTER)
        _w(ws, r, 4, float(rx.gross_before or 0), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 5, branch_names.get(str(rx.softech_branchcode), rx.softech_branchcode or ''),
           align=ALIGN_RIGHT)
        _w(ws, r, 6, remark, align=ALIGN_RIGHT)
        r += 1
        n_on_page += 1

    ws.print_title_rows = f'{header_row}:{header_row}'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f'احصائية_{claim.claim_number}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def generate_reprice_reconciliation_excel(runs, save_path=None):
    """
    Accounting sign-off sheet for the SOFTECH price rewrites: one row per re-price
    run with old→new السعر / الإجمالى / الصافى / الضريبة, run id, date, receipt, branch,
    claim, net Δ, status.  Reconstructed from the recorded SoftechRepriceEdit rows
    (HQ node).  `runs` = a SoftechRepriceRun queryset (bonusqty-backfill runs excluded
    by the caller).  Returns an HttpResponse, or writes to `save_path` and returns it.
    """
    if not HAS_OPENPYXL:
        return HttpResponse('openpyxl not installed', status=500)

    def _num(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'تسوية تعديلات الأسعار'
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')

    ws.row_dimensions[1].height = 24
    _w(ws, 1, 1, 'كشف تسوية تعديلات أسعار سوفتك — لاعتماد الحسابات',
       font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)
    _w(ws, 2, 1, f'تاريخ الإصدار: {timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")}',
       font=_f(size=9, color='666666'), align=ALIGN_RIGHT)

    headers = ['م', 'رقم العملية', 'التاريخ', 'الإيصال', 'الفرع', 'المطالبة', 'الصنف',
               'السعر (قبل)', 'السعر (بعد)',
               'الإجمالى (قبل)', 'الإجمالى (بعد)',
               'الصافى (قبل)', 'الصافى (بعد)',
               'الضريبة (قبل)', 'الضريبة (بعد)',
               'فرق الصافى', 'الحالة', 'بواسطة']
    widths  = [5, 9, 12, 10, 7, 13, 26, 11, 11, 12, 12, 12, 12, 11, 11, 11, 9, 16]
    r = 4
    for col, (h, w) in enumerate(zip(headers, widths), start=1):
        _w(ws, r, col, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        ws.column_dimensions[get_column_letter(col)].width = w
    header_row = r
    r += 1

    money = '#,##0.00'
    status_lbl = {'applied': 'مُطبَّق', 'reverted': 'مُتراجَع', 'failed': 'فشل', 'preview': 'معاينة'}
    serial = 0
    tot_net_before = tot_net_after = tot_delta = 0.0
    for run in runs.prefetch_related('edits'):
        edits = [e for e in run.edits.all() if e.node == 'HQ']
        # price(s): itemsaleprice on stktrans, by itemcode
        price_pairs = {}
        gross_b = gross_a = net_b = net_a = vat_b = vat_a = None
        for e in edits:
            if e.table == 'stktrans' and e.field == 'itemsaleprice':
                code = str(e.row_key.get('itemcode', '')).strip()
                price_pairs.setdefault(code, (e.before, e.after))
            elif e.table == 'stktransm' and e.field == 'docvalue1':
                gross_b, gross_a = e.before, e.after
            elif e.table == 'stktransm' and e.field == 'docvalue':
                net_b, net_a = e.before, e.after
            elif e.table == 'stktransm' and e.field == 'docvalue3':
                vat_b, vat_a = e.before, e.after
        items = '، '.join(price_pairs.keys()) or ('؛'.join(run.new_prices.keys()) if run.new_prices else '')
        pb = '، '.join(str(_num(v[0])) for v in price_pairs.values()) if price_pairs else ''
        pa = '، '.join(str(_num(v[1])) for v in price_pairs.values()) if price_pairs else ''

        serial += 1
        ws.row_dimensions[r].height = 15
        _w(ws, r, 1, serial, align=ALIGN_CENTER)
        _w(ws, r, 2, run.pk, align=ALIGN_CENTER)
        _w(ws, r, 3, timezone.localtime(run.applied_at).strftime('%Y-%m-%d %H:%M') if run.applied_at else '',
           align=ALIGN_CENTER)
        _w(ws, r, 4, f'#{run.docnumber}', align=ALIGN_CENTER)
        _w(ws, r, 5, BL(run.branchcode), align=ALIGN_CENTER)
        _w(ws, r, 6, run.claim.claim_number if run.claim else '', align=ALIGN_CENTER)
        _w(ws, r, 7, items, align=ALIGN_RIGHT)
        _w(ws, r, 8, _num(pb) if price_pairs and len(price_pairs) == 1 else pb, align=_a('left', 'center'), fmt=money if len(price_pairs) == 1 else None)
        _w(ws, r, 9, _num(pa) if price_pairs and len(price_pairs) == 1 else pa, align=_a('left', 'center'), fmt=money if len(price_pairs) == 1 else None)
        _w(ws, r, 10, _num(gross_b), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 11, _num(gross_a), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 12, _num(net_b), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 13, _num(net_a), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 14, _num(vat_b), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 15, _num(vat_a), align=_a('left', 'center'), fmt=money)
        _w(ws, r, 16, float(run.net_delta or 0), font=FONT_SUBTOTAL, fill=FILL_SUBTOTAL,
           align=_a('left', 'center'), fmt=money)
        _w(ws, r, 17, status_lbl.get(run.status, run.status), align=ALIGN_CENTER)
        who = ''
        try:
            who = getattr(run.applied_by, 'full_name', None) or getattr(run.applied_by, 'username', '') or ''
        except Exception:
            who = ''
        _w(ws, r, 18, who, align=ALIGN_RIGHT)
        if _num(net_b) is not None:
            tot_net_before += _num(net_b)
        if _num(net_a) is not None:
            tot_net_after += _num(net_a)
        tot_delta += float(run.net_delta or 0)
        r += 1

    # totals row
    _w(ws, r, 7, 'الإجمالى', font=FONT_GRAND, fill=FILL_GRAND, align=ALIGN_RIGHT)
    _w(ws, r, 12, tot_net_before, font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt=money)
    _w(ws, r, 13, tot_net_after, font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt=money)
    _w(ws, r, 16, tot_delta, font=FONT_GRAND, fill=FILL_GRAND, align=_a('left', 'center'), fmt=money)
    r += 3

    # sign-off block
    _w(ws, r, 1, 'أعدّه: ______________', align=ALIGN_RIGHT); _w(ws, r, 6, 'راجعه: ______________', align=ALIGN_RIGHT)
    _w(ws, r, 12, 'اعتمده (الحسابات): ______________', align=ALIGN_RIGHT)

    ws.print_title_rows = f'{header_row}:{header_row}'

    if save_path:
        wb.save(save_path)
        return save_path
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="reprice_reconciliation.xlsx"'
    return response
