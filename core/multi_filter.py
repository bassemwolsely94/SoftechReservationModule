"""Multi-select list filters: one query parameter, several values.

The screens send a multi-select dropdown as one comma list (``?status=draft,submitted``); the
repeated form (``?status=draft&status=submitted``) is accepted too. Nothing ticked means the
parameter is absent, i.e. no filter — never "match nothing".

    from core.multi_filter import multi_values, multi_ids, filter_in
    qs = filter_in(qs, 'status', multi_values(request.query_params, 'status'))
    qs = filter_in(qs, 'branch_id', multi_ids(request.query_params, 'branch'))

A single value keeps working exactly as before, so old links and bookmarks still filter.
"""

_MAX_VALUES = 500   # a pasted list longer than this is cut, not turned into a huge IN (...)


def multi_values(params, key):
    """Distinct non-empty values of ``key``, in the order given ([] = no filter)."""
    raw = params.getlist(key) if hasattr(params, 'getlist') else [params.get(key)]
    out = []
    for chunk in raw:
        if chunk in (None, ''):
            continue
        parts = chunk if isinstance(chunk, (list, tuple, set)) else str(chunk).split(',')
        for p in parts:
            p = str(p).strip()
            if p and p not in out:
                out.append(p)
    return out[:_MAX_VALUES]


def multi_ids(params, key):
    """Like multi_values, keeping whole-number ids only (junk dropped, never an error)."""
    return [int(v) for v in multi_values(params, key) if v.isdigit()]


def filter_in(qs, field, values):
    """``field`` equal to the one value, or ``field__in`` several; untouched when empty."""
    if not values:
        return qs
    if len(values) == 1:
        return qs.filter(**{field: values[0]})
    return qs.filter(**{f'{field}__in': values})
