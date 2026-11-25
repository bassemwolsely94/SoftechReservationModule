"""
apps/crews/cc_switch.py

The one-shot switch of the call center from the fake «CC» branch to the call-center crew (crews
piece 2b Part B, Task 5; owner rulings A–E). plan_switch() reads and writes nothing (a crew seed
it needs is rolled back); apply_switch() does it all in ONE transaction:

  1. seed the crew if absent (cc_seed.seed, PBX agent extensions on — ruling C; audited there)
  2. per month (every month with a CC KpiActualRollup row, plus the current month when the crew has
     identities in it): compute_crew_month(returns=True). Per metric
       computed by the crew (and no note makes it unavailable) → new = crew value, source 'crew'
       otherwise                                              → new = stored,     source 'stored'
     The CC row is re-pointed in place (branch NULL, crew set, value new) so its id survives; when
     the crew already has a row for that month × metric (build_crew_rollups) the CC row is deleted
     and the crew row takes the new value. A computed metric with no CC row is created.
     One 'cc_crew_history_rebuilt' audit row per month.
  3. SalesTarget(branch=CC) → scope 'crew'; ForecastResult(branch=CC) → crew, scope_key 'crew:<id>'
     (a crew forecast already there for the scenario × metric wins; the CC row is deleted)
  4. the CC branch kind → 'closed'

A second run finds nothing to move and changes nothing. No SOFTECH writes: SOFTECH is read only for
returns (softech_returns via config.sybase); the CDR once per month through cc_comparison._cdr_rows.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog

from . import cc_seed
from . import kpi as crew_kpi
from .cc_comparison import _cdr_rows, _months
from .cc_legacy import legacy_cc_branch
from .membership import identities

CALL = 'call_count'
CREW_METRICS = (*crew_kpi.SALES_METRICS, CALL)
FOCUS_MONTH = (2026, 10)            # the month the owner checks attainment on (October 2026)
TWO = Decimal('0.01')

class SwitchRefused(Exception):
    """--apply refused (month count not confirmed, crew name taken, ...)."""


class _Rollback(Exception):
    pass


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(TWO)


def _s(v):
    return None if v is None else str(_q(v))


def _find_crew():
    return cc_seed._find_crew()


# ── the plan ────────────────────────────────────────────────────────────────────

def _month_plan(crew, y, m, cc_rows, crew_rows, cdr_rows_by_month) -> dict:
    rows, cdr_note = _cdr_rows(y, m, cdr_rows_by_month)        # one CDR fetch per month
    cm = crew_kpi.compute_crew_month(crew, y, m, returns=True,
                                     cdr_rows=rows if rows is not None else [])
    notes = list(cm.notes)
    if rows is None:        # [] above only stopped a second fetch: call_count is not computed
        cm.kpis.pop(CALL, None)
        notes.append(cdr_note)
    stored_calls = cc_rows[CALL].value if CALL in cc_rows else (
        crew_rows[CALL].value if CALL in crew_rows else None)
    if crew_kpi.guard_empty_cdr(cm, stored_calls):      # a CDR hole never wipes a stored count
        notes.append(crew_kpi.NOTE_CDR_EMPTY)
    off = crew_kpi.unavailable_metrics(notes)
    computed = {k: v for k, v in cm.kpis.items() if k in CREW_METRICS and k not in off}
    out = []
    for metric in sorted(set(cc_rows) | set(computed)):
        cc_row, crew_row = cc_rows.get(metric), crew_rows.get(metric)
        stored = cc_row.value if cc_row else None
        if metric in computed:
            new, source = computed[metric], 'crew'
        else:
            new, source = stored, 'stored'
        if cc_row:
            action = 'repoint_replace' if crew_row else 'repoint'
        else:
            action = 'update' if crew_row else 'create'
        out.append({'metric': metric, 'stored': _s(stored), 'crew': _s(computed.get(metric)),
                    'new': _s(new), 'source': source, 'action': action,
                    'cc_row_id': cc_row.pk if cc_row else None,
                    'crew_row_id': crew_row.pk if crew_row else None})
    return {'year': y, 'month': m, 'notes': notes, 'metrics': out}


def _targets(cc, month_plans, crew):
    from apps.forecasting.models import KpiActualRollup as K
    from apps.incentives.models import SalesTarget
    new_by = {(mp['year'], mp['month'], r['metric']): Decimal(r['new'])
              for mp in month_plans for r in mp['metrics']}
    out = []
    for t in SalesTarget.objects.filter(branch=cc).order_by('period_start', 'metric', 'id'):
        months = _months((t.period_start.year, t.period_start.month),
                         (t.period_end.year, t.period_end.month))
        before = after = Decimal('0')
        for y, m in months:
            row = K.objects.filter(branch=cc, year=y, month=m, metric=t.metric).first()
            before += row.value if row else 0
            if (y, m, t.metric) in new_by:
                after += new_by[(y, m, t.metric)]
            elif crew is not None:
                crow = K.objects.filter(crew=crew, year=y, month=m, metric=t.metric).first()
                after += crow.value if crow else 0
        target = Decimal(str(t.target_value or 0))

        def pct(a):
            return round(float(a) / float(target) * 100, 1) if target else None
        out.append({'id': t.pk, 'metric': t.metric, 'scope_before': t.scope_type,
                    'period': f'{t.period_start.isoformat()} → {t.period_end.isoformat()}',
                    'months': [list(x) for x in months], 'target': _s(target),
                    'achieved_before': _s(before), 'achieved_after': _s(after),
                    'pct_before': pct(before), 'pct_after': pct(after)})
    return out


def _nothing_to_move(cc) -> bool:
    from apps.branches.models import Branch
    from apps.forecasting.models import ForecastResult, KpiActualRollup as K
    from apps.incentives.models import SalesTarget
    if cc is None:
        return True
    return not (K.objects.filter(branch=cc).exists()
                or SalesTarget.objects.filter(branch=cc).exists()
                or ForecastResult.objects.filter(branch=cc).exists()
                or cc.kind != Branch.KIND_CLOSED)


def _build(crew, cc, *, cdr_rows_by_month, today, focus_month, seeds_crew) -> dict:
    from apps.branches.models import Branch
    from apps.forecasting.models import ForecastResult, KpiActualRollup as K
    plan = {'crew_id': crew.pk if crew else None, 'seeds_crew': seeds_crew,
            'focus_month': list(focus_month), 'months': [], 'targets': [], 'focus_targets': [],
            'forecast_count': 0, 'branch': None}
    if _nothing_to_move(cc):
        plan.update(month_count=0, nothing_to_move=True)
        return plan
    months = set(K.objects.filter(branch=cc).values_list('year', 'month').order_by().distinct())
    cur = (today.year, today.month)
    m_start, m_end = date(*cur, 1), date(*cur, monthrange(*cur)[1])
    if crew is not None and identities(crew, m_start, m_end):
        months.add(cur)
    for y, m in sorted(months):
        cc_rows = {r.metric: r for r in K.objects.filter(branch=cc, year=y, month=m)}
        crew_rows = ({r.metric: r for r in K.objects.filter(crew=crew, year=y, month=m)}
                     if crew else {})
        plan['months'].append(_month_plan(crew, y, m, cc_rows, crew_rows, cdr_rows_by_month))
    plan['targets'] = _targets(cc, plan['months'], crew)
    plan['focus_targets'] = [t['id'] for t in plan['targets'] if list(focus_month) in t['months']]
    plan['forecast_count'] = ForecastResult.objects.filter(branch=cc).count()
    plan['branch'] = {'id': cc.pk, 'kind_before': cc.kind, 'kind_after': Branch.KIND_CLOSED}
    plan.update(month_count=len(plan['months']), nothing_to_move=False)
    return plan


def plan_switch(user=None, *, cdr_rows_by_month=None, today=None, focus_month=FOCUS_MONTH) -> dict:
    """The switch as it would run now — writes nothing (a needed crew seed is rolled back).
    cdr_rows_by_month = {(y, m): rows} replaces the live CDR (a month missing = unavailable)."""
    today = today or timezone.localdate()
    box = {}
    try:
        with transaction.atomic():
            cc = legacy_cc_branch()
            crew = _find_crew()
            seeds = crew is None and not _nothing_to_move(cc)
            if seeds:
                crew = _find_crew_after_seed(user)
            box['plan'] = _build(crew, cc, cdr_rows_by_month=cdr_rows_by_month, today=today,
                                 focus_month=focus_month, seeds_crew=seeds)
            raise _Rollback
    except _Rollback:
        pass
    if box['plan']['seeds_crew']:
        box['plan']['crew_id'] = None           # the seeded id was rolled back
    return box['plan']


def _find_crew_after_seed(user):
    from .models import Crew
    return Crew.objects.get(pk=cc_seed.seed(user=user)['crew_id'])


# ── the switch ──────────────────────────────────────────────────────────────────

def _apply_month(crew, mp, user):
    from apps.forecasting.models import KpiActualRollup as K
    old, new, source, replaced, created = {}, {}, {}, {}, []
    for r in mp['metrics']:
        value = Decimal(r['new'])
        if r['action'] in ('repoint_replace', 'update'):
            K.objects.filter(pk=r['crew_row_id']).update(value=value, computed_at=timezone.now())
            if r['action'] == 'repoint_replace':
                K.objects.filter(pk=r['cc_row_id']).delete()
                replaced[r['metric']] = r['crew_row_id']
        elif r['action'] == 'repoint':
            row = K.objects.get(pk=r['cc_row_id'])
            row.branch, row.crew, row.value = None, crew, value
            row.save()
        else:
            K.objects.create(crew=crew, branch=None, year=mp['year'], month=mp['month'],
                             metric=r['metric'], value=value)
            created.append(r['metric'])
        if r['stored'] is not None:
            old[r['metric']] = r['stored']
        new[r['metric']] = r['new']
        source[r['metric']] = r['source']
    AuditLog.log('cc_crew_history_rebuilt', user=user, obj=crew, old_data=old, new_data=new,
                 extra={'year': mp['year'], 'month': mp['month'], 'source': source,
                        'notes': mp['notes'], 'replaced_crew_rows': replaced,
                        'created': created})


def _move_targets(cc, crew, plan, user):
    from apps.incentives.models import SalesTarget
    qs = SalesTarget.objects.filter(branch=cc)
    if not qs.exists():
        return
    rows = plan['targets']
    qs.update(scope_type=SalesTarget.SCOPE_CREW, crew=crew, branch=None)
    AuditLog.log('cc_targets_moved_to_crew', user=user, obj=crew,
                 old_data={'branch_id': cc.pk, 'targets': [
                     {'id': t['id'], 'scope_type': t['scope_before'], 'achieved': t['achieved_before'],
                      'pct': t['pct_before']} for t in rows]},
                 new_data={'crew_id': crew.pk, 'scope_type': SalesTarget.SCOPE_CREW, 'targets': [
                     {'id': t['id'], 'achieved': t['achieved_after'], 'pct': t['pct_after']}
                     for t in rows]},
                 extra={'ids': [t['id'] for t in rows], 'focus_month': plan['focus_month'],
                        'focus_targets': plan['focus_targets']})


def _move_forecasts(cc, crew, user):
    from apps.forecasting.models import ForecastResult
    key = f'crew:{crew.pk}'
    moved, dropped = [], []
    for f in ForecastResult.objects.filter(branch=cc).order_by('id'):
        clash = (ForecastResult.objects.filter(scenario_id=f.scenario_id, scope_key=key,
                                               metric=f.metric).exclude(pk=f.pk).first())
        if clash:       # the crew's own forecast for the scenario x metric wins
            dropped.append({'id': f.pk, 'kept_crew_row': clash.pk, 'metric': f.metric,
                            'scenario_id': f.scenario_id, 'old_scope_key': f.scope_key})
            f.delete()
            continue
        moved.append({'id': f.pk, 'old_scope_key': f.scope_key})
        ForecastResult.objects.filter(pk=f.pk).update(branch=None, crew=crew, scope_key=key)
    if moved or dropped:
        AuditLog.log('cc_forecasts_moved_to_crew', user=user, obj=crew,
                     old_data={'branch_id': cc.pk, 'rows': moved},
                     new_data={'crew_id': crew.pk, 'scope_key': key},
                     extra={'moved': len(moved), 'deleted_clashes': dropped})


def _close_branch(cc, user):
    from apps.branches.models import Branch
    if cc.kind == Branch.KIND_CLOSED:
        return
    before = cc.kind
    Branch.objects.filter(pk=cc.pk).update(kind=Branch.KIND_CLOSED)
    AuditLog.log('cc_branch_closed', user=user, obj=cc, old_data={'kind': before},
                 new_data={'kind': Branch.KIND_CLOSED}, extra={'branch_id': cc.pk})


def _figures(plan) -> dict:
    return {(int(mp['year']), int(mp['month']), r['metric']): r['new']
            for mp in plan.get('months', []) for r in mp.get('metrics', [])}


def plan_differences(reviewed: dict, plan: dict, limit: int = 10) -> list:
    """Why the plan computed now is not the reviewed one: the month count, or any
    month x metric whose new figure differs / is missing on one side. [] = identical."""
    out = []
    if int(reviewed.get('month_count', -1)) != plan['month_count']:
        out.append(f"month count: reviewed {reviewed.get('month_count')}, now {plan['month_count']}")
    a, b = _figures(reviewed), _figures(plan)
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            y, m, metric = key
            out.append(f'{y}-{m:02d} {metric}: reviewed {a.get(key)}, now {b.get(key)}')
    return out[:limit] + ([f'... {len(out) - limit} more'] if len(out) > limit else [])


def apply_switch(user, *, confirm_months, reviewed_plan=None, cdr_rows_by_month=None,
                 today=None, focus_month=FOCUS_MONTH) -> dict:
    """Run the switch in one transaction. confirm_months must equal the planned month count
    (computed inside the same transaction) and, when reviewed_plan (the dry run's JSON) is given,
    every month x metric figure must equal it — otherwise SwitchRefused and nothing is written."""
    today = today or timezone.localdate()
    with transaction.atomic():
        cc = legacy_cc_branch()
        crew = _find_crew()
        seeds = crew is None and not _nothing_to_move(cc)
        if seeds:
            crew = _find_crew_after_seed(user)
        plan = _build(crew, cc, cdr_rows_by_month=cdr_rows_by_month, today=today,
                      focus_month=focus_month, seeds_crew=seeds)
        if confirm_months is None or int(confirm_months) != plan['month_count']:
            raise SwitchRefused(f'--confirm-months must be {plan["month_count"]} '
                                f'(the planned month count), got {confirm_months}.')
        if reviewed_plan is not None:
            diffs = plan_differences(reviewed_plan, plan)
            if diffs:
                raise SwitchRefused('The figures changed since the reviewed plan — run the dry run '
                                    'again and review it: ' + '; '.join(diffs))
        if plan['nothing_to_move']:
            return plan
        for mp in plan['months']:
            _apply_month(crew, mp, user)
        _move_targets(cc, crew, plan, user)
        _move_forecasts(cc, crew, user)
        _close_branch(cc, user)
    return plan
