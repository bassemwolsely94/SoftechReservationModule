"""Excel exports of the general-ledger reports in finance's layout (finance-gl Task 8).

Right-to-left sheets, Arabic headers, amounts as numbers with `#,##0.00`, branches as
"code · name" labels (never a bare code).  Each function takes the dict the API view built and
returns an HttpResponse.
"""
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.http import HttpResponse
from openpyxl.styles import Alignment, Font, PatternFill

from core.export_safety import neutralise_formulas

from .statements import EXPENSE_LINES, LABELS

MONEY = '#,##0.00'
PCT = '0.00%'
HEAD_FILL = PatternFill('solid', fgColor='022871')
WARN_FONT = Font(bold=True, color='B45309')

TRADING_ROWS = ['net_sales', 'opening_stock', 'net_purchases', 'closing_stock', 'cost_of_sales',
                'gross_profit', 'other_revenue', 'capital_gains', *EXPENSE_LINES, 'total_expenses',
                'unclassified', 'net_profit']
SOFTECH_ROWS = ('softech_sales', 'softech_cost', 'softech_gross_profit')
RATIO_ROWS = [('gross_margin', 'هامش مجمل الربح'), ('net_margin', 'هامش صافى الربح'),
              ('expense_ratio', 'نسبة المصاريف لصافى المبيعات')]
POSITION_ROWS = [
    ('fixed_assets', 'الأصول الثابتة (التكلفة)'), ('accumulated_depreciation', 'مجمع الإهلاك'),
    ('net_fixed_assets', 'صافى الأصول الثابتة'),
    ('inventory', 'المخزون'), ('receivables', 'العملاء'), ('other_debtors', 'مدينون وأرصدة مدينة أخرى'),
    ('deposits', 'تأمينات لدى الغير'), ('cash', 'النقدية بالصندوق والبنوك'),
    ('total_current_assets', 'إجمالى الأصول المتداولة'),
    ('creditors', 'دائنون وأرصدة دائنة أخرى'), ('overdraft', 'بنوك سحب على المكشوف'),
    ('notes_payable', 'أوراق الدفع'), ('suppliers', 'الموردون'),
    ('total_current_liabilities', 'إجمالى الخصوم المتداولة'),
    ('working_capital', 'رأس المال العامل'), ('unclassified', 'حسابات بدون بند'),
    ('total_investment', 'إجمالى الاستثمار'),
    ('capital', 'رأس المال'), ('partners', 'جارى الشركاء'), ('profit_and_loss', 'الأرباح والخسائر'),
    ('total_equity', 'إجمالى حقوق الملكية'), ('check', 'فرق (يجب أن يكون صفراً)'),
]


def _num(v):
    if v is None or v == '':
        return None
    return float(v) if isinstance(v, (Decimal, int, float, str)) else v


def _book(title, subtitle, headers, widths, warnings=()):
    """Title, subtitle, then each server warning («⚠ …», under the title so nobody misses it),
    a blank row and the header row."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.sheet_view.rightToLeft = True
    ws.append([title])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append([subtitle])
    for w in warnings or ():
        ws.append([f'⚠ {w}'])
        ws.cell(row=ws.max_row, column=1).font = WARN_FONT
    ws.append([])
    ws.append(headers)
    head = ws.max_row
    for i, w in enumerate(widths, start=1):
        cell = ws.cell(row=head, column=i)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[cell.column_letter].width = w
    ws.freeze_panes = f'A{head + 1}'
    return wb, ws


def _fmt(ws, first_col, last_col, fmt=MONEY, start_row=5):
    for row in ws.iter_rows(min_row=start_row, min_col=first_col, max_col=last_col):
        for c in row:
            if isinstance(c.value, (int, float)):
                c.number_format = fmt


def _bold_row(ws, row):
    for c in ws[row]:
        c.font = Font(bold=True)


def _response(wb, filename):
    buf = BytesIO()
    neutralise_formulas(wb).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


SUBLEDGER_TITLES = {'suppliers': 'الموردون', 'creditors': 'الدائنون', 'notes_payable': 'أوراق الدفع',
                    'customers': 'العملاء', 'employees': 'الموظفون', 'partners': 'جارى الشركاء'}


def subledger(d):
    """A party's rows, «بدون طرف», the totals; notes payable lists each month's cheques under it."""
    amounts = ('opening', 'debit', 'credit', 'closing')
    wb, ws = _book(f'الأستاذ المساعد - {SUBLEDGER_TITLES[d["kind"]]}', f'من {d["from"]} إلى {d["to"]}',
                   ['الكود', 'الاسم', 'افتتاحي', 'مدين', 'دائن', 'ختامي'], [14, 40, 16, 16, 16, 16])

    def add(r):
        ws.append([r['key'] or '', r['name'], *(_num(r[c]) for c in amounts)])
    for r in d['rows']:
        add(r)
        for c in r.get('cheques', ()):
            ws.append([c['cheque_no'], f'{c["party"] or ""} — {c["due_date"] or ""}', None, None, None,
                       _num(c['amount'])])
    if d.get('unassigned'):
        add(d['unassigned'])
    add(d['totals'])
    _bold_row(ws, ws.max_row)
    _fmt(ws, 3, 6)
    return _response(wb, f'subledger_{d["kind"]}_{d["from"]}_{d["to"]}.xlsx')


def supplier_vs_ap(d):
    wb, ws = _book('الموردون مقابل سداد الموردين', f'فى {d["as_of"]}',
                   ['الكود', 'المورد', 'رصيد الأستاذ', 'رصيد سداد الموردين', 'الفرق', 'السبب'],
                   [14, 40, 18, 18, 18, 30])
    for r in d['rows']:
        ws.append([r['party_code'], r['name'], _num(r['gl_balance']), _num(r['ap_balance']),
                   _num(r['difference']), r['reason']])
    _fmt(ws, 3, 5)
    return _response(wb, f'suppliers_vs_ap_{d["as_of"]}.xlsx')


def trial_balance(d):
    by_group = d['by'] == 'group'
    headers = (['المجموعة'] if by_group else ['الكود', 'الحساب', 'المجموعة']) + [
        'افتتاحي مدين', 'افتتاحي دائن', 'حركة مدين', 'حركة دائن', 'ختامي مدين', 'ختامي دائن']
    widths = ([34] if by_group else [10, 36, 26]) + [16] * 6
    wb, ws = _book('ميزان المراجعة', f'من {d["from"]} إلى {d["to"]}', headers, widths)
    cols = ('opening_debit', 'opening_credit', 'period_debit', 'period_credit',
            'closing_debit', 'closing_credit')
    for r in d['rows']:
        lead = [r['name']] if by_group else [r['code'] or '', r['name'], r['group'] or '']
        if r.get('is_total'):
            lead = ['الإجمالى'] if by_group else ['', 'الإجمالى', '']
        ws.append(lead + [_num(r[c]) for c in cols])
        if r.get('is_total'):
            _bold_row(ws, ws.max_row)
    _fmt(ws, len(headers) - 5, len(headers))
    return _response(wb, f'trial_balance_{d["from"]}_{d["to"]}.xlsx')


def account_statement(d):
    wb, ws = _book(f'كشف حساب {d["code"]}', f'{d["code"]} {d["name"]} — من {d["from"]} إلى {d["to"]}',
                   ['التاريخ', 'رقم القيد', 'البيان', 'مدين', 'دائن', 'الرصيد'], [12, 18, 50, 16, 16, 18])
    ws.append(['', '', 'رصيد أول المدة', None, None, _num(d['opening_balance'])])
    for ln in d['lines']:
        ws.append([str(ln['date']), ln['number'] or '', ln['description'] or '',
                   _num(ln['debit']), _num(ln['credit']), _num(ln['running_balance'])])
    ws.append(['', '', 'رصيد آخر المدة', None, None, _num(d['closing_balance'])])
    _bold_row(ws, ws.max_row)
    _fmt(ws, 4, 6)
    return _response(wb, f'account_statement_{d["code"]}_{d["from"]}_{d["to"]}.xlsx')


def trading(d):
    wb, ws = _book('الختامية', f'من {d["from"]} إلى {d["to"]}', ['البند', 'القيمة'], [36, 18],
                   warnings=d.get('warnings'))
    for k in TRADING_ROWS:
        if k == 'unclassified' and not d.get(k):
            continue
        ws.append([LABELS.get(k, k), _num(d.get(k))])
        if k in ('gross_profit', 'net_profit'):
            _bold_row(ws, ws.max_row)
    _fmt(ws, 2, 2)
    ws.append([])
    for k, label in RATIO_ROWS:
        ws.append([label, _num(d.get(k))])
        ws.cell(row=ws.max_row, column=2).number_format = PCT
    ws.append(['متوسط المبيعات الشهرى', _num(d.get('monthly_avg_sales'))])
    ws.cell(row=ws.max_row, column=2).number_format = MONEY
    return _response(wb, f'trading_pl_{d["from"]}_{d["to"]}.xlsx')


def position(d):
    wb, ws = _book('المركز المالى', f'فى {d["as_of"]}', ['البند', 'القيمة'], [36, 18],
                   warnings=d.get('warnings'))
    for k, label in POSITION_ROWS:
        if k in ('unclassified', 'check') and not d.get(k):
            continue
        ws.append([label, _num(d.get(k))])
        if k.startswith('total_') or k == 'working_capital':
            _bold_row(ws, ws.max_row)
    _fmt(ws, 2, 2)
    return _response(wb, f'financial_position_{d["as_of"]}.xlsx')


def branch_pl(d):
    cols = d['columns']
    total = next((c for c in cols if c.get('is_total')), {})
    wb, ws = _book('الختامية فروع بالتوزيع', f'من {d["from"]} إلى {d["to"]}',
                   ['البند'] + [c['label'] for c in cols], [34] + [18] * len(cols),
                   warnings=total.get('warnings'))
    for k in TRADING_ROWS:
        if k == 'unclassified' and not any(c.get(k) for c in cols):
            continue
        ws.append([LABELS.get(k, k)] + [_num(c.get(k)) for c in cols])
        if k == 'gross_profit':   # Ruling P34: SOFTECH's own figures, beside the ledger figures
            for sk in SOFTECH_ROWS:
                ws.append([LABELS[sk]] + [_num(c.get(sk)) for c in cols])
    for k in EXPENSE_LINES:
        ws.append([f'توزيع {LABELS.get(k, k)}'] + [_num(c['allocation'].get(k)) for c in cols])
    ws.append(['صافى الربح بعد التوزيع'] + [_num(c['after']['net_profit']) for c in cols])
    _bold_row(ws, ws.max_row)
    _fmt(ws, 2, len(cols) + 1)
    return _response(wb, f'branch_pl_{d["from"]}_{d["to"]}.xlsx')


def comparison(d):
    years = d['years']
    headers = ['البند']
    for y in years:
        headers += [str(y['year']), f'% {y["year"]}']
    wb, ws = _book('الختامية المجمعة', '، '.join(str(y['year']) for y in years), headers,
                   [34] + [16, 10] * len(years))
    for k in TRADING_ROWS:
        row = [LABELS.get(k, k)]
        for y in years:
            row += [_num(y['values'].get(k)), _num(y['pct_of_sales'].get(k))]
        ws.append(row)
    for r in ws.iter_rows(min_row=5):
        for i, c in enumerate(r[1:], start=0):
            if isinstance(c.value, (int, float)):
                c.number_format = MONEY if i % 2 == 0 else PCT
    return _response(wb, 'comparison_' + '_'.join(str(y['year']) for y in years) + '.xlsx')
