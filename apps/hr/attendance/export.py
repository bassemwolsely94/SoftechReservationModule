"""
apps/hr/attendance/export.py — the monthly attendance workbook (display only, no money).

Day and total figures come from ``days.month_rows`` — the same function the month screen uses — so
the file and the screen cannot disagree. Sheets are right-to-left; typed text (names, machine
names) is written as text, never as a formula.
"""
from openpyxl import Workbook

from core.export_safety import neutralise_formulas

from . import compare
from . import days as day_engine
from . import issues as issue_list

SUMMARY, DAILY, REVIEW = 'الملخص الشهري', 'يوم بيوم', 'بنود للمراجعة'
KIND_LABEL = {
    'unknown_id': 'رقم غير معروف', 'conflict': 'تعارض أسماء', 'held': 'موظف موقوف',
    'bad_date': 'تاريخ غير صالح', 'drift': 'انحراف ساعة الجهاز',
    'outside_dates': 'بصمات خارج فترة العمل', 'ignored_ids': 'أرقام مستبعدة',
}


STATUS_LABEL = {'active': 'على رأس العمل', 'left': 'ترك العمل'}
SOURCE_LABEL = {'lg': 'لينكد جيتس', 'ours': 'نظامنا'}
LG_HEAD = ['أيام لينكد جيتس', 'ساعات لينكد جيتس']
LG_MACHINES, LG_DAYS = 'البصمات حسب الماكينة', 'أيام مختلفة'


def _leave_text(info):
    return '، '.join(i['label'] for i in info if i.get('label'))


def _branch(emp):
    return (emp.branch.name_ar or emp.branch.name) if emp.branch else ''


def _num(value):
    return float(value) if value is not None else None


def _hhmm(at):
    return at.strftime('%H:%M') if at else ''


def _sheet(wb, title, head):
    ws = wb.create_sheet(title)
    ws.sheet_view.rightToLeft = True
    ws.append(head)
    ws.freeze_panes = 'A2'
    return ws


def _review_row(r):
    kind = r['kind']
    code = r.get('user_code', '')
    if kind == 'unknown_id':
        detail = f"عدد البصمات {r['count']}، آخر بصمة {r['last_punch'] or '-'}"
        machines = '، '.join(r['machines'])
        names = '، '.join(r['roster_names'])
    elif kind == 'conflict':
        detail = 'الأجهزة تحمل أسماء مختلفة لنفس الرقم'
        machines = '، '.join(sorted({m['machine'] for m in r['by_machine']}))
        names = '، '.join(r['names'])
    elif kind == 'held':
        detail = f"بصمات محتجزة {r['count']}" + (f"، {r['reason']}" if r.get('reason') else '')
        machines, names = '', r['name']
    elif kind == 'bad_date':
        detail = f"عدد البصمات {r['count']}، من {r['oldest']} إلى {r['newest']}"
        machines, names = r['machine'], ''
    elif kind == 'outside_dates':
        detail = (f"عدد البصمات {r['count']}، من {r['oldest']} إلى {r['newest']}، "
                  f"فترة العمل من {r.get('start_date') or '-'} إلى {r.get('end_date') or '-'}")
        machines, names = '', r['name']
    elif kind == 'drift':
        detail = f"فرق الساعة {r['seconds']} ثانية"
        machines, names = r['machine'], ''
    else:   # a kind this file doesn't know yet still gets a row instead of failing the export
        detail, machines, names = str(r.get('detail', '')), str(r.get('machine', '')), str(r.get('name', ''))
    return [KIND_LABEL.get(kind, kind), code, names, machines, detail]


def build_workbook(year, month, status=None) -> Workbook:
    from apps.hr.models import Employee

    qs = Employee.objects.select_related('branch')
    if status in ('active', 'left'):
        qs = qs.filter(status=status)
    # deliberately uncapped (the month screen caps at 1000 rows): the file must not hide anyone
    results = day_engine.month_rows(qs.order_by('hr_number'), year, month, with_leave=True)

    wb = Workbook()
    wb.remove(wb.active)

    head = ['رقم الموظف', 'الاسم', 'القسم', 'الوظيفة', 'الفرع', 'الحالة']
    ours_head = ['أيام بها بصمات', 'ساعات العمل', 'الساعات المتوقعة', 'أيام تحتاج مراجعة', 'بدون بصمات']
    lg_on = compare.lg_enabled()
    official = compare.official_source()
    lg_totals = compare.lg_month_totals([e for e, _r, _t in results], year, month) if lg_on else {}
    if lg_on:
        # during the trial both sources show; «المعتمد» (the official hours) is the first figure
        head += [f'المعتمد: ساعات {SOURCE_LABEL[official]}'] + ours_head + LG_HEAD
    else:
        head += ours_head
    ws = _sheet(wb, SUMMARY, head)
    for e, _rows, t in results:
        row = [e.hr_number, e.name_ar, e.department, e.job_title, _branch(e), STATUS_LABEL.get(e.status, e.status)]
        ours = [t.days_with_punches, _num(t.worked_hours), _num(t.expected_hours), t.days_needing_review,
                t.days_no_punches]
        if lg_on:
            lg = lg_totals.get(e.pk) or {'days_with_punches': 0, 'worked_hours': None}
            lg_hours = _num(lg['worked_hours'])
            row += [lg_hours if official == 'lg' else _num(t.worked_hours)] + ours + [
                lg['days_with_punches'], lg_hours]
        else:
            row += ours
        ws.append(row)

    ws = _sheet(wb, DAILY, [
        'رقم الموظف', 'الاسم', 'الفرع', 'التاريخ', 'أول بصمة', 'آخر بصمة', 'دقائق العمل',
        'عدد البصمات', 'الأجهزة', 'الحالة', 'إجازة / إذن'])
    for e, rows, _t in results:
        for d in rows:
            state = 'بدون بصمات' if d.no_punches else ('يحتاج مراجعة' if d.needs_review else '')
            ws.append([e.hr_number, e.name_ar, _branch(e), d.work_date, _hhmm(d.first_in),
                       _hhmm(d.last_out), d.worked_minutes, d.punch_count, '، '.join(d.machines), state,
                       _leave_text(d.info)])
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].number_format = 'yyyy-mm-dd'

    ws = _sheet(wb, REVIEW, ['النوع', 'الرقم', 'الاسم', 'الأجهزة', 'التفاصيل'])
    for r in issue_list.list_issues():
        ws.append(_review_row(r))
    ignored = issue_list.ignored_ids()
    if ignored:    # set aside by a person; their punches are in no total, so the file says so
        ws.append([KIND_LABEL['ignored_ids'], '', '', '',
                   f'عدد الأرقام المستبعدة بقرار: {len(ignored)}'])

    return neutralise_formulas(wb)


def _minutes_hm(minutes):
    if minutes is None:
        return ''
    sign = '-' if minutes < 0 else ''
    minutes = abs(minutes)
    return f'{sign}{minutes // 60}:{minutes % 60:02d}'


def build_lg_compare_workbook(year, month) -> Workbook:
    """The Linked Gates trial comparison (design 2026-11-20 §5.4): punches per machine and day by
    category, then the employee-days whose figures differ with the reasons in plain words. The same
    engine as the screen (compare.py); display only."""
    from apps.hr.models import Employee

    employees = list(Employee.objects.order_by('hr_number'))      # uncapped: the file hides no one
    by_id = {e.pk: e for e in employees}
    cat = compare.CATEGORY_LABELS

    wb = Workbook()
    wb.remove(wb.active)
    ws = _sheet(wb, LG_MACHINES, ['التاريخ', 'الماكينة'] + [cat[c]['ar'] for c in compare.CATEGORIES])
    for r in compare.machine_day_counts(year, month):
        ws.append([r['date'], r['name']] + [r[c] for c in compare.CATEGORIES])
    for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
        row[0].number_format = 'yyyy-mm-dd'

    official = compare.official_source()
    lg_cols = ['حضور لينكد جيتس', 'انصراف لينكد جيتس', 'دقائق لينكد جيتس']
    our_cols = ['حضور نظامنا', 'انصراف نظامنا', 'دقائق نظامنا']
    first, second = (lg_cols, our_cols) if official == 'lg' else (our_cols, lg_cols)
    first = [f'{first[0]} (المعتمد)'] + first[1:]
    ws = _sheet(wb, LG_DAYS, ['رقم الموظف', 'الاسم', 'التاريخ'] + first + second + ['الفرق', 'السبب'])
    for d in compare.compare_month(employees, year, month):
        e = by_id[d['employee_id']]
        lg = [_hhmm(d['lg']['in']), _hhmm(d['lg']['out']), d['lg']['minutes']]
        ours = [_hhmm(d['ours']['in']), _hhmm(d['ours']['out']), d['ours']['minutes']]
        a, b = (lg, ours) if official == 'lg' else (ours, lg)
        reasons = '، '.join(compare.REASON_LABELS.get(c, {}).get('ar', c) for c in d['reasons'])
        ws.append([e.hr_number, e.name_ar, d['date']] + a + b + [
            _minutes_hm(d['ours']['minutes'] - d['lg']['minutes']), reasons or compare.NO_REASON_LABEL['ar']])
    for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].number_format = 'yyyy-mm-dd'
    return neutralise_formulas(wb)
