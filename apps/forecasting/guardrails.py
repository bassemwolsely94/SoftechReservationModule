"""
Guardrail evaluation  (doc 16 metric-catalog Phase 3)
=====================================================
Combines a KPI reward (SalesTarget attainment) with guardrail metrics so an
incentive is earned only when the reward is hit AND the guardrails hold — the
anti-gaming layer (reward revenue, but only if discount%/return-rate stay in
bounds). apps/incentives calls `evaluate_eligibility` before paying out.
"""
from datetime import date


def evaluate_guardrails(scope_type, start, end, *, reward_metric=None, **scope_kwargs):
    """Evaluate all active guardrails for a scope over a period.
    scope_kwargs: branch_ids / softech_user / category_id (passed to the resolver).
    Returns {passed: bool, checks: [{metric, value, operator, threshold, ok, label}]}."""
    from apps.forecasting.models import MetricGuardrail, KpiActualRollup
    from apps.forecasting.kpi import KpiResolver
    qs = MetricGuardrail.objects.filter(active=True, scope_type=scope_type)
    if reward_metric:
        from django.db.models import Q
        qs = qs.filter(Q(reward_metric='') | Q(reward_metric=reward_metric))
    guards = list(qs)
    if not guards:
        return {'passed': True, 'checks': []}
    resolver = KpiResolver()
    checks, passed = [], True
    for g in guards:
        val = resolver.resolve(g.guardrail_metric, start=start, end=end, **scope_kwargs)
        ok = g.passes(val)
        passed = passed and ok
        checks.append({
            'metric': g.guardrail_metric,
            'label': KpiActualRollup.METRIC_LABELS.get(g.guardrail_metric, g.guardrail_metric),
            'value': float(val), 'operator': g.operator,
            'threshold': float(g.threshold), 'ok': ok,
        })
    return {'passed': passed, 'checks': checks}


def evaluate_eligibility(target):
    """
    Incentive eligibility for a SalesTarget: reward hit AND guardrails hold.
    Returns {eligible, attainment, guardrails}.
    """
    att = target.attainment()
    reward_hit = att['pct'] >= 100 or att['pace'] == 'met'
    # map SalesTarget scope → resolver kwargs
    st = target.scope_type
    scope_kwargs = {}
    if st == 'branch' and target.branch_id:
        scope_kwargs['branch_ids'] = [target.branch_id]; scope_type = 'branch'
    elif st == 'salesperson' and target.softech_user:
        scope_kwargs['softech_user'] = target.softech_user; scope_type = 'salesperson'
    elif st == 'category' and target.category_id:
        scope_kwargs['category_id'] = target.category_id; scope_type = 'category'
    else:
        scope_type = 'chain'
    g = evaluate_guardrails(scope_type, target.period_start, target.period_end,
                            reward_metric=target.metric, **scope_kwargs)
    return {
        'eligible': bool(reward_hit and g['passed']),
        'reward_hit': reward_hit,
        'attainment': att,
        'guardrails': g,
    }
