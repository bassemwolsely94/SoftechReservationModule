"""
KPI target-sheet Excel export  (doc 16, Phase 7)
================================================
Reproduces the owner's legacy monthly "تارجت الشهر" workbook FROM the new system:
per-branch KPI rows (cash / delivery / عميل دائم, credit, profit, customers,
cosmetics) with achieved + target + % + the weighted-scoring block, chain totals,
the call-center section, and the management-summary block — all as LIVE Excel
formulas identical to the legacy sheet, so the output behaves penny-for-penny like
the owner's own workbook.

Inputs injected per branch:
  • ACHIEVED  E/F/G (cash/delivery/عميل دائم), K (credit), Q (profit),
              T (customers), Y (cosmetics)  ← KpiActualRollup (net of returns)
  • TARGETS   I (cash+del), L (credit), R (profit), U (customers), Z (cosmetics)
              ← ForecastEngine (Model A / B / avg) over base=M-12, LM=M-1, PM=M-2
Everything else is a formula referencing those cells.

A sheet is produced per requested model. Optional reconciliation sheet(s) read the
owner's own legacy workbook(s) and diff the achieved values against our rollups.
Read-only: never writes to SOFTECH. Deterministic (no LLM).
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .engine import ForecastEngine, _shift_month, round_up_step, kpi_round_steps
from .models import KpiActualRollup as K


def _whole(x):
    """Round an exact/actual value to the nearest whole number (int)."""
    return int(round_up_step(x, 1))

# ── styling ──────────────────────────────────────────────────────────────────
_THIN = Side(style='thin', color='B0B0B0')
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
HDR_FILL = PatternFill('solid', fgColor='022871')          # brand navy
SUB_FILL = PatternFill('solid', fgColor='DCE6F1')
TGT_FILL = PatternFill('solid', fgColor='FFF2CC')           # target rows (soft gold)
TOTAL_FILL = PatternFill('solid', fgColor='E2EFDA')
CC_FILL = PatternFill('solid', fgColor='FCE4D6')
HDR_FONT = Font(bold=True, color='FFFFFF', size=10)
BOLD = Font(bold=True, size=10)
CTR = Alignment(horizontal='center', vertical='center', wrap_text=True)
RIGHT = Alignment(horizontal='right', vertical='center')
MONEY = '#,##0'
PCT = '0.0%'

# Owner's legacy branch display order (seniority); others fall to code order.
LEGACY_BRANCH_ORDER = ['160', '170', '140', '150', '130']

# Branch block geometry (identical to the legacy sheet).
TARGET_ROWS = [8, 10, 12, 14, 16]     # المطلوب rows (one per branch)
ACH_ROWS = [9, 11, 13, 15, 17]        # المحقق rows
ROW_TOTAL_TGT = 18
ROW_TOTAL_ACH = 19
# Weight cells (branch score): Cash .5 / Credit .1 / Profit .1 / PIC .05 / Cosm .1 / chain-cash .15
WEIGHTS = {'AC': 0.5, 'AD': 0.1, 'AE': 0.1, 'AF': 0.05, 'AG': 0.1, 'AH': 0.15}


# ── forecast targets (A / B / avg) over the scope ────────────────────────────
def _roll(branch_id, year, month, metric):
    r = K.objects.filter(branch_id=branch_id, year=year, month=month, metric=metric).first()
    return Decimal(r.value) if r else Decimal('0')


def forecast_targets(year, month, *, incentive_threshold=Decimal('0.90'),
                     benchmark_growth=Decimal('0.30'), inflation=Decimal('0'),
                     promotion_lift=Decimal('0'), factors=None):
    """
    Return {'branches': [{code,name,id, <metric>:{a,b,avg}}...],
            'chain': {<metric>:{a,b,avg}}} full-month targets per model.
    Uses the same math as ForecastEngine.compute_models (deterministic).
    """
    from .kpi import analytics_branches
    fac = factors or ForecastEngine.DEFAULT_FACTORS
    metrics = ForecastEngine.METRICS
    by, bm = _shift_month(year, month, -12)
    ly, lm = _shift_month(year, month, -1)
    py, pm = _shift_month(year, month, -2)
    thr = incentive_threshold or Decimal('0.90')

    def models_for(branch_id, metric):
        g, wl, wp, wy = fac[metric]
        base = _roll(branch_id, by, bm, metric)
        lmv = _roll(branch_id, ly, lm, metric)
        pmv = _roll(branch_id, py, pm, metric)
        ma, mb = ForecastEngine.compute_models(
            base, lmv, pmv, growth=g, w_lm=wl, w_pm=wp, w_yoy=wy,
            seasonality=Decimal('1'), bench=benchmark_growth,
            infl=inflation, promo=promotion_lift)
        avg = (ma + mb) / 2
        return {'a': ma / thr, 'b': mb / thr, 'avg': avg / thr}

    branches, chain = [], {m: {'a': Decimal('0'), 'b': Decimal('0'), 'avg': Decimal('0')} for m in metrics}
    for b in analytics_branches().order_by('code', 'softech_branch_id'):
        row = {'code': b.code or b.softech_branch_id, 'name': getattr(b, 'name_ar', '') or b.name, 'id': b.id}
        for m in metrics:
            mm = models_for(b.id, m)
            row[m] = mm
            for k in ('a', 'b', 'avg'):
                chain[m][k] += mm[k]
        branches.append(row)
    # order to match the owner's legacy sheet for easy side-by-side comparison
    order = {c: i for i, c in enumerate(LEGACY_BRANCH_ORDER)}
    branches.sort(key=lambda r: (order.get(str(r['code']), 99), str(r['code'])))
    return {'branches': branches, 'chain': chain}


def cc_targets(year, month, *, incentive_threshold=Decimal('0.90'),
               benchmark_growth=Decimal('0.30'), factors=None):
    """Call-center targets (sales/profit/beauty/orders) per model from the CC rollup history."""
    from apps.branches.models import Branch
    cc = Branch.objects.filter(softech_branch_id='CC').first()
    if not cc:
        return None
    fac = factors or ForecastEngine.DEFAULT_FACTORS
    thr = incentive_threshold or Decimal('0.90')
    by, bm = _shift_month(year, month, -12)
    ly, lm = _shift_month(year, month, -1)
    py, pm = _shift_month(year, month, -2)
    # CC metric → factor key to borrow (sales≈cash_delivery, orders≈customer_count)
    cc_map = {'sales': (K.M_CASH_DELIVERY, 'cash_delivery'),
              'profit': (K.M_GROSS_PROFIT, 'gross_profit'),
              'beauty': (K.M_BEAUTY, 'beauty'),
              'orders': (K.M_CUSTOMERS, 'customer_count')}
    out = {}
    for name, (metric, fkey) in cc_map.items():
        g, wl, wp, wy = fac[fkey]
        base = _roll(cc.id, by, bm, metric)
        lmv = _roll(cc.id, ly, lm, metric)
        pmv = _roll(cc.id, py, pm, metric)
        ma, mb = ForecastEngine.compute_models(
            base, lmv, pmv, growth=g, w_lm=wl, w_pm=wp, w_yoy=wy,
            seasonality=Decimal('1'), bench=benchmark_growth, infl=Decimal('0'), promo=Decimal('0'))
        out[name] = {'a': ma / thr, 'b': mb / thr, 'avg': (ma + mb) / 2 / thr}
    out['_cc_id'] = cc.id
    return out


def _achieved(branch_id, year, month):
    """Per-branch achieved dict from the rollup (net of returns)."""
    rows = {r['metric']: Decimal(r['value']) for r in K.objects.filter(
        branch_id=branch_id, year=year, month=month).values('metric', 'value')}
    g = lambda m: float(rows.get(m, Decimal('0')))
    return {'cash': g(K.M_CASH), 'delivery': g(K.M_DELIVERY), 'regular': g(K.M_REGULAR),
            'credit': g(K.M_CREDIT), 'profit': g(K.M_GROSS_PROFIT),
            'customers': g(K.M_CUSTOMERS), 'beauty': g(K.M_BEAUTY)}


# ── month label (Arabic) ─────────────────────────────────────────────────────
_AR_MONTHS = ['', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
              'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']


# ── one faithful replica sheet for a model ───────────────────────────────────
def _write_model_sheet(ws, year, month, data, cc, achieved_by_branch, model, days_elapsed, steps):
    days = monthrange(year, month)[1]
    mkey = model  # 'a' | 'b' | 'avg'

    def put(coord, value, *, fmt=None, font=None, fill=None, align=None, border=True):
        c = ws[coord]
        c.value = value
        if fmt:
            c.number_format = fmt
        if font:
            c.font = font
        if fill:
            c.fill = fill
        if align:
            c.alignment = align
        if border:
            c.border = BORDER
        return c

    # row 1 — day knobs
    put('D1', 'عدد ايام الشهر كله', font=BOLD, align=RIGHT, border=False)
    put('E1', days, font=BOLD, align=CTR)
    put('G1', 'تاريخ اليوم فى الشهر المحسوب عليه', font=BOLD, align=RIGHT, border=False)
    put('H1', days_elapsed, font=BOLD, align=CTR)

    model_lbl = {'a': 'Model A — نمو الهدف', 'b': 'Model B — مزيج مرجّح', 'avg': 'المتوسط (A+B)/2'}[mkey]
    put('C5', f'تارجت مبيعات الفروع صيدليات الرزيقى عن شهر {_AR_MONTHS[month]} {year}  —  [{model_lbl}]',
        font=BOLD, align=RIGHT, border=False)
    put('AC5', 'التحقيقات بالوزن النسبى', font=BOLD, align=CTR, fill=SUB_FILL)
    put('C6', f'01-{month}-{year}/{days}-{month}-{year}', align=RIGHT, border=False)

    # row 6 weighted-score headers
    for coord, txt in [('AB6', 'تصنيف النسب'), ('AC6', 'Cash'), ('AD6', 'Credit'),
                       ('AE6', 'Profit Factor'), ('AF6', 'PIC'), ('AG6', 'Cosm+O'),
                       ('AH6', 'نقدى الفروع'), ('AI6', 'Total'), ('AK6', 'عدد الايام')]:
        put(coord, txt, font=HDR_FONT, fill=HDR_FILL, align=CTR)

    # row 7 header labels
    h7 = {'A7': 'الاجمالى الشهر', 'C7': 'الكود', 'D7': 'حجم مبيعات', 'E7': 'cash', 'F7': 'delivery',
          'G7': 'عميل دائم', 'H7': 'اجمالى cash+delivery خلال الفترة', 'I7': 'المطلوب خلال المدة cash+delivery',
          'J7': 'الاجمالى cash+delivery', 'K7': 'credit', 'L7': 'credit', 'M7': 'الاجمالى credit',
          'N7': 'التارجت المحقق لكل فرع خلال الفترة', 'O7': 'التارجت لكل فرع خلال الفترة', 'P7': 'الاجمالى التارجت',
          'Q7': 'معامل الربحية', 'R7': 'معامل الربحية', 'S7': 'الاجمالى معامل الربحية', 'T7': 'المحقق العملاء',
          'U7': 'العملاء', 'V7': 'اجمالى العملاء', 'W7': 'cosmetics', 'X7': 'others', 'Y7': 'اجمالى cos+other',
          'Z7': 'المطلوب Cosmetics+OTHERS', 'AA7': 'الاجمالى cosm+other', 'AB7': 'نسبة الوزن النسبى'}
    for coord, txt in h7.items():
        put(coord, txt, font=HDR_FONT, fill=HDR_FILL, align=CTR)
    for coord, w in WEIGHTS.items():
        put(f'{coord}7', w, font=HDR_FONT, fill=HDR_FILL, align=CTR, fmt='0.00')
    put('AI7', '=SUM(AC7:AH7)', font=HDR_FONT, fill=HDR_FILL, align=CTR, fmt='0.00')
    put('AK7', '=E1', font=BOLD, align=CTR)

    # ── branch blocks ────────────────────────────────────────────────────────
    for i, b in enumerate(data['branches']):
        rt, ra = TARGET_ROWS[i], ACH_ROWS[i]
        ach = achieved_by_branch[b['id']]
        # TARGETS rounded UP to the memorable per-KPI step (forecast stays exact in the model)
        tgt = {m: int(round_up_step(b[m][mkey], steps.get(m, 1))) for m in ForecastEngine.METRICS}
        # target row
        put(f'A{rt}', 'cash', align=CTR, fill=TGT_FILL)
        put(f'C{rt}', b['code'], align=CTR, font=BOLD, fill=TGT_FILL)
        put(f'D{rt}', b['name'], align=RIGHT, font=BOLD, fill=TGT_FILL)
        put(f'I{rt}', tgt['cash_delivery'], fmt=MONEY, fill=TGT_FILL)
        put(f'J{rt}', f'=I{rt}/$E$1', fmt=MONEY, fill=TGT_FILL)
        put(f'L{rt}', tgt['credit'], fmt=MONEY, fill=TGT_FILL)
        put(f'O{rt}', f'=I{rt}+L{rt}', fmt=MONEY, fill=TGT_FILL)
        put(f'R{rt}', tgt['gross_profit'], fmt=MONEY, fill=TGT_FILL)
        put(f'U{rt}', tgt['customer_count'], fmt=MONEY, fill=TGT_FILL)
        put(f'Z{rt}', tgt['beauty'], fmt=MONEY, fill=TGT_FILL)
        put(f'AB{rt}', b['name'], align=RIGHT, font=BOLD, fill=TGT_FILL)
        # achieved row — exact actuals, rounded to the nearest whole number
        put(f'A{ra}', 'delivery', align=CTR)
        put(f'D{ra}', 'المحقق', align=CTR, font=BOLD)
        put(f'E{ra}', _whole(ach['cash']), fmt=MONEY)
        put(f'F{ra}', _whole(ach['delivery']), fmt=MONEY)
        put(f'G{ra}', _whole(ach['regular']), fmt=MONEY)
        put(f'H{ra}', f'=E{ra}+F{ra}+G{ra}', fmt=MONEY)
        put(f'I{ra}', f'=I{rt}/$E$1*$H$1', fmt=MONEY)
        put(f'J{ra}', f'=H{ra}/I{ra}', fmt=PCT)
        put(f'K{ra}', _whole(ach['credit']), fmt=MONEY)
        put(f'L{ra}', f'=L{rt}/$E$1*$H$1', fmt=MONEY)
        put(f'M{ra}', f'=K{ra}/L{ra}', fmt=PCT)
        put(f'N{ra}', f'=H{ra}+K{ra}', fmt=MONEY)
        put(f'O{ra}', f'=I{ra}+L{ra}', fmt=MONEY)
        put(f'P{ra}', f'=N{ra}/O{ra}', fmt=PCT)
        put(f'Q{ra}', _whole(ach['profit']), fmt=MONEY)
        put(f'R{ra}', f'=R{rt}/$E$1*$H$1', fmt=MONEY)
        put(f'S{ra}', f'=Q{ra}/R{ra}', fmt=PCT)
        put(f'T{ra}', _whole(ach['customers']), fmt=MONEY)
        put(f'U{ra}', f'=U{rt}/$E$1*$H$1', fmt=MONEY)
        put(f'V{ra}', f'=T{ra}/U{ra}', fmt=PCT)
        put(f'Y{ra}', _whole(ach['beauty']), fmt=MONEY)
        put(f'Z{ra}', f'=Z{rt}/$E$1*$H$1', fmt=MONEY)
        put(f'AA{ra}', f'=Y{ra}/Z{ra}', fmt=PCT)
        put(f'AB{ra}', 'المحقق', align=CTR, font=BOLD)
        put(f'AC{ra}', f'=$AC$7*$J{ra}', fmt=PCT)
        put(f'AD{ra}', f'=$AD$7*$M{ra}', fmt=PCT)
        put(f'AE{ra}', f'=$AE$7*$S{ra}', fmt=PCT)
        put(f'AF{ra}', f'=IF(($AF$7*$V{ra})>$AF$7,$AF$7,($AF$7*$V{ra}))', fmt=PCT)
        put(f'AG{ra}', f'=IF(($AG$7*$AA{ra})>$AG$7,$AG$7,($AG$7*$AA{ra}))', fmt=PCT)
        put(f'AH{ra}', '=$AH$7*$J$19', fmt=PCT)
        put(f'AI{ra}', f'=SUM(AC{ra}:AH{ra})', fmt=PCT, font=BOLD)

    # ── totals rows ──────────────────────────────────────────────────────────
    tr, ar = ROW_TOTAL_TGT, ROW_TOTAL_ACH
    tsum = lambda col: '+'.join(f'{col}{r}' for r in TARGET_ROWS)
    asum = lambda col: '+'.join(f'{col}{r}' for r in ACH_ROWS)
    put(f'B{tr}', 'اجمالى الفروع', font=BOLD, align=RIGHT, fill=TOTAL_FILL)
    for col in ('I', 'L', 'O', 'R', 'U', 'Z'):
        put(f'{col}{tr}', f'={tsum(col)}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'AB{tr}', 'إجمالى الفروع', font=BOLD, align=RIGHT, fill=TOTAL_FILL)

    put(f'B{ar}', 'اجمالى المحقق', font=BOLD, align=RIGHT, fill=TOTAL_FILL)
    put(f'H{ar}', f'={asum("H")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'I{ar}', f'={asum("I")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'J{ar}', f'=H{ar}/I{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'K{ar}', f'={asum("K")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'L{ar}', f'={asum("L")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'M{ar}', f'=K{ar}/L{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'N{ar}', f'={asum("N")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'O{ar}', f'={asum("O")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'P{ar}', f'=N{ar}/O{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'Q{ar}', f'={asum("Q")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'R{ar}', f'={asum("R")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'S{ar}', f'=Q{ar}/R{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'T{ar}', f'={asum("T")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'U{ar}', f'={asum("U")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'V{ar}', f'=T{ar}/U{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'Y{ar}', f'={asum("Y")}', fmt=MONEY, font=BOLD, fill=TOTAL_FILL)
    put(f'Z{ar}', f'={asum("Z")}', fmt=MONEY, fill=TOTAL_FILL)
    put(f'AA{ar}', f'=Y{ar}/Z{ar}', fmt=PCT, font=BOLD, fill=TOTAL_FILL)
    put(f'AB{ar}', 'المحقق', font=BOLD, align=CTR, fill=TOTAL_FILL)
    put(f'AC{ar}', '=$AC$7*$J19', fmt=PCT, fill=TOTAL_FILL)
    put(f'AD{ar}', '=$AD$7*$M19', fmt=PCT, fill=TOTAL_FILL)
    put(f'AE{ar}', '=$AE$7*$S19', fmt=PCT, fill=TOTAL_FILL)
    put(f'AF{ar}', '=IF(($AF$7*$V19)>$AF$7,$AF$7,($AF$7*$V19))', fmt=PCT, fill=TOTAL_FILL)
    put(f'AG{ar}', '=IF(($AG$7*$AA19)>$AG$7,$AG$7,($AG$7*$AA19))', fmt=PCT, fill=TOTAL_FILL)
    put(f'AH{ar}', '=$AH$7*$J$19', fmt=PCT, fill=TOTAL_FILL)
    put(f'AI{ar}', '=SUM(AC19:AH19)', fmt=PCT, font=BOLD, fill=TOTAL_FILL)

    # ── call center section ──────────────────────────────────────────────────
    _write_cc_block(ws, cc, mkey, put, steps)
    # ── management summary block ─────────────────────────────────────────────
    _write_mgmt_block(ws, put)

    # column widths (mirror legacy, approximately)
    widths = {'A': 11, 'B': 15, 'C': 7, 'D': 20, 'E': 14, 'F': 13, 'G': 13, 'H': 15,
              'I': 14, 'J': 9, 'K': 14, 'L': 14, 'M': 9, 'N': 15, 'O': 14, 'P': 9,
              'Q': 13, 'R': 13, 'S': 9, 'T': 11, 'U': 11, 'V': 9, 'W': 12, 'X': 11,
              'Y': 13, 'Z': 14, 'AA': 9, 'AB': 20, 'AC': 10, 'AD': 10, 'AE': 10,
              'AF': 10, 'AG': 10, 'AH': 11, 'AI': 10, 'AJ': 10, 'AK': 12}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = 'A8'


def _write_cc_block(ws, cc, mkey, put, steps):
    # labels row 21
    for coord, txt in [('W21', 'المبيعات'), ('X21', 'الربحية'), ('Y21', 'التجميل'),
                       ('Z21', 'عدد العملاء'), ('AA21', 'عدد المكالمات'), ('AC21', 'الاجمالى'),
                       ('AG21', 'Cash'), ('AH21', 'Credit'), ('AI21', 'Profit Factor'),
                       ('AJ21', 'PIC'), ('AK21', 'Cosm+O')]:
        put(coord, txt, font=HDR_FONT, fill=HDR_FILL, align=CTR)
    # row 22 — CC targets (rounded to the same per-KPI step) + weights
    _cc_step = {'sales': 'cash_delivery', 'profit': 'gross_profit',
                'beauty': 'beauty', 'orders': 'customer_count'}
    t = (lambda name: int(round_up_step(cc[name][mkey], steps.get(_cc_step[name], 1)))
         if cc and name in cc else 0)
    put('C22', 1, align=CTR, fill=CC_FILL)
    put('D22', 'call center', font=BOLD, align=CTR, fill=CC_FILL)
    put('E22', 'الاجمالى المبيعات', align=RIGHT, fill=CC_FILL)
    put('F22', t('sales'), fmt=MONEY, fill=CC_FILL)
    put('H22', 'الربحية', align=RIGHT, fill=CC_FILL)
    put('I22', t('profit'), fmt=MONEY, fill=CC_FILL)
    put('K22', 'التجميل', align=RIGHT, fill=CC_FILL)
    put('L22', t('beauty'), fmt=MONEY, fill=CC_FILL)
    put('N22', 'عدد العملاء', align=RIGHT, fill=CC_FILL)
    put('O22', t('orders'), fmt=MONEY, fill=CC_FILL)
    put('Q22', 'عدد المكالمات', align=RIGHT, fill=CC_FILL)
    put('R22', '', fmt=MONEY, fill=CC_FILL)   # calls target: manual (no CDR history)
    put('U22', 0, align=CTR, fill=CC_FILL)
    for coord, w in [('W22', 0.5), ('X22', 0.1), ('Y22', 0.15), ('Z22', 0.1), ('AA22', 0.15)]:
        put(coord, w, align=CTR, fmt='0.00', fill=CC_FILL)
    # management achievers (row 22, AG..AK)
    put('AF22', 'إجمالى الفروع المحققة', font=BOLD, align=RIGHT, fill=SUB_FILL)
    _mgmt_branch_formula(put, 22, achieved=True)
    # row 23 — CC achieved (from rollup). CC stores cash_delivery as ONE metric
    # (no cash/delivery/عميل دائم split), so read it directly for sales.
    cc_ach = _achieved(cc['_cc_id'], _CC_CTX['year'], _CC_CTX['month']) if cc else None
    cc_sales = float(_roll(cc['_cc_id'], _CC_CTX['year'], _CC_CTX['month'], K.M_CASH_DELIVERY)) if cc else 0
    cc_calls = float(_roll(cc['_cc_id'], _CC_CTX['year'], _CC_CTX['month'], K.M_CALL_COUNT)) if cc else 0
    put('D23', 'المحقق', align=CTR, font=BOLD)
    put('E23', _whole(cc_sales) if cc else 0, fmt=MONEY)
    put('F23', '=F22/$E$1*$H$1', fmt=MONEY)
    put('G23', '=E23/F23', fmt=PCT)
    put('H23', _whole(cc_ach['profit']) if cc else 0, fmt=MONEY)
    put('I23', '=I22/$E$1*$H$1', fmt=MONEY)
    put('J23', '=H23/I23', fmt=PCT)
    put('K23', _whole(cc_ach['beauty']) if cc else 0, fmt=MONEY)
    put('L23', '=L22/$E$1*$H$1', fmt=MONEY)
    put('M23', '=K23/L23', fmt=PCT)
    put('N23', _whole(cc_ach['customers']) if cc else 0, fmt=MONEY)
    put('O23', '=O22/$E$1*$H$1', fmt=MONEY)
    put('P23', '=N23/O23', fmt=PCT)
    put('Q23', _whole(cc_calls), fmt=MONEY)                # calls achieved (0 w/o CDR)
    put('R23', '=R22/$E$1*$H$1', fmt=MONEY)
    put('S23', '=IF(R23=0,0,Q23/R23)', fmt=PCT)
    put('U23', '=U22/$E$1*$H$1', fmt=MONEY)
    put('W23', '=$G23*$W22', fmt=PCT)
    put('X23', '=$J$23*$X$22', fmt=PCT)
    put('Y23', '=$M$23*$Y$22', fmt=PCT)
    put('Z23', '=$P$23*$Z$22', fmt=PCT)
    put('AA23', '=$S$23*$AA$22', fmt=PCT)
    put('AC23', '=SUM(W23:AB23)', fmt=PCT, font=BOLD)
    put('AF23', 'إجمالى الفرق للفروع الغير محققة', font=BOLD, align=RIGHT, fill=SUB_FILL)
    _mgmt_branch_formula(put, 23, achieved=False)


# columns in the branch grid feeding each management category (achieved, target, ratio)
_MGMT_CATS = [
    ('AG', 'H', 'I', 'J'),   # Cash   (achieved H, target I, ratio J)
    ('AH', 'K', 'L', 'M'),   # Credit
    ('AI', 'Q', 'R', 'S'),   # Profit
    ('AJ', 'T', 'U', 'V'),   # PIC
    ('AK', 'Y', 'Z', 'AA'),  # Cosm
]


def _mgmt_branch_formula(put, row, *, achieved):
    """Row 22 = Σ achieved value for branches ≥90%; Row 23 = Σ shortfall for branches <90%."""
    for outcol, ach, tgt, ratio in _MGMT_CATS:
        parts = []
        for r in ACH_ROWS:
            if achieved:
                parts.append(f'(IF({ratio}${r}>=90%,{ach}${r},0))')
            else:
                parts.append(f'(IF({ratio}${r}<90%,{tgt}${r}-{ach}${r},0))')
        put(f'{outcol}{row}', '=SUM(' + ','.join(parts) + ')', fmt=MONEY)


def _write_mgmt_block(ws, put):
    put('Y24', 'غير محقق', align=CTR, font=BOLD, fill=SUB_FILL)
    put('AB24', 'الصافى للادارة', font=BOLD, align=RIGHT, fill=SUB_FILL)
    # الصافى = محققة − غير محققة  (AC..AG ← AG..AK)
    for dst, src in zip(['AC', 'AD', 'AE', 'AF', 'AG'], ['AG', 'AH', 'AI', 'AJ', 'AK']):
        put(f'{dst}24', f'={src}22-{src}23', fmt=MONEY)
    put('AB25', 'التارجت الكلى', font=BOLD, align=RIGHT, fill=SUB_FILL)
    for dst, src in zip(['AC', 'AD', 'AE', 'AF', 'AG'], ['I', 'L', 'R', 'U', 'Z']):
        put(f'{dst}25', f'={src}19', fmt=MONEY)
    put('AB26', 'نسبة التحقيق الصافى للادارة', font=BOLD, align=RIGHT, fill=SUB_FILL)
    # IF chain weighted-score < 0.9×weight → net/total, else the plain chain ratio.
    # NB: AE26 references P19 verbatim from the legacy sheet (owner formula).
    chain_ratio = {'AC': 'J$19', 'AD': 'M$19', 'AE': 'P$19', 'AF': 'V$19', 'AG': 'AA$19'}
    for col in ['AC', 'AD', 'AE', 'AF', 'AG']:
        put(f'{col}26', f'=(IF({col}$19<(0.9*{col}$7),{col}$24/{col}$25,{chain_ratio[col]}))', fmt=PCT)
    put('AB27', 'الوزن النسبى', font=BOLD, align=RIGHT, fill=SUB_FILL)
    for coord, w in [('AC27', 0.55), ('AD27', 0.15), ('AE27', 0.15), ('AF27', 0.05), ('AG27', 0.1)]:
        put(coord, w, align=CTR, fmt='0.00')
    put('AH27', '=SUM(AC27:AG27)', fmt='0.00', font=BOLD)
    put('AB28', 'نسبة التحقيق بالوزن النسبى', font=BOLD, align=RIGHT, fill=SUB_FILL)
    for col in ['AC', 'AD', 'AE', 'AF', 'AG']:
        put(f'{col}28', f'={col}26*{col}27', fmt=PCT)
    put('AH28', '=SUM(AC28:AG28)', fmt=PCT, font=BOLD)


# module-level CC context (year/month) for the CC achieved lookup inside _write_cc_block
_CC_CTX = {'year': None, 'month': None}


# ── reconciliation sheet (legacy workbook vs our rollups) ────────────────────
def _read_legacy_achieved(path):
    """Read achieved values from an owner legacy target workbook (data_only)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    out = {}
    for rt, ra in zip(TARGET_ROWS, ACH_ROWS):
        code = ws[f'C{rt}'].value
        if code is None:
            continue
        code = str(int(code)) if isinstance(code, (int, float)) else str(code).strip()
        out[code] = {
            'cash_delivery': ws[f'H{ra}'].value, 'credit': ws[f'K{ra}'].value,
            'gross_profit': ws[f'Q{ra}'].value, 'customer_count': ws[f'T{ra}'].value,
            'beauty': ws[f'Y{ra}'].value,
        }
    # call center (row 23): E23 sales, H23 profit, K23 beauty, N23 orders
    out['CC'] = {'cash_delivery': ws['E23'].value, 'gross_profit': ws['H23'].value,
                 'beauty': ws['K23'].value, 'customer_count': ws['N23'].value}
    return out


def _write_recon_sheet(ws, year, month, legacy_path):
    legacy = _read_legacy_achieved(legacy_path)
    from apps.branches.models import Branch
    ws.sheet_view.rightToLeft = True
    hdr = ['الكود', 'الفرع', 'المؤشر', 'النظام الجديد', 'ملف الإكسل', 'الفرق', 'الفرق %', 'ملاحظة']
    ws.append([f'مطابقة {_AR_MONTHS[month]} {year} — النظام الجديد مقابل ملف الإكسل'])
    ws['A1'].font = BOLD
    ws.append(hdr)
    for c in range(1, len(hdr) + 1):
        cell = ws.cell(row=2, column=c)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = CTR
    MLAB = {'cash_delivery': 'نقدى+توصيل', 'credit': 'آجل', 'gross_profit': 'معامل الربحية',
            'customer_count': 'عدد العملاء', 'beauty': 'التجميل'}
    metrics = ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty']
    branches = {b.code: b for b in Branch.objects.filter(code__in=[c for c in legacy if c != 'CC'])}
    cc = Branch.objects.filter(softech_branch_id='CC').first()

    def emit(code, name, bid, legvals):
        for m in metrics:
            new = float(_roll(bid, year, month, m)) if bid else 0.0
            old = legvals.get(m)
            old = float(old) if old is not None else None
            diff = (new - old) if old is not None else None
            pct = (diff / old) if (old not in (None, 0)) else None
            note = ''
            if pct is not None and m != 'customer_count' and abs(pct) > 0.03:
                note = '⚠️ فرق جوهري'
            if m == 'customer_count' and old is not None and abs(new - old) > 10:
                note = '⚠️ فرق جوهري'
            r = ws.max_row + 1
            ws.cell(row=r, column=1, value=code)
            ws.cell(row=r, column=2, value=name)
            ws.cell(row=r, column=3, value=MLAB[m])
            ws.cell(row=r, column=4, value=round(new, 2)).number_format = MONEY
            ws.cell(row=r, column=5, value=(round(old, 2) if old is not None else '—')).number_format = MONEY
            ws.cell(row=r, column=6, value=(round(diff, 2) if diff is not None else '—')).number_format = MONEY
            ws.cell(row=r, column=7, value=(round(pct, 4) if pct is not None else '—')).number_format = PCT
            ws.cell(row=r, column=8, value=note)

    for code in ['160', '170', '140', '150', '130']:
        if code in legacy and code in branches:
            b = branches[code]
            emit(code, getattr(b, 'name_ar', '') or b.name, b.id, legacy[code])
    if 'CC' in legacy and cc:
        emit('CC', 'الكول سنتر', cc.id, legacy['CC'])
    widths = [8, 24, 14, 16, 16, 14, 10, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ── scenario detail export (all forecast data: per-KPI branch rows + totals) ──
def build_scenario_workbook(scenario):
    """Export every ForecastResult of a scenario: per metric, branch rows then total,
    with base / LM / PM / Model A / Model B / forecast / target + the scenario knobs."""
    from .models import ForecastResult
    wb = Workbook()
    ws = wb.active
    ws.title = 'التنبؤ'
    ws.sheet_view.rightToLeft = True
    model_lbl = dict(scenario.MODEL_CHOICES).get(scenario.model, scenario.model)
    scope_lbl = dict(scenario.SCOPE_CHOICES).get(scenario.scope_type, scenario.scope_type)

    r = 1

    def row(cells, *, bold=False, fill=None, fmts=None):
        nonlocal r
        for i, v in enumerate(cells, start=1):
            c = ws.cell(row=r, column=i, value=v)
            if bold:
                c.font = BOLD
            if fill:
                c.fill = fill
            if fmts and i - 1 < len(fmts) and fmts[i - 1]:
                c.number_format = fmts[i - 1]
            c.border = BORDER
        r += 1

    # header / meta
    ws.cell(row=r, column=1, value=f'سيناريو التنبؤ — {scenario.name}').font = Font(bold=True, size=13)
    r += 1
    ws.cell(row=r, column=1,
            value=f'{_AR_MONTHS[scenario.month]} {scenario.year} · {scope_lbl} · {model_lbl} · '
                  f'حد الحافز {scenario.incentive_threshold} · نمو مرجعي {scenario.benchmark_growth}'
                  f' · تضخم {scenario.inflation} · عروض {scenario.promotion_lift}')
    r += 2

    rows = list(ForecastResult.objects.filter(scenario=scenario))
    metrics = []
    for x in rows:
        if x.metric not in metrics:
            metrics.append(x.metric)
    HDR = ['النطاق', 'الأساس (العام السابق)', 'الشهر السابق', 'قبل السابق',
           'Model A', 'Model B', 'التنبؤ', 'الهدف', 'الحصة']
    MFMT = [None, MONEY, MONEY, MONEY, MONEY, MONEY, MONEY, MONEY, '0.0%']

    for m in metrics:
        label = K.METRIC_LABELS.get(m, m)
        row([label], bold=True, fill=HDR_FILL)
        ws.cell(row=r - 1, column=1).font = HDR_FONT
        row(HDR, bold=True, fill=SUB_FILL)
        members = [x for x in rows if x.metric == m and x.scope_key != 'chain']
        members.sort(key=lambda x: float(x.target_value), reverse=True)
        chain = next((x for x in rows if x.metric == m and x.scope_key == 'chain'), None)
        for x in members:
            row([x.scope_label or '', float(x.base_value), float(x.lm_value), float(x.pm_value),
                 float(x.model_a), float(x.model_b), float(x.forecast_value), float(x.target_value),
                 float(x.branch_share)], fmts=MFMT)
        if chain:
            row(['الإجمالى', float(chain.base_value), float(chain.lm_value), float(chain.pm_value),
                 float(chain.model_a), float(chain.model_b), float(chain.forecast_value),
                 float(chain.target_value), 1.0], bold=True, fill=TOTAL_FILL, fmts=MFMT)
        r += 1   # spacer

    # factors sheet
    fs = wb.create_sheet('العوامل')
    fs.sheet_view.rightToLeft = True
    fs.append(['المؤشر', 'هدف النمو (A)', 'وزن الشهر السابق', 'وزن قبل السابق',
               'وزن العام السابق', 'مؤشر موسمي'])
    for c in range(1, 7):
        fs.cell(row=1, column=c).font = HDR_FONT
        fs.cell(row=1, column=c).fill = HDR_FILL
    for f in scenario.factors.all():
        fs.append([K.METRIC_LABELS.get(f.metric, f.metric), float(f.growth_goal),
                   float(f.w_lm), float(f.w_pm), float(f.w_yoy), float(f.seasonality_index)])

    for col, w in {'A': 24, 'B': 18, 'C': 14, 'D': 13, 'E': 12, 'F': 12, 'G': 13, 'H': 13, 'I': 9}.items():
        ws.column_dimensions[col].width = w
    for col in ['A', 'B', 'C', 'D', 'E', 'F']:
        fs.column_dimensions[col].width = 16
    return wb


# ── public entry point ───────────────────────────────────────────────────────
def build_target_workbook(year, month, *, models=('a', 'b', 'avg'), days_elapsed=None,
                          recon_legacy=None, incentive_threshold=Decimal('0.90'),
                          benchmark_growth=Decimal('0.30'), factors=None):
    """
    Build the faithful target workbook. `models` → one sheet each ('a','b','avg').
    `recon_legacy` → list of legacy xlsx paths (same month) to append reconciliation sheets.
    Returns an openpyxl Workbook.
    """
    _CC_CTX['year'], _CC_CTX['month'] = year, month
    if days_elapsed is None:
        today = date.today()
        days_elapsed = today.day if (today.year, today.month) == (year, month) else monthrange(year, month)[1]

    data = forecast_targets(year, month, incentive_threshold=incentive_threshold,
                            benchmark_growth=benchmark_growth, factors=factors)
    cc = cc_targets(year, month, incentive_threshold=incentive_threshold,
                    benchmark_growth=benchmark_growth, factors=factors)
    achieved_by_branch = {b['id']: _achieved(b['id'], year, month) for b in data['branches']}
    steps = kpi_round_steps()

    wb = Workbook()
    wb.remove(wb.active)
    model_names = {'a': 'Model A', 'b': 'Model B', 'avg': 'Avg (A+B)'}
    for mk in models:
        ws = wb.create_sheet(title=f'{model_names[mk]} {_AR_MONTHS[month]}')
        _write_model_sheet(ws, year, month, data, cc, achieved_by_branch, mk, days_elapsed, steps)
    for path in (recon_legacy or []):
        ws = wb.create_sheet(title='مطابقة')
        _write_recon_sheet(ws, year, month, path)
    return wb
