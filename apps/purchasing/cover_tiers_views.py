"""
apps/purchasing/cover_tiers_views.py

C25 / P-34 «🎯 التغطية حسب الفئة» on /cash-optimization — READ-ONLY (apps/purchasing/cover_tiers.py).
Read = the purchasing matrix grant. Branch-level rows go through core/branch_scope: a branch-bound user sees only
own-branch lines. The 75/100/125% budget comparison uses the company's last-month purchases, so it is shown only
to a user who sees every branch and only for the whole network (no branch filter).

  GET /api/purchasing/cover-tiers/summary/?branch=
  GET /api/purchasing/cover-tiers/lines/?branch=&tier=&q=&need=1&ordering=&page=&page_size=   (format=xlsx = every line)
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.export_safety import neutralise_formulas
from core.multi_filter import multi_values
from core.permissions import matrix_permission

from apps.pic_analytics.queries.ordering import parse_ordering, sort_items

from . import cover_tiers as CT

COVER_READ = matrix_permission('purchasing')
LINE_ORDERS = ('itemcode', 'name', 'branch_name', 'tier', 'rate', 'sales_value', 'stock', 'transit', 'cover_months',
               'target_months', 'target_qty', 'need_qty', 'cost', 'stock_value', 'need_value', 'excess_value')
PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000


def _num(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _num(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_num(x) for x in v]
    return v


def _scope(request):
    """(codes to read or None = every branch, whether the whole network is in view)."""
    from core.branch_scope import branch_codes
    allowed = branch_codes(request.user)
    asked = set(multi_values(request.query_params, 'branch'))
    if asked:
        codes = asked if allowed is None else asked & allowed
        return codes, False
    return allowed, allowed is None


def _report(request):
    codes, whole = _scope(request)
    return CT.build_report(branch_codes=codes), whole


def _run_info(run):
    if run is None:
        return None
    return {'id': run.pk, 'calc_date': run.calc_date, 'finished_at': run.finished_at}


def _settings_out(st):
    return {'months': _num(st['months']), 'cut_a': float(st['cut_a']), 'cut_b': float(st['cut_b']),
            'keys': list(CT.SETTING_DEFAULTS)}


@api_view(['GET'])
@permission_classes([IsAuthenticated, COVER_READ])
def cover_tiers_summary(request):
    report, whole = _report(request)
    if report['run'] is None:
        return Response({'run': None, 'detail': 'لا يوجد تشغيل ناجح لمحرك الطلب بعد.',
                         'settings': _settings_out(report['settings'])})
    purchases = CT.last_month_purchases(timezone.localdate()) if whole else None
    summ = CT.summarize(report, purchases)
    return Response(_num({
        'run': _run_info(report['run']), 'settings': _settings_out(report['settings']),
        'tiers': summ['tiers'], 'total': summ['total'], 'branches': summ['branches'],
        'budget': summ['budget'],
        'budget_note': None if whole else 'مقارنة الميزانية للشبكة كلها فقط (بدون فلتر فرع).',
    }))


def _line_out(l):
    return {
        'item_id': l['item_id'], 'itemcode': l['itemcode'], 'name': l['name'], 'branch_code': l['branch_code'],
        'branch_name': l['branch_name'], 'tier': l['tier'], 'rate': float(l['rate']),
        'sales_value': float(l['sales_value']), 'stock': float(l['stock']), 'transit': float(l['transit']),
        'cover_months': None if l['cover_months'] is None else float(l['cover_months']),
        'target_months': float(l['target_months']), 'target_qty': float(l['target_qty']), 'need_qty': l['need_qty'],
        'cost': float(l['cost']), 'stock_value': float(l['stock_value']), 'need_value': float(l['need_value']),
        'excess_value': float(l['excess_value']), 'no_cost': l['no_cost'], 'at_zero': l['at_zero'],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, COVER_READ])
def cover_tiers_lines(request):
    qp = request.query_params
    report, _whole = _report(request)
    lines = report['lines']
    tiers = set(multi_values(qp, 'tier'))
    if tiers:
        lines = [l for l in lines if l['tier'] in tiers]
    if qp.get('need') in ('1', 'true'):
        lines = [l for l in lines if l['need_qty'] > 0]
    if qp.get('q'):
        q = qp['q'].strip().lower()
        lines = [l for l in lines if q in l['name'].lower() or q in l['itemcode'].lower()]
    out = [_line_out(l) for l in lines]
    try:
        key, desc = parse_ordering(qp.get('ordering'), LINE_ORDERS)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    if key:
        out = sort_items(out, lambda l: l.get(key), desc)            # ALL lines, before paging
    else:
        out.sort(key=lambda l: (-l['need_value'], l['itemcode'], l['branch_code']))
    if qp.get('format') == 'xlsx':
        return _excel(out, report)                                   # the export is never paged
    try:
        size = max(1, min(int(qp.get('page_size', PAGE_SIZE)), MAX_PAGE_SIZE))
        page = max(1, int(qp.get('page', 1)))
    except ValueError:
        size, page = PAGE_SIZE, 1
    pages = max(1, -(-len(out) // size))
    page = min(page, pages)
    return Response({'lines': out[(page - 1) * size: page * size], 'count': len(out), 'page': page,
                     'pages': pages, 'page_size': size, 'run': _run_info(report['run'])})


def build_workbook(lines, report):
    """Summary sheet (per tier, per branch × tier) + every line. Branch names, never a bare code."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    fill = PatternFill('solid', fgColor='022871')
    bold_white = Font(bold=True, color='FFFFFF')

    def header(ws, cols):
        ws.append([c for c, _ in cols])
        for i, (_, w) in enumerate(cols, start=1):
            cell = ws.cell(row=ws.max_row, column=i)
            cell.font, cell.fill = bold_white, fill
            ws.column_dimensions[cell.column_letter].width = w

    run = report['run']
    keep = {(x['item_id'], x['branch_code']) for x in lines}          # the summary = the lines exported
    summ = CT.summarize({'settings': report['settings'],
                         'lines': [l for l in report['lines'] if (l['item_id'], l['branch_code']) in keep]})
    ws = wb.active
    ws.title = 'ملخص'
    ws.sheet_view.rightToLeft = True
    ws.append([f'التغطية حسب الفئة — تشغيل المحرك {run.pk if run else "—"}'
               f' ({run.calc_date if run and run.calc_date else ""}) — للاسترشاد فقط'])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append([])
    header(ws, [('الفئة', 26), ('عدد', 9), ('قيمة البيع/شهر', 16), ('قيمة الرصيد (تكلفة)', 18),
                ('تكلفة البيع/شهر', 16), ('التغطية الحالية (شهر)', 14), ('الهدف (شهر)', 12),
                ('الكاش المطلوب', 16), ('فوق الهدف (قيمة)', 16), ('أصناف رصيدها صفر', 14)])
    for t in CT.TIERS:
        a = summ['tiers'][t]
        ws.append([CT.TIER_AR[t], a['lines'], float(a['sales_value']), float(a['stock_value']),
                   float(a['monthly_cost']), _f(a['cover_months']), float(a['target_months']),
                   float(a['need_value']), float(a['excess_value']), a['at_zero']])
    tot = summ['total']
    ws.append(['الإجمالي', tot['lines'], float(tot['sales_value']), float(tot['stock_value']),
               float(tot['monthly_cost']), _f(tot['cover_months']), None, float(tot['need_value']),
               float(tot['excess_value']), tot['at_zero']])
    ws.append([])
    header(ws, [('الفرع', 26), ('الفئة', 9), ('عدد', 16), ('قيمة الرصيد (تكلفة)', 18), ('تكلفة البيع/شهر', 16),
                ('التغطية الحالية (شهر)', 14), ('الكاش المطلوب', 12), ('فوق الهدف (قيمة)', 16)])
    for b in summ['branches']:
        for t in CT.TIERS:
            a = b['tiers'][t]
            ws.append([b['branch_name'], t, a['lines'], float(a['stock_value']), float(a['monthly_cost']),
                       _f(a['cover_months']), float(a['need_value']), float(a['excess_value'])])

    wl = wb.create_sheet('الأسطر')
    wl.sheet_view.rightToLeft = True
    header(wl, [('الصنف', 10), ('الاسم', 34), ('الفرع', 18), ('الفئة', 7), ('المعدل/شهر', 11),
                ('قيمة البيع/شهر', 13), ('الرصيد', 10), ('بالطريق', 9), ('التغطية (شهر)', 11), ('الهدف (شهر)', 10),
                ('كمية الهدف', 11), ('المطلوب (علبة)', 11), ('التكلفة', 10), ('قيمة الرصيد', 12),
                ('الكاش المطلوب', 13), ('فوق الهدف', 12), ('ملاحظات', 16)])
    for l in lines:
        notes = []
        if l['no_cost'] and l['need_qty'] > 0:
            notes.append('بلا تكلفة')
        if l['at_zero']:
            notes.append('الرصيد صفر')
        wl.append([l['itemcode'], l['name'], l['branch_name'], l['tier'], l['rate'], l['sales_value'], l['stock'],
                   l['transit'], l['cover_months'], l['target_months'], l['target_qty'], l['need_qty'], l['cost'],
                   l['stock_value'], l['need_value'], l['excess_value'], ' · '.join(notes)])
    wl.freeze_panes = 'A2'
    return neutralise_formulas(wb)


def _f(v):
    return None if v is None else float(v)


def _excel(lines, report):
    from io import BytesIO
    from django.http import HttpResponse
    buf = BytesIO()
    neutralise_formulas(build_workbook(lines, report)).save(buf)   # the save site itself is neutralised (W-4)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="cover_tiers_{timezone.localdate().isoformat()}.xlsx"'
    return resp
