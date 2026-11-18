"""
apps/crews/cc_comparison.py

Old-vs-crew comparison for the call center (crews piece 2b, Task 3) — what the owner signs off
before any incentive / target / KPI figure moves from the fake «CC» branch to the call-center
crew (money gate). It READS only; it writes no money figure and nothing at all except, with
compare_seeded_in_transaction, a crew seed that is rolled back before it returns.

Per month x KPI three figures:
  stored  = the CC branch's KpiActualRollup row (what the KPI board shows today)
  old_now = the old rule recomputed now: KpiResolver.compute_call_center_month over the
            CallCenterConfig usercodes, minus cc_returns_from_softech, + count_calls over the
            CallCenterConfig extensions
  crew    = apps.crews.kpi.compute_crew_month (dated member identities)
and one reason code per row (REASONS; priority in _reason). Also per person (old per config code
vs crew per member), per CC SalesTarget, the CC ForecastResult rows, per invoice branch, and the
questions only the owner can answer.

A figure that cannot be computed (SOFTECH / CDR unreachable) is None — «غير محسوب» — never 0.
SOFTECH reads only through cc_softech / softech_returns (config.sybase); CDR through config.issabel.
"""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.forecasting.call_center import LEGACY_CC_KEY, legacy_cc_branch
from apps.forecasting.callcount import count_calls
from apps.forecasting.cc_softech import cc_returns_from_softech
from apps.forecasting.kpi import KpiResolver
from config.issabel import cdr_configured, fetch_cdr_rows

from . import kpi as crew_kpi
from .membership import identities
from .unattributed import branch_label, generic_rule, is_generic

METRICS = ['cash_delivery', 'gross_profit', 'beauty', 'customer_count', 'pic_count', 'call_count']
MONEY_METRICS = ('cash_delivery', 'gross_profit', 'beauty')
RETURN_METRICS = ('cash_delivery', 'gross_profit')          # the two the SOFTECH returns adjust
SALES_METRICS = ('cash_delivery', 'gross_profit', 'beauty', 'customer_count', 'pic_count')
CALL_METRIC = 'call_count'
TOL = Decimal('0.01')
NOT_COMPUTED = 'غير محسوب'
GENERIC_LABEL = 'بائع غير محدد'

METRIC_LABELS = {
    'cash_delivery': 'المبيعات (صافي)', 'gross_profit': 'الربحية', 'beauty': 'التجميل',
    'customer_count': 'عدد الطلبات', 'pic_count': 'عدد العملاء (PIC)',
    'call_count': 'عدد المكالمات',
}
# distinct counts: a customer (PIC) / mobile two people served counts once for each of them
NOT_ADDITIVE_PER_PERSON = ('pic_count', 'call_count')
PIC_NOT_ADDITIVE = ('عدد العملاء (PIC) وعدد المكالمات لكل شخص غير تجميعي: عميل أو رقم خدمه شخصان '
                    'يُعد عند كل منهما، فمجموع الأشخاص قد يزيد عن رقم الطاقم.')

REASONS = {
    'same': {'ar': 'مطابق', 'en': 'Same: crew = stored = old rule now'},
    'drift_since_build': {'ar': 'تغيّرت بيانات المبيعات/المرتجعات منذ بناء الرقم القديم',
                          'en': 'Sales/returns data changed since the stored figure was built'},
    'membership': {'ar': 'اختلاف أعضاء الطاقم عن أكواد الإعداد',
                   'en': 'Crew members differ from the CallCenterConfig codes'},
    'returns_unreachable': {'ar': 'لم يُحسب خصم المرتجعات (SOFTECH غير متاح)',
                            'en': 'Returns not deducted (SOFTECH unreachable)'},
    'cdr_unavailable': {'ar': 'عدد المكالمات غير قابل لإعادة الحساب هنا (CDR غير متاح) — القيمة المخزنة فقط',
                        'en': 'Call count cannot be recomputed here (no CDR) — stored value only'},
    'return_before_membership': {'ar': 'مرتجع لبيع سابق لبداية العضوية',
                                 'en': 'A return of a sale made before the membership began'},
    'no_stored_value': {'ar': 'لا يوجد رقم مخزن قديم', 'en': 'No stored old figure'},
}


# ── small helpers ───────────────────────────────────────────────────────────────

def _months(start, end) -> list:
    (y, m), out = start, []
    while (y, m) <= tuple(end):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _month_range(y, m):
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return date(y, m, 1), nxt


def _f(v):
    return None if v is None else float(round(Decimal(str(v)), 2))


def _diff(a, b):
    return None if a is None or b is None else _f(Decimal(str(a)) - Decimal(str(b)))


def _close(a, b) -> bool:
    return a is not None and b is not None and abs(Decimal(str(a)) - Decimal(str(b))) < TOL


def _key_str(key) -> str:
    return f'{key[0]}:{key[1]}'


# ── one month, old rule ─────────────────────────────────────────────────────────

def _cdr_rows(y, m, cdr_rows_by_month):
    """(rows | None, note | None) — one fetch per month, shared by the old rule and the crew."""
    if cdr_rows_by_month is not None:
        rows = cdr_rows_by_month.get((y, m))
        return (list(rows), None) if rows is not None else (None, crew_kpi.NOTE_CDR_UNAVAILABLE)
    if not cdr_configured():
        return None, crew_kpi.NOTE_CDR_UNAVAILABLE
    try:
        return list(fetch_cdr_rows(*_month_range(y, m))), None
    except Exception:       # PBX unreachable: not computed, never zero
        return None, crew_kpi.NOTE_CDR_UNREACHABLE


def _old_sales(resolver, y, m, codes, returns) -> dict:
    """{'gross', 'net', 'returns_failed'} of the old rule for these usercodes."""
    if not codes:       # compute_call_center_month falls back to the config on an empty list
        zero = {k: Decimal('0') for k in SALES_METRICS}
        return {'gross': zero, 'net': dict(zero), 'returns': None, 'returns_failed': False}
    gross = resolver.compute_call_center_month(y, m, list(codes))
    net, ret, failed = dict(gross), None, False
    if returns:
        try:
            ret = cc_returns_from_softech(y, m, list(codes))
        except Exception:   # SOFTECH unreachable: marked, never zeroed
            failed = True
        else:
            net['cash_delivery'] = net['cash_delivery'] - ret['amount']
            net['gross_profit'] = net['gross_profit'] - ret['profit']
    return {'gross': gross, 'net': net, 'returns': ret, 'returns_failed': failed}


# ── reason per month row ───────────────────────────────────────────────────────

def _reason(metric, stored, old_now, crew, *, cdr_missing, returns_missing, gross_equal) -> str:
    if stored is None:
        return 'no_stored_value'
    if metric == CALL_METRIC and cdr_missing:
        return 'cdr_unavailable'
    if metric in RETURN_METRICS and returns_missing:
        return 'returns_unreachable'
    if _close(crew, stored) and _close(old_now, stored):
        return 'same'
    if metric in RETURN_METRICS and gross_equal and not _close(old_now, crew):
        return 'return_before_membership'
    if not _close(old_now, crew):
        return 'membership'       # drift may apply too: both diffs stay visible on the row
    return 'drift_since_build'


# ── people ──────────────────────────────────────────────────────────────────────

class _Labeller:
    def __init__(self, crew):
        from apps.hr.models import Employee
        from apps.users.models import ERPUser
        self.rule = generic_rule()
        self.group_of = dict(ERPUser.objects.values_list('username', 'user_group'))
        rows = list(crew.manual_members.filter(voided_at__isnull=True)) if crew else []
        self.code_label = {r.softech_usercode: r.label for r in rows if r.softech_usercode and r.label}
        self.ext_label = {r.pbx_extension: r.label for r in rows if r.pbx_extension and r.label}
        emp_ids = {r.employee_id for r in rows if r.employee_id}
        self.emp_name = dict(Employee.objects.filter(id__in=emp_ids).values_list('id', 'name_ar'))

    def _emp(self, emp_id):
        if emp_id not in self.emp_name:
            from apps.hr.models import Employee
            self.emp_name[emp_id] = (Employee.objects.filter(id=emp_id)
                                     .values_list('name_ar', flat=True).first() or f'موظف {emp_id}')
        return self.emp_name[emp_id]

    def label(self, key, codes) -> tuple:
        """(label, generic). A member any of whose seller codes is generic is «بائع غير محدد»."""
        generic = any(is_generic(c, self.rule, self.group_of) for c in codes)
        if generic:
            return GENERIC_LABEL, True
        kind, value = key
        if kind == 'emp':
            return self._emp(value), False
        if kind == 'code':
            return self.code_label.get(value) or f'مندوب {value}', False
        return self.ext_label.get(value) or f'داخلي {value}', False


def _people_rows(y, m, crew_month, ids, *, old_for, cfg_codes, cfg_exts, cdr_rows, labeller,
                 returns_missing) -> list:
    """Per member: crew figures vs the old rule over the member's identities that are in
    CallCenterConfig (computed for the member's codes together, so distinct counts stay
    distinct). Config codes / extensions no member carries get their own row, crew 0."""
    codes_of, exts_of = defaultdict(set), defaultdict(set)
    for i in ids:
        if i.kind == 'softech_user':
            codes_of[i.member_key].add(i.value)
        elif i.kind == 'extension':
            exts_of[i.member_key].add(i.value)
    keys = list(crew_month.per_member)
    carried_codes = set().union(*codes_of.values()) if codes_of else set()
    carried_exts = set().union(*exts_of.values()) if exts_of else set()
    keys += [('code', c) for c in cfg_codes if c not in carried_codes]
    keys += [('ext', x) for x in cfg_exts if x not in carried_exts]
    out = []
    for key in keys:
        in_crew = key in crew_month.per_member
        codes = codes_of.get(key, {key[1]} if key[0] == 'code' else set())
        exts = exts_of.get(key, {key[1]} if key[0] == 'ext' else set())
        label, generic = labeller.label(key, codes)
        if not in_crew:
            label = f'{label} (ليس في الطاقم)'
        crew_vals = crew_month.per_member.get(key, {})
        old_sales = old_for(tuple(sorted(c for c in codes if c in cfg_codes)))
        member_exts = [x for x in sorted(exts) if x in cfg_exts]
        for metric in METRICS:
            if metric == CALL_METRIC:
                if cdr_rows is None:
                    old = crew = None
                else:
                    old = count_calls(cdr_rows, member_exts) if member_exts else 0
                    crew = crew_vals.get(metric, 0) if in_crew else 0
            elif metric in RETURN_METRICS and (returns_missing or old_sales['returns_failed']):
                old = crew = None
            else:
                old = old_sales['net'][metric]
                crew = crew_vals.get(metric, 0) if in_crew else 0
            out.append({'year': y, 'month': m, 'member_key': _key_str(key), 'label': label,
                        'generic': generic, 'metric': metric, 'old': _f(old), 'crew': _f(crew),
                        'diff': _diff(crew, old)})
    return out


# ── targets / forecasts / branches ──────────────────────────────────────────────

def _targets(cc, stored, crew_values) -> list:
    from apps.forecasting import kpi_board
    from apps.incentives.models import SalesTarget
    if cc is None:
        return []
    out = []
    for t in SalesTarget.objects.filter(scope_type=SalesTarget.SCOPE_BRANCH, branch=cc).order_by(
            'period_start', 'metric', 'id'):
        months = _months((t.period_start.year, t.period_start.month),
                         (t.period_end.year, t.period_end.month))
        board = sum((stored.get((y, m, t.metric), 0) for y, m in months), Decimal('0'))
        crew_parts = [crew_values.get((y, m, t.metric)) for y, m in months]
        crew = None if any(v is None for v in crew_parts) else sum(
            (Decimal(str(v)) for v in crew_parts), Decimal('0'))
        target = float(t.target_value or 0)
        row = {'target_id': t.pk, 'metric': t.metric,
               'period': f'{t.period_start.isoformat()} → {t.period_end.isoformat()}',
               'target': _f(target), 'achieved_board': _f(board),
               'achieved_salestarget_today': _f(t.actual_value()), 'achieved_crew': _f(crew),
               'pct_board': None, 'pct_crew': None, 'pace_board': None, 'pace_crew': None}
        if len(months) == 1:        # the board's own to-date % and pace (kpi_board)
            _s, m_end, through, _t, _e, frac = kpi_board.month_pacing(*months[0])
            for name, a in (('board', board), ('crew', crew)):
                if a is not None:
                    cell = kpi_board.make_cell(float(a), target, None, through, m_end, frac)
                    row[f'pct_{name}'], row[f'pace_{name}'] = cell['pct'], cell['pace']
        else:
            for name, a in (('board', board), ('crew', crew)):
                if a is not None and target:
                    row[f'pct_{name}'] = round(float(a) / target * 100, 1)
        out.append(row)
    return out


def _forecasts() -> list:
    from apps.forecasting.models import ForecastResult
    qs = (ForecastResult.objects.filter(scope_key=LEGACY_CC_KEY).select_related('scenario')
          .order_by('scenario__year', 'scenario__month', 'scenario_id', 'metric'))
    return [{'scenario_id': r.scenario_id,
             'scenario': f'{r.scenario.name} ({r.scenario.year}-{r.scenario.month:02d})',
             'metric': r.metric, 'forecast': _f(r.forecast_value), 'target': _f(r.target_value)}
            for r in qs]


def _branch_sales(resolver, months, codes, crew) -> list:
    """Gross net-of-doc-30 sales (mirror only, before SOFTECH returns) per invoice branch over the
    whole range, old codes vs crew spans. Live branches always listed; any other branch with
    sales listed too so nothing drops."""
    from apps.branches.models import Branch

    from .branches import live_branches

    def by_branch(qs):
        out = defaultdict(Decimal)
        for r in qs.filter(doc_code__in=['115', '30']).values('branch_id', 'doc_code').annotate(
                s=Sum('total_amount')):
            v = r['s'] or Decimal('0')
            out[r['branch_id']] += v if r['doc_code'] == '115' else -v
        return out

    old, new = defaultdict(Decimal), defaultdict(Decimal)
    for y, m in months:
        start, end = resolver.month_bounds(y, m)
        if codes:
            for b, v in by_branch(resolver._ph_qs(None, start, end, softech_user=list(codes))).items():
                old[b] += v
        spans = crew_kpi.seller_spans(crew, start, end) if crew else []
        if spans:
            for b, v in by_branch(resolver._ph_qs(None, start, end)
                                  .filter(crew_kpi.sales_q(spans))).items():
                new[b] += v
    branches = {b.id: b for b in live_branches()}
    missing = (set(old) | set(new)) - set(branches) - {None}
    if missing:
        branches.update({b.id: b for b in Branch.objects.filter(id__in=missing)})
    rows = [{'branch_id': bid, 'label': branch_label(b), 'old': _f(old.get(bid, 0)),
             'crew': _f(new.get(bid, 0)), 'diff': _diff(new.get(bid, 0), old.get(bid, 0))}
            for bid, b in branches.items()]
    return sorted(rows, key=lambda r: (-(r['old'] or 0), r['label']))


# ── questions ───────────────────────────────────────────────────────────────────

def _questions(targets, *, cdr_from_csv) -> list:
    from apps.incentives.models import SalesTarget

    from .cc_seed import extra_pbx_agent_extensions
    extra = extra_pbx_agent_extensions()
    qs = [
        ('داخليات PBX من نوع «agent» غير مدرجة في إعداد الكول سنتر: '
         + (', '.join(extra) if extra else 'لا يوجد حالياً')
         + ' — هل تُضم للطاقم؟ ضمّها يغيّر عدد المكالمات التاريخي.'),
        ('الأرقام التاريخية للكول سنتر: تُنقل قيمةً بقيمة كما هي مخزنة (value-for-value، كما في '
         'المواصفات) أم يُعاد بناؤها من أرقام الطاقم؟'),
    ]
    resolver_targets = [t for t in targets if t['metric'] in SalesTarget.KPI_RESOLVER_METRICS]
    qs.append(
        f'ملاحظة: SalesTarget.actual_value() يقرأ صفراً لمستهدفات الكول سنتر المحسوبة بمحرك المؤشرات '
        f'({len(resolver_targets)} في هذا التقرير) لأنه يبحث عن فواتير الفرع الوهمي «CC»، بينما تعرض '
        f'لوحة المؤشرات رقم الـ rollup. أي رقم يُعتمد للحافز بعد النقل للطاقم؟')
    if cdr_from_csv:
        qs.append('عدد المكالمات من ملف CDR CSV: الطاقم يعدّ فقط صفوف أيام العضوية، بينما المسار '
                  'القديم للـ CSV كان يعدّ كل صفوف الملف — هل الملف لشهر واحد فقط؟')
    return qs


# ── the comparison ──────────────────────────────────────────────────────────────

def compare(crew, start, end, *, returns=True, cdr_rows_by_month=None, cdr_from_csv=False) -> dict:
    """See the module docstring. start / end = (year, month) inclusive. cdr_rows_by_month =
    {(y, m): rows} replaces the live CDR (a month missing from it = CDR unavailable)."""
    from apps.forecasting.models import CallCenterConfig, KpiActualRollup
    cfg = CallCenterConfig.get_solo()
    codes = [str(c).strip() for c in cfg.sales_agent_usercodes or [] if str(c).strip()]
    exts = [str(e).strip() for e in cfg.call_agent_extensions or [] if str(e).strip()]
    months = _months(start, end)
    resolver = KpiResolver()
    labeller = _Labeller(crew)
    cc = legacy_cc_branch()
    stored = {}
    if cc is not None:
        for r in KpiActualRollup.objects.filter(branch=cc, metric__in=METRICS).values(
                'year', 'month', 'metric', 'value'):
            stored[(r['year'], r['month'], r['metric'])] = r['value']

    month_rows, people, crew_values = [], [], {}
    for y, m in months:
        rows, cdr_note = _cdr_rows(y, m, cdr_rows_by_month)
        cdr_missing = rows is None
        old = _old_sales(resolver, y, m, codes, returns)
        old_calls = None if cdr_missing else count_calls(rows, exts)
        cache = {tuple(sorted(codes)): old}

        def old_for(member_codes, y=y, m=m, cache=cache):
            if member_codes not in cache:
                cache[member_codes] = _old_sales(resolver, y, m, member_codes, returns)
            return cache[member_codes]

        cm = crew_kpi.compute_crew_month(crew, y, m, returns=returns,
                                         cdr_rows=rows if rows is not None else [])
        if cdr_missing:     # [] above only kept the crew from fetching the CDR a second time
            cm.kpis.pop(CALL_METRIC, None)
            for v in cm.per_member.values():
                v.pop(CALL_METRIC, None)
            cm.notes.append(cdr_note)
        returns_missing = returns and (
            old['returns_failed'] or crew_kpi.NOTE_RETURNS_UNREACHABLE in cm.notes)

        for metric in METRICS:
            s = stored.get((y, m, metric))
            if metric == CALL_METRIC:
                o = old_calls
                c = cm.kpis.get(metric)
            elif metric in RETURN_METRICS and returns_missing:
                o = c = None
            else:
                o = old['net'].get(metric)
                c = cm.kpis.get(metric)
            gross_equal = (returns and not returns_missing and metric in RETURN_METRICS
                           and metric in cm.gross
                           and _close(cm.gross.get(metric), old['gross'].get(metric)))
            reason = _reason(metric, s, o, c, cdr_missing=cdr_missing,
                             returns_missing=returns_missing, gross_equal=gross_equal)
            crew_values[(y, m, metric)] = _f(c)
            month_rows.append({'year': y, 'month': m, 'metric': metric, 'stored': _f(s),
                               'old_now': _f(o), 'crew': _f(c), 'diff_stored_crew': _diff(c, s),
                               'diff_old_crew': _diff(c, o), 'reason': reason,
                               'notes': list(cm.notes)})

        ids = identities(crew, *resolver.month_bounds(y, m)) if crew else []
        people += _people_rows(y, m, cm, ids, old_for=old_for, cfg_codes=codes, cfg_exts=exts,
                               cdr_rows=rows, labeller=labeller, returns_missing=returns_missing)

    targets = _targets(cc, stored, crew_values)
    result = {
        'crew_id': crew.pk if crew else None, 'start': list(start), 'end': list(end),
        'returns': returns, 'months': month_rows, 'people': people, 'targets': targets,
        'forecasts': _forecasts(),
        'branches': _branch_sales(resolver, months, codes, crew),
        'questions': _questions(targets, cdr_from_csv=cdr_from_csv),
    }
    result['totals'] = _totals(month_rows)
    return result


def _totals(month_rows) -> dict:
    metrics = {}
    for metric in METRICS:
        rows = [r for r in month_rows if r['metric'] == metric]
        t = {}
        for col in ('stored', 'old_now', 'crew'):
            vals = [r[col] for r in rows if r[col] is not None]
            t[col] = _f(sum(Decimal(str(v)) for v in vals)) if vals else None
            t[f'{col}_missing'] = sum(1 for r in rows if r[col] is None)
        metrics[metric] = t
    return {'metrics': metrics, 'reasons': dict(Counter(r['reason'] for r in month_rows))}


class _Rollback(Exception):
    """Sentinel: leave the atomic block so the temporary seed is rolled back."""


def compare_seeded_in_transaction(start, end, **kw) -> dict:
    """Seed the call-center crew, compare, roll everything back (seed rows and its audit entry)
    and return the computed result — for a DB where the seed must not persist yet."""
    from . import cc_seed
    from .models import Crew
    box = {}
    try:
        with transaction.atomic():
            cc_seed.seed()
            crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME, type='call_center', is_archived=False)
            box['result'] = compare(crew, start, end, **kw)
            raise _Rollback
    except _Rollback:
        pass
    return box['result']


# ── outputs ─────────────────────────────────────────────────────────────────────

def _num(v, money=True):
    if v is None:
        return NOT_COMPUTED
    return f'{v:,.2f}' if money else f'{v:,.0f}'


def markdown_summary(result) -> str:
    lines = ['## مقارنة الكول سنتر: الرقم القديم مقابل الطاقم', '',
             f"الفترة {result['start'][0]}-{result['start'][1]:02d} → "
             f"{result['end'][0]}-{result['end'][1]:02d}"
             + ('' if result['returns'] else ' — بدون خصم المرتجعات (--no-returns)'), '',
             '| المؤشر | metric | المخزن | القديم الآن | الطاقم | الطاقم − المخزن |',
             '|---|---|---:|---:|---:|---:|']
    for metric in METRICS:
        t = result['totals']['metrics'][metric]
        money = metric in MONEY_METRICS
        miss = sum(t[f'{c}_missing'] for c in ('stored', 'old_now', 'crew'))
        lines.append(f"| {METRIC_LABELS[metric]} | {metric} | {_num(t['stored'], money)} | "
                     f"{_num(t['old_now'], money)} | {_num(t['crew'], money)} | "
                     f"{_num(_diff(t['crew'], t['stored']), money)} |"
                     + (f' ({miss} خانة {NOT_COMPUTED})' if miss else ''))
    lines += ['', '### أسباب الفروق (عدد صفوف شهر × مؤشر)', '', '| السبب | code | العدد |',
              '|---|---|---:|']
    for code, n in sorted(result['totals']['reasons'].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {REASONS[code]['ar']} | {code} | {n} |")
    lines += ['', '### المستهدفات (الفرع الوهمي CC)', '']
    if result['targets']:
        lines += ['| # | metric | الفترة | المستهدف | اللوحة | SalesTarget اليوم | الطاقم | % اللوحة | % الطاقم |',
                  '|---|---|---|---:|---:|---:|---:|---:|---:|']
        for t in result['targets']:
            money = t['metric'] in MONEY_METRICS
            lines.append(f"| {t['target_id']} | {t['metric']} | {t['period']} | "
                         f"{_num(t['target'], money)} | {_num(t['achieved_board'], money)} | "
                         f"{_num(t['achieved_salestarget_today'], money)} | "
                         f"{_num(t['achieved_crew'], money)} | {t['pct_board'] if t['pct_board'] is not None else '—'} | "
                         f"{t['pct_crew'] if t['pct_crew'] is not None else '—'} |")
    else:
        lines.append('لا توجد مستهدفات للكول سنتر.')
    lines += ['', '### أسئلة للمالك', '']
    lines += [f'{i}. {q}' for i, q in enumerate(result['questions'], 1)]
    return '\n'.join(lines) + '\n'


_MONEY_FMT, _COUNT_FMT = '#,##0.00', '#,##0'


def build_workbook(result):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core.export_safety import neutralise_formulas, safe_sheet

    wb = Workbook()
    wb.remove(wb.active)

    def sheet(title, header, rows, money_cols=(), metric_col=None):
        ws = safe_sheet(wb.create_sheet(title))
        ws.sheet_view.rightToLeft = True
        ws.append(header)
        for i in range(1, len(header) + 1):
            ws.cell(row=1, column=i).font = Font(bold=True)
        for values, metric in rows:
            ws.append([NOT_COMPUTED if v is None else v for v in values])
            r = ws.max_row
            fmt = _MONEY_FMT if metric is None or metric in MONEY_METRICS else _COUNT_FMT
            for col in money_cols:
                ws.cell(row=r, column=col).number_format = fmt
        for i, _ in enumerate(header, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 18
        return ws

    sheet('ملخص', ['السنة', 'الشهر', 'المؤشر', 'metric', 'المخزن (اللوحة)', 'القديم محسوباً الآن',
                   'الطاقم', 'الطاقم − المخزن', 'الطاقم − القديم الآن', 'السبب', 'reason'],
          [([r['year'], r['month'], METRIC_LABELS[r['metric']], r['metric'], r['stored'],
             r['old_now'], r['crew'], r['diff_stored_crew'], r['diff_old_crew'],
             REASONS[r['reason']]['ar'], r['reason']], r['metric']) for r in result['months']],
          money_cols=(5, 6, 7, 8, 9))

    def person_metric(metric):
        label = METRIC_LABELS[metric]
        return f'{label} — غير تجميعي' if metric in NOT_ADDITIVE_PER_PERSON else label

    ws = sheet('حسب الشخص', ['السنة', 'الشهر', 'الشخص', 'المفتاح', 'بائع غير محدد', 'المؤشر',
                             'metric', 'القديم (أكواد الإعداد)', 'الطاقم', 'الفرق'],
               [([p['year'], p['month'], p['label'], p['member_key'], 'نعم' if p['generic'] else '',
                  person_metric(p['metric']), p['metric'], p['old'], p['crew'], p['diff']],
                 p['metric']) for p in result['people']],
               money_cols=(8, 9, 10))
    ws.append([])
    ws.append([PIC_NOT_ADDITIVE])

    sheet('المستهدفات', ['#', 'metric', 'الفترة', 'المستهدف', 'المحقق (اللوحة)',
                         'المحقق (SalesTarget.actual_value اليوم)', 'المحقق (الطاقم)', '% اللوحة',
                         '% الطاقم', 'الإيقاع (اللوحة)', 'الإيقاع (الطاقم)'],
          [([t['target_id'], t['metric'], t['period'], t['target'], t['achieved_board'],
             t['achieved_salestarget_today'], t['achieved_crew'],
             '—' if t['pct_board'] is None else t['pct_board'],
             '—' if t['pct_crew'] is None else t['pct_crew'],
             t['pace_board'] or '—', t['pace_crew'] or '—'], t['metric'])
           for t in result['targets']], money_cols=(4, 5, 6, 7))

    sheet('التنبؤات', ['السيناريو', '#', 'metric', 'التنبؤ', 'الهدف'],
          [([f['scenario'], f['scenario_id'], f['metric'], f['forecast'], f['target']], f['metric'])
           for f in result['forecasts']], money_cols=(4, 5))

    sheet('أسئلة للمالك', ['#', 'السؤال'],
          [([i, q], 'customer_count') for i, q in enumerate(result['questions'], 1)])

    counts = result['totals']['reasons']
    sheet('شرح الفروق', ['code', 'السبب', 'reason', 'عدد الصفوف'],
          [([code, r['ar'], r['en'], counts.get(code, 0)], 'customer_count')
           for code, r in REASONS.items()])

    sheet('حسب الفرع', ['الفرع', 'القديم (أكواد الإعداد)', 'الطاقم', 'الفرق'],
          [([b['label'], b['old'], b['crew'], b['diff']], None) for b in result['branches']],
          money_cols=(2, 3, 4))
    return neutralise_formulas(wb)
