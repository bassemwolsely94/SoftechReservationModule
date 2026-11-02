"""
Excel workbook for «تقارير المطالبات» (portfolio.build_report): one sheet per section,
in the order and grouping the user chose, with subtotals and grand totals.
"""
import io
from collections import OrderedDict

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from core.export_safety import neutralise_formulas

from .export import (_w, _margins, FONT_HEADER, FILL_HEADER, ALIGN_CENTER, ALIGN_RIGHT,
                     FONT_SUBTOTAL, FILL_SUBTOTAL, FONT_GRAND, FILL_GRAND, BL)

MONEY = '#,##0.00'
PCT = '0.00"%"'
STATUS = {'draft': 'مسودة', 'ready': 'جاهزة', 'submitted': 'مُقدَّمة', 'under_review': 'قيد المراجعة',
          'partially_paid': 'مدفوعة جزئياً', 'paid': 'مدفوعة', 'rejected': 'مرفوضة', 'cancelled': 'ملغاة'}


def _sheet(wb, title, cols, rows, *, first=False, group=None, totals=True, note=''):
    """cols = [(key, header, width, kind)] kind: text|int|money|pct. rows = list of dicts.
    group = key to subtotal on (rows must already be ordered by it)."""
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws.sheet_view.rightToLeft = True
    _margins(ws, 'landscape')
    r = 1
    if note:
        _w(ws, r, 1, note, font=FONT_GRAND, align=ALIGN_RIGHT)
        r += 2
    for i, (_k, h, wdt, _kind) in enumerate(cols, start=1):
        _w(ws, r, i, h, font=FONT_HEADER, fill=FILL_HEADER, align=ALIGN_CENTER)
        ws.column_dimensions[get_column_letter(i)].width = wdt
    ws.freeze_panes = ws.cell(row=r + 1, column=1)
    r += 1
    sums = [k for k, _h, _w2, kind in cols if kind in ('int', 'money')]

    def put(row, *, font=None, fill=None):
        nonlocal r
        for i, (k, _h, _w2, kind) in enumerate(cols, start=1):
            v = row.get(k, '')
            fmt = MONEY if kind == 'money' else PCT if kind == 'pct' else ('#,##0' if kind == 'int' else None)
            _w(ws, r, i, v if v is not None else '', font=font, fill=fill,
               align=ALIGN_RIGHT if kind == 'text' else ALIGN_CENTER, fmt=fmt)
        r += 1

    def total_row(label, part, font, fill):
        row = {k: sum(float(x.get(k) or 0) for x in part) for k in sums}
        row[cols[0][0]] = label
        put(row, font=font, fill=fill)

    groups = OrderedDict()
    for row in rows:
        groups.setdefault(row.get(group) if group else None, []).append(row)
    for g, part in groups.items():
        for row in part:
            put(row)
        if group and len(groups) > 1:
            total_row(f'إجمالى {g}', part, FONT_SUBTOTAL, FILL_SUBTOTAL)
    if totals and rows:
        total_row('الإجمالى العام', rows, FONT_GRAND, FILL_GRAND)
    return ws


def generate_portfolio_excel(report, *, title='تقارير المطالبات', group_by_client=False):
    wb = Workbook()
    T = report['totals']
    mot = report['motalbas']
    for m in mot:
        m['status_label'] = STATUS.get(m['status'], m['status'])
        m['period'] = f"{m['period_from'] or ''} ← {m['period_to'] or ''}"
        for k, v in m['bridge'].items():
            m[f'b_{k}'] = v
    if group_by_client:
        mot = sorted(mot, key=lambda m: m['client'])   # stable: keeps the chosen order inside a company

    summary = [
        {'k': 'عدد المطالبات', 'v': T.get('motalbas', 0)}, {'k': 'عدد الروشتات', 'v': T.get('rx_count', 0)},
        {'k': 'الإجمالى قبل الخصم', 'v': T.get('gross', 0)}, {'k': 'الخصم', 'v': T.get('discount', 0)},
        {'k': 'صافى المطالبات', 'v': T.get('net', 0)}, {'k': 'نصيب المريض', 'v': T.get('patient_share', 0)},
        {'k': 'الإيراد (المطالبة + المريض)', 'v': T.get('revenue', 0)}, {'k': 'التكلفة', 'v': T.get('cost', 0)},
        {'k': 'مجمل الربح', 'v': T.get('gp', 0)}, {'k': 'نسبة مجمل الربح %', 'v': T.get('gp_pct', 0)},
        {'k': 'المحصل', 'v': T.get('collected', 0)}, {'k': 'الرصيد', 'v': T.get('balance', 0)},
        {'k': 'زيادة القيمة من تعديلات سوفتك', 'v': T.get('bridge_softech_edits_delta', 0)},
        {'k': 'إضافات من مطالبات أخرى', 'v': T.get('bridge_from_other_net', 0)},
    ]
    _sheet(wb, 'ملخص', [('k', 'البند', 34, 'text'), ('v', 'القيمة', 20, 'money')], summary,
           first=True, totals=False, note=title)

    _sheet(wb, 'المطالبات', [
        ('claim_number', 'المطالبة', 15, 'text'), ('softech_motalba_no', 'رقم سوفتك', 10, 'text'),
        ('client', 'الجهة', 30, 'text'), ('subclient', 'الفئة', 16, 'text'), ('period', 'الفترة', 24, 'text'),
        ('status_label', 'الحالة', 11, 'text'), ('rx_count', 'الروشتات', 9, 'int'), ('patients', 'المرضى', 9, 'int'),
        ('local_before', 'محلى', 13, 'money'), ('imported_before', 'مستورد', 13, 'money'),
        ('tarsia_before', 'ترسية', 12, 'money'), ('gross', 'الإجمالى', 14, 'money'),
        ('discount', 'الخصم', 12, 'money'), ('net', 'الصافى', 14, 'money'),
        ('patient_share', 'نصيب المريض', 11, 'money'), ('revenue', 'الإيراد', 14, 'money'),
        ('cost', 'التكلفة', 14, 'money'), ('gp', 'مجمل الربح', 13, 'money'), ('gp_pct', 'GP %', 8, 'pct'),
        ('local_gp', 'ربح محلى', 12, 'money'), ('local_gp_pct', 'محلى %', 8, 'pct'),
        ('imported_gp', 'ربح مستورد', 12, 'money'), ('imported_gp_pct', 'مستورد %', 8, 'pct'),
        ('tarsia_gp', 'ربح ترسية', 12, 'money'), ('tarsia_gp_pct', 'ترسية %', 8, 'pct'),
        ('collected', 'المحصل', 12, 'money'), ('balance', 'الرصيد', 12, 'money'),
    ], mot, group='client' if group_by_client else None)

    _sheet(wb, 'جسر القيمة', [
        ('claim_number', 'المطالبة', 15, 'text'), ('client', 'الجهة', 30, 'text'),
        ('b_import_net', 'قيمة الاستيراد', 14, 'money'),
        ('b_softech_edits', 'إيصالات عُدّلت فى سوفتك', 10, 'int'), ('b_softech_edits_delta', 'زيادة من تعديلات سوفتك', 13, 'money'),
        ('b_catalog_delta', 'فرق تطبيق الكتالوج', 13, 'money'),
        ('b_excluded_count', 'مستبعد (عدد)', 9, 'int'), ('b_excluded_net', 'مستبعد (قيمة)', 13, 'money'),
        ('b_wrong_allocation', 'منها تخصيص خاطئ', 9, 'int'),
        ('b_manual_count', 'إضافات يدوية (عدد)', 9, 'int'), ('b_manual_net', 'إضافات يدوية (قيمة)', 13, 'money'),
        ('b_from_other_count', 'من مطالبات أخرى (عدد)', 9, 'int'), ('b_from_other_net', 'من مطالبات أخرى (قيمة)', 13, 'money'),
        ('b_supplements_count', 'ملاحق (روشتات)', 9, 'int'), ('b_supplements_net', 'ملاحق (قيمة)', 12, 'money'),
        ('b_other_adjustments', 'تعديلات أخرى', 12, 'money'), ('b_final_net', 'القيمة النهائية', 14, 'money'),
    ], mot, group='client' if group_by_client else None)

    for b in report['branches']:
        b['branch_label'] = BL(b['branch'])
    _sheet(wb, 'الفروع', [
        ('branch_label', 'الفرع', 30, 'text'), ('motalbas', 'المطالبات', 9, 'int'), ('rx', 'الروشتات', 9, 'int'),
        ('net', 'الصافى', 14, 'money'), ('patient_share', 'نصيب المريض', 11, 'money'),
        ('revenue', 'الإيراد', 14, 'money'), ('cost', 'التكلفة', 14, 'money'),
        ('gp', 'مجمل الربح', 13, 'money'), ('gp_pct', 'GP %', 8, 'pct'),
    ], report['branches'])

    rows = sorted(report['by_branch_claim'], key=lambda r: (r['claim_number'], r['branch']))
    for b in rows:
        b['branch_label'] = BL(b['branch'])
    _sheet(wb, 'المطالبة × الفرع', [
        ('claim_number', 'المطالبة', 15, 'text'), ('branch_label', 'الفرع', 30, 'text'), ('rx', 'الروشتات', 9, 'int'),
        ('net', 'الصافى', 14, 'money'), ('revenue', 'الإيراد', 14, 'money'), ('cost', 'التكلفة', 14, 'money'),
        ('gp', 'مجمل الربح', 13, 'money'), ('gp_pct', 'GP %', 8, 'pct'),
    ], rows, group='claim_number')

    rows = sorted(report['sellers'], key=lambda r: (r['branch'], -r['net']))
    for b in rows:
        b['branch_label'] = BL(b['branch'])
    _sheet(wb, 'البائعون', [
        ('branch_label', 'الفرع', 30, 'text'), ('seller', 'البائع', 22, 'text'), ('usercode', 'كود سوفتك', 9, 'text'),
        ('rx', 'الروشتات', 9, 'int'), ('net', 'الصافى', 14, 'money'), ('revenue', 'الإيراد', 14, 'money'),
        ('cost', 'التكلفة', 14, 'money'), ('gp', 'مجمل الربح', 13, 'money'), ('gp_pct', 'GP %', 8, 'pct'),
    ], rows, group='branch_label')

    _sheet(wb, 'الفئات المالية', [
        ('label', 'الفئة', 14, 'text'), ('gross', 'قبل الخصم', 14, 'money'), ('net', 'الصافى', 14, 'money'),
        ('cost', 'التكلفة', 14, 'money'), ('gp', 'مجمل الربح', 13, 'money'), ('gp_pct', 'GP %', 8, 'pct'),
    ], report['categories'])

    moves = [dict(m, from_claims_txt='، '.join(m['from_claims']) or '—', branch_label=BL(m['branch']))
             for m in report['moves']]
    _sheet(wb, 'تحويلات بين المطالبات', [
        ('to_claim', 'أُضيفت إلى', 15, 'text'), ('from_claims_txt', 'من المطالبة', 18, 'text'),
        ('docnumber', 'الإيصال', 11, 'text'), ('branch_label', 'الفرع', 26, 'text'), ('patient', 'المريض', 26, 'text'),
        ('net', 'الصافى', 13, 'money'), ('note', 'ملاحظة', 50, 'text'),
    ], moves)

    buf = io.BytesIO()
    neutralise_formulas(wb).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="motalbas_report.xlsx"'
    return resp
