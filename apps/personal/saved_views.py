"""C23 — saved filters / default views per user on worklist screens.

The allow-list below is the whole contract: a screen key and the filter keys it may store. Anything
else is dropped on save (never an error the user has to understand), values are trimmed to plain
JSON scalars or short lists, and the stored dict is capped in size. A saved view is only a set of
filters — the screen's own endpoints still check module grants and branch scope when it is applied.
"""
import json

from apps.users.roles import ROLE_KEYS

# screen key → {filter key: nested allow-list (dict) | None for a plain value}
SCREENS = {
    'cash.dead_stock': {'lane': None, 'location': None, 'branch': None, 'q': None, 'show_decided': None},
    'batches.near_expiry': {'branch': None, 'action': None},
    'batches.return_window': {'supplier': None, 'location': None, 'state': None},
    'transits': {'priority': None, 'transit_status': None, 'awaiting_erp': None,
                 'supplying_branch': None, 'receiving_branch': None, 'min_days': None},
    'purchasing': {'abc': None, 'search': None, 'item_filters': {k: None for k in (
        # frontend/src/pages/PurchasingDashboard.jsx MULTI_KEYS + the flag / range filters
        'medicine_type', 'category', 'shape_code', 'effect_code', 'origin_code',
        'supplier_code', 'producer_code', 'family_code',
        'store_classif', 'nosale_classif', 'insurance_type', 'item_level',
        'branch_trans', 'supplier_trans', 'customer_trans',
        'requires_fridge', 'is_fast_moving', 'has_points', 'is_active',
        'price_min', 'price_max', 'discount_min', 'discount_max')}},
}

MAX_VIEWS_PER_SCREEN = 30
MAX_LIST = 300
MAX_STR = 200
MAX_JSON = 8000


def _scalar(v):
    if isinstance(v, bool) or v is None:
        return v, True
    if isinstance(v, (int, float)):
        return v, True
    if isinstance(v, str):
        return v[:MAX_STR], True
    return None, False


def _value(v):
    if isinstance(v, list):
        out = []
        for x in v[:MAX_LIST]:
            s, ok = _scalar(x)
            if ok and s is not None:
                out.append(s)
        return out, True
    return _scalar(v)


def clean_filters(screen, filters):
    """Keep only the allow-listed keys of `screen` with plain values. Returns (dict, dropped_keys)."""
    allowed = SCREENS.get(screen)
    if allowed is None or not isinstance(filters, dict):
        return {}, sorted(filters) if isinstance(filters, dict) else []
    out, dropped = {}, []
    for k, v in filters.items():
        if k not in allowed:
            dropped.append(k)
            continue
        nested = allowed[k]
        if nested is not None:
            if not isinstance(v, dict):
                dropped.append(k)
                continue
            inner = {}
            for ik, iv in v.items():
                val, ok = _value(iv) if ik in nested else (None, False)
                if ok:
                    inner[ik] = val
                else:
                    dropped.append(f'{k}.{ik}')
            out[k] = inner
            continue
        val, ok = _value(v)
        if ok:
            out[k] = val
        else:
            dropped.append(k)
    if len(json.dumps(out, ensure_ascii=False)) > MAX_JSON:
        raise ValueError('الفلاتر أكبر من المسموح.')
    return out, sorted(dropped)


def valid_role(role):
    return role in ROLE_KEYS
