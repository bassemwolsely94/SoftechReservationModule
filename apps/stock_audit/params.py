"""
apps/stock_audit/params.py

Thresholds: rules.RULES defaults ⊕ StockAuditRule.params (chain) ⊕ StockAuditRuleOverride.params (branch).
Every value is validated against the rule's schema before it is stored — the backend owns the rules.
"""
from decimal import Decimal, InvalidOperation

from .rules import RULES


class ParamError(ValueError):
    pass


def validate_params(code, params, partial=True):
    """Return a cleaned copy of `params` or raise ParamError. `partial` allows a subset (overrides)."""
    spec = RULES.get(code)
    if spec is None:
        raise ParamError(f'unknown rule {code!r}')
    if not isinstance(params, dict):
        raise ParamError('params must be an object')
    schema = spec['schema']
    unknown = set(params) - set(schema)
    if unknown:
        raise ParamError(f'unknown params for {code}: {", ".join(sorted(unknown))}')
    out = {}
    for key, value in params.items():
        kind = schema[key]
        if kind[0] == 'number':
            try:
                d = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise ParamError(f'{key} must be a number')
            if not d.is_finite() or d < kind[1] or d > kind[2]:
                raise ParamError(f'{key} must be between {kind[1]} and {kind[2]}')
            out[key] = int(d) if d == d.to_integral_value() else float(d)
        elif kind[0] == 'bool':
            if not isinstance(value, bool):
                raise ParamError(f'{key} must be true or false')
            out[key] = value
        elif kind[0] == 'codes':
            if not isinstance(value, (list, tuple)):
                raise ParamError(f'{key} must be a list')
            cleaned = []
            for v in value:
                s = str(v).strip()
                if not s or len(s) > 20:
                    raise ParamError(f'{key}: invalid code {v!r}')
                if s not in cleaned:
                    cleaned.append(s)
            out[key] = cleaned
    if not partial:
        missing = set(schema) - set(out)
        if missing:
            raise ParamError(f'missing params for {code}: {", ".join(sorted(missing))}')
    return out


def ensure_rules():
    """Create missing StockAuditRule rows from RULES defaults; add newly introduced default keys
    to existing rows without touching values the owner already set. Returns {code: rule}."""
    from .models import StockAuditRule
    rules = {r.code: r for r in StockAuditRule.objects.all()}
    for code, spec in RULES.items():
        r = rules.get(code)
        if r is None:
            rules[code] = StockAuditRule.objects.create(code=code, params=dict(spec['defaults']))
            continue
        missing = {k: v for k, v in spec['defaults'].items() if k not in (r.params or {})}
        if missing:
            r.params = {**(r.params or {}), **missing}
            r.save(update_fields=['params', 'updated_at'])
    return rules


def effective(rule, override=None):
    """(enabled, params) for one rule at one branch."""
    spec = RULES[rule.code]
    params = {**spec['defaults'], **(rule.params or {})}
    enabled = rule.enabled
    if override is not None:
        params.update(override.params or {})
        if override.enabled is not None:
            enabled = override.enabled
    return enabled, params
