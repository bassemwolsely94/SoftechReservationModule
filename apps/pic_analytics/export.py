"""
apps/pic_analytics/export.py — the audited Excel workbook (doc 33 §9).

One sheet per tab, built from the SAME query functions the screen uses (so the file can never
disagree with the screen and can never show more than the user may see), plus the «الفلاتر
والتعريفات» sheet first. RTL, frozen navy header (022871), branch labels «code · name».
Write-only workbook, large lists read page by page. Branch managers get no cost / GP columns and
no calls sheets — the query layer omits those keys and the column lists below skip them too.
"""
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django.utils import timezone

from core.export_safety import neutralise_formulas, safe_sheet

from .queries import groups, missed, numbers, overview as ov, pics, retention
from .queries.calls import call_center
from .queries.groups import CHANNEL_LABELS

PAGE = 200
S_FILTERS = 'الفلاتر والتعريفات'
S_OVERVIEW = 'نظرة عامة'
S_PICS = 'العملاء'
S_BRANCH, S_SALES, S_CHANNEL, S_CATEGORY = 'الفروع', 'البائعون', 'القنوات', 'الأصناف'
S_LOYALTY = 'الولاء والتكرار'
S_CENTER, S_MISSED, S_NUMBERS = 'مركز الاتصال', 'المكالمات الفائتة', 'أرقام جديدة'

DEFINITIONS = [
    'الفترة: من/إلى شاملة، بتوقيت القاهرة. البيانات تبدأ من 2024-08-01.',
    'الزيارة: فواتير العميل (PIC) في نفس اليوم تُحسب زيارة واحدة؛ عدد الفواتير يظهر منفصلاً.',
    'زيارة نفس اليوم في فرعين = زيارة لكل فرع وزيارة واحدة على مستوى السلسلة، لذلك قد يزيد مجموع الفروع عن الإجمالي.',
    'المرتجعات: تُخصم من صافي يوم الارتجاع، ولا تُعد زيارة ولا تغيّر تاريخ أول شراء.',
    'مبيعات بدون PIC: لا تدخل في عدّ العملاء وتظهر كسطر منفصل في النظرة العامة.',
    'القناة: نفس تصنيف لوحة KPI (ChannelBucketMap).',
    'عميل جديد: أول شراء له في الفترة وتاريخ فتح حسابه في SOFTECH ليس أقدم من بداية الفترة بأكثر من 30 يوماً.',
    'عميل عائد: اشترى في الفترة وليس جديداً. معاد التنشيط: عائد وكان شراؤه السابق قبل 12 شهراً أو أكثر.',
    'نسبة (أ): عدد الشهور المختلفة التي فيها زيارة خلال 12 شهراً حتى تاريخ النهاية. (ب): أطول سلسلة شهور متتالية.',
    'دورة الشراء (ج): متوسط الأيام بين الزيارات (زيارتان فأكثر). متأخر = أيام منذ آخر زيارة أكبر من 1.5 × دورته.',
    'وفيّ: عدد شهور الشراء (أ) 10 فأكثر (قابل للتعديل من الإعدادات).',
    'الاستبقاء: نسبة عملاء الفترة السابقة (بنفس الطول) الذين اشتروا مرة أخرى في هذه الفترة.',
    'السلة: لكل زيارة (وليس لكل فاتورة): الصافي، الوحدات، عدد الأصناف.',
    'التسميات (جديد/عائد/معاد التنشيط) والتكرار على مستوى السلسلة كلها، والمبالغ على فروع المستخدم فقط.',
    'المكالمة الفائتة: واردة لم يردّ عليها أحد. غير المردودة: لا اتصال مجاب بنفس الرقم خلال المهلة (24 ساعة افتراضياً).',
    'الرقم المشترك بين عدة عملاء يُحسب مرة واحدة على آخر عميل اشترى قبل المكالمة.',
    'مكالمات التحويل الداخلية لا تُحسب.',
    'أرقام جديدة: مكالمات من أرقام لا تطابق أي عميل وبلا تصنيف.',
]

# (key, header) per sheet; keys the query layer omits for a branch manager are skipped at write time
OVERVIEW_ITEMS = [
    ('distinct_pics', 'العملاء (PIC)'), ('new', 'جدد'), ('returning', 'عائدون'), ('reactivated', 'معاد تنشيطهم'),
    ('visits', 'الزيارات'), ('invoices', 'الفواتير'), ('net', 'صافي المبيعات'), ('units', 'الوحدات'),
    ('basket_net', 'متوسط صافي السلة'), ('basket_units', 'متوسط وحدات السلة'),
    ('basket_categories', 'متوسط أصناف السلة'), ('visits_per_pic', 'زيارات لكل عميل'),
    ('retention_pct', 'الاستبقاء %'), ('no_pic_net', 'مبيعات بدون PIC'),
    ('gp', 'الربح الإجمالي'), ('gp_pct', 'هامش الربح %'),
    ('calls_in', 'مكالمات واردة'), ('calls_out', 'مكالمات صادرة'), ('missed_not_returned', 'فائتة لم يُردّ عليها'),
]
OVERVIEW_CALL_KEYS = {'calls_in', 'calls_out', 'missed_not_returned'}
MONTH_COLS = [('month', 'الشهر'), ('distinct_pics', 'العملاء'), ('new', 'جدد'), ('visits', 'الزيارات'),
              ('net', 'صافي المبيعات')]
PIC_COLS = [
    ('pic', 'PIC'), ('name', 'الاسم'), ('segment', 'الشريحة'), ('last_branch', 'آخر فرع'), ('phone', 'الهاتف'),
    ('net', 'صافي المبيعات'), ('gp', 'الربح الإجمالي'), ('visits', 'الزيارات'), ('invoices', 'الفواتير'),
    ('units', 'الوحدات'), ('basket_net', 'صافي السلة'), ('categories', 'الأصناف'), ('channels', 'القنوات'),
    ('first_purchase', 'أول شراء'), ('last_purchase', 'آخر شراء'), ('days_since_last', 'أيام منذ آخر شراء'),
    ('months_a', 'شهور الشراء (أ)'), ('streak_b', 'أطول سلسلة (ب)'), ('cycle_bucket', 'دورة الشراء (ج)'),
    ('overdue', 'متأخر'),
    ('calls_in', 'مكالمات واردة'), ('calls_out', 'مكالمات صادرة'), ('missed', 'فائتة'),
    ('last_call', 'آخر مكالمة'), ('talk_time', 'مدة الحديث (ث)'), ('call_to_purchase', 'مكالمة ثم شراء'),
]
PIC_CALL_KEYS = {'calls_in', 'calls_out', 'missed', 'last_call', 'talk_time', 'call_to_purchase'}
GROUP_COLS = [
    ('label', 'البند'), ('distinct_pics', 'العملاء'), ('new', 'جدد'), ('returning', 'عائدون'),
    ('reactivated', 'معاد تنشيطهم'), ('visits', 'الزيارات'), ('net', 'صافي المبيعات'), ('gp', 'الربح الإجمالي'),
    ('basket_net', 'صافي السلة'), ('units_per_visit', 'وحدات لكل زيارة'),
]
CENTER_COLS = [
    ('agent_ext', 'التحويلة'), ('staff_name', 'الموظف'), ('pbx_name', 'اسم السنترال'), ('calls_in', 'واردة'),
    ('calls_out', 'صادرة'), ('answered', 'مجابة'), ('talk_seconds', 'مدة الحديث (ث)'),
    ('pics_reached', 'عملاء تم الوصول لهم'), ('call_to_purchase_pct', 'مكالمة ثم شراء %'),
    ('unanswered_out', 'صادرة بلا رد'), ('avg_attempts_to_reach', 'متوسط المحاولات'), ('not_reached', 'لم يتم الوصول'),
]
MISSED_COLS = [
    ('call_at', 'وقت المكالمة'), ('customer_number', 'الرقم'), ('queue', 'الطابور'), ('pic', 'PIC'),
    ('customer_name', 'الاسم'), ('segment', 'الشريحة'), ('last_purchase', 'آخر شراء'),
    ('lifetime_net', 'صافي المبيعات الكلي'), ('bought_within_7d', 'اشترى خلال 7 أيام'),
    ('returned_at', 'وقت الردّ'), ('minutes_to_return', 'دقائق حتى الردّ'),
]
NUMBER_COLS = [
    ('number', 'الرقم'), ('kind', 'النوع'), ('calls_in', 'واردة'), ('calls_out', 'صادرة'), ('answered', 'مجابة'),
    ('missed', 'فائتة'), ('first_call', 'أول مكالمة'), ('last_call', 'آخر مكالمة'), ('talk_seconds', 'مدة الحديث (ث)'),
    ('last_agent', 'آخر موظف'),
]
KIND_LABELS = {'mobile': 'موبايل', 'landline': 'أرضي'}
GP_KEYS = {'gp', 'gp_pct'}


def filters_dict(f):
    """The active filters as plain JSON (the audit entry and the filters sheet)."""
    return {'from': f.start.isoformat(), 'to': f.end.isoformat(),
            'branch': sorted(f.branch_ids) if f.branch_ids else [], 'salesperson': f.salesperson,
            'agent': f.agent_ext, 'channel': f.channel_bucket, 'category': f.category, 'segment': f.segment,
            'customer_type': f.customer_type, 'frequency': f.frequency,
            'data_from': f.data_from.isoformat(), 'data_to': f.data_to.isoformat(), 'clamped': f.clamped}


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'نعم' if v else 'لا'
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return (timezone.localtime(v) if timezone.is_aware(v) else v).strftime('%Y-%m-%d %H:%M')
    if isinstance(v, (list, tuple, set)):
        return '، '.join(str(x) for x in v)
    if isinstance(v, dict):
        return '، '.join(f'{k}: {x}' for k, x in v.items() if x)
    return v


class _Book:
    def __init__(self):
        import openpyxl
        self.wb = openpyxl.Workbook(write_only=True)
        self.counts = {}

    def sheet(self, title, headers, widths=None):
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Alignment, Font, PatternFill
        ws = safe_sheet(self.wb.create_sheet(title=title))
        ws.sheet_view.rightToLeft = True
        for i, w in enumerate(widths or [], start=1):
            ws.column_dimensions[chr(64 + i)].width = w
        ws.freeze_panes = 'A2'
        fill = PatternFill('solid', fgColor='022871')
        cells = []
        for h in headers:
            c = WriteOnlyCell(ws._ws, value=h)
            c.font, c.fill = Font(bold=True, color='FFFFFF'), fill
            c.alignment = Alignment(horizontal='center')
            cells.append(c)
        ws.append(cells)
        self.counts[title] = 0
        return ws

    def row(self, ws, title, values):
        ws.append([_cell(v) for v in values])
        self.counts[title] += 1

    def table(self, title, cols, rows, widths=None):
        ws = self.sheet(title, [h for _k, h in cols], widths or [18] * len(cols))
        for r in rows:
            self.row(ws, title, [r.get(k) for k, _h in cols])
        return ws


def _all_pages(fn):
    """Rows of every page of a {'count','rows'} query; fn(page) -> that dict."""
    page, out = 1, []
    while True:
        res = fn(page)
        out.extend(res['rows'])
        if not res['rows'] or len(out) >= res['count']:
            return out
        page += 1


def _cols(cols, access, call_keys=()):
    return [(k, h) for k, h in cols
            if (access.sees_cost or k not in GP_KEYS) and (access.sees_calls_tabs or k not in call_keys)]


def build_workbook(f, access, exported_by=''):
    """-> (bytes, {sheet: rows written}). Only called for a user who may export."""
    from apps.branches.models import Branch
    book = _Book()
    branch_names = {b.pk: f'{b.softech_branch_id} · {b.name_ar or b.name}' for b in Branch.objects.all()}

    # 1. filters and definitions
    ws = book.sheet(S_FILTERS, ['البند', 'القيمة'], [34, 90])
    ids = access.allowed_branch_ids(f.branch_ids)
    rows = [
        ('من', f.start.isoformat()), ('إلى', f.end.isoformat()),
        ('الفروع', 'كل الفروع' if ids is None else '، '.join(branch_names.get(i, str(i)) for i in sorted(ids))),
        ('البائع', f.salesperson or 'الكل'),
        ('القناة', CHANNEL_LABELS.get(f.channel_bucket, f.channel_bucket) or 'الكل'),
        ('الصنف', f.category or 'الكل'), ('الشريحة', f.segment or 'الكل'),
        ('نوع العميل', f.customer_type or 'الكل'), ('فئة التكرار', f.frequency or 'الكل'),
        ('تحويلة الموظف', f.agent_ext or 'الكل'),
        ('بيانات متاحة من', f.data_from.isoformat()), ('بيانات متاحة حتى', f.data_to.isoformat()),
        ('الفترة قُصّت على نطاق البيانات', 'نعم' if f.clamped else 'لا'),
        ('تاريخ التصدير', timezone.localtime().strftime('%Y-%m-%d %H:%M')), ('المصدّر', exported_by),
    ]
    for r in rows:
        book.row(ws, S_FILTERS, r)
    book.row(ws, S_FILTERS, ['', ''])
    book.row(ws, S_FILTERS, ['التعريفات', ''])
    for line in DEFINITIONS:
        book.row(ws, S_FILTERS, ['', line])

    # 2. overview
    o = ov.overview(f, access)
    ws = book.sheet(S_OVERVIEW, ['المؤشر', 'القيمة'], [34, 20])
    for key, label in OVERVIEW_ITEMS:
        if key in GP_KEYS and not access.sees_cost:
            continue
        if key in OVERVIEW_CALL_KEYS and not access.sees_calls_tabs:
            continue
        book.row(ws, S_OVERVIEW, [label, o.get(key)])
    book.row(ws, S_OVERVIEW, ['', ''])
    book.row(ws, S_OVERVIEW, [h for _k, h in MONTH_COLS])
    for m in o['by_month']:
        book.row(ws, S_OVERVIEW, [m.get(k) for k, _h in MONTH_COLS])

    # 3. customers (every page)
    cols = _cols(PIC_COLS, access, PIC_CALL_KEYS)
    ws = book.sheet(S_PICS, [h for _k, h in cols], [16, 28] + [16] * (len(cols) - 2))
    for r in _all_pages(lambda p: pics.pic_rows(f, access, '-net', p, PAGE)):
        r = dict(r, last_branch=branch_names.get(r.get('last_branch'), r.get('last_branch')))
        book.row(ws, S_PICS, [r.get(k) for k, _h in cols])

    # 4. groups
    for title, fn in ((S_BRANCH, groups.by_branch), (S_SALES, groups.by_salesperson),
                      (S_CHANNEL, groups.by_channel), (S_CATEGORY, groups.by_category)):
        g = fn(f, access)
        gcols = _cols(GROUP_COLS, access)
        ws = book.table(title, gcols, list(g['rows']) + [dict(g['total'], label='الإجمالي')],
                        [30] + [16] * (len(gcols) - 1))
        if 'cross_category_rate' in g:
            book.row(ws, title, ['نسبة الزيارات من أكثر من صنف', g['cross_category_rate']])

    # 5. loyalty and frequency
    fr = retention.frequency(f, access)
    ws = book.sheet(S_LOYALTY, ['الفئة', 'العملاء'], [34, 16])
    for k, n in fr['a'].items():
        book.row(ws, S_LOYALTY, [f'(أ) {k} شهر', n])
    for k, n in fr['b'].items():
        book.row(ws, S_LOYALTY, [f'(ب) سلسلة {k} شهر', n])
    for k, n in fr['c'].items():
        book.row(ws, S_LOYALTY, [f'(ج) {k or "غير محدد"}', n])
    book.row(ws, S_LOYALTY, ['وفيّ', fr['loyal']])
    book.row(ws, S_LOYALTY, ['متأخر', fr['overdue']])
    book.row(ws, S_LOYALTY, ['الاستبقاء %', retention.retention_summary(f, access)['retention_pct']])
    book.row(ws, S_LOYALTY, ['', ''])
    book.row(ws, S_LOYALTY, ['شهر أول شراء', 'الحجم'] + [f'بعد {k} شهر %' for k in range(1, 13)])
    for c in retention.cohorts(f, access):
        book.row(ws, S_LOYALTY, [c['cohort'], c['size']] + list(c['months']))

    # 6. management only: calls
    if access.sees_calls_tabs:
        cc = call_center(f, access)
        ws = book.table(S_CENTER, CENTER_COLS, cc['rows'], [10, 24, 24] + [16] * 9)
        book.row(ws, S_CENTER, ['', 'عملاء جدد باعتهم الفريق', '', cc['team_new_pics_sold']])
        book.table(S_MISSED, MISSED_COLS,
                   _all_pages(lambda p: missed.missed_rows(f, access, False, p, PAGE)),
                   [20, 18, 14, 14, 26] + [16] * 6)
        rows = []
        for r in _all_pages(lambda p: numbers.new_numbers(f, access, p, PAGE)):
            agent = r.get('last_agent') or {}
            rows.append(dict(r, kind=KIND_LABELS.get(r['kind'], r['kind']),
                             last_agent=agent.get('staff_name') or agent.get('pbx_name') or agent.get('agent_ext', '')))
        book.table(S_NUMBERS, NUMBER_COLS, rows, [18] + [16] * 9)

    buf = BytesIO()
    neutralise_formulas(book.wb).save(buf)
    return buf.getvalue(), book.counts
