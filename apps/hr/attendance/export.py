"""
apps/hr/attendance/export.py — the monthly attendance workbook (display only, no money).

Day and total figures come from ``days.month_rows`` — the same function the month screen uses — so
the file and the screen cannot disagree. Sheets are right-to-left; typed text (names, machine
names) is written as text, never as a formula.
"""
from openpyxl import Workbook

from core.export_safety import neutralise_formulas

from . import days as day_engine
from . import issues as issue_list

SUMMARY, DAILY, REVIEW = 'الملخص الشهري', 'يوم بيوم', 'بنود للمراجعة'
KIND_LABEL = {
    'unknown_id': 'رقم غير معروف', 'conflict': 'تعارض أسماء', 'held': 'موظف موقوف',
    'bad_date': 'تاريخ غير صالح', 'drift': 'انحراف ساعة الجهاز',
    'outside_dates': 'بصمات خارج فترة العمل', 'ignored_ids': 'أرقام مستبعدة',
}


STATUS_LABEL = {'active': 'على رأس العمل', 'left': 'ترك العمل'}


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

    ws = _sheet(wb, SUMMARY, [
        'رقم الموظف', 'الاسم', 'القسم', 'الوظيفة', 'الفرع', 'الحالة', 'أيام بها بصمات', 'ساعات العمل',
        'الساعات المتوقعة', 'أيام تحتاج مراجعة', 'بدون بصمات'])
    for e, _rows, t in results:
        ws.append([e.hr_number, e.name_ar, e.department, e.job_title, _branch(e), STATUS_LABEL.get(e.status, e.status),
                   t.days_with_punches, _num(t.worked_hours), _num(t.expected_hours),
                   t.days_needing_review, t.days_no_punches])

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
