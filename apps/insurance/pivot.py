"""
apps/insurance/pivot.py

Generic pivot / cross-tab engine for insurance claims.

Reuses the existing frozen snapshot data — NO new models, NO new fields.
All dimensions are already columns on InsuranceClaimPrescription / InsuranceClaimLine.

One function — build_pivot() — powers every analysis:
  • Simple summary      : row dimension only
  • Cross-tab           : row dimension × column dimension
  • Both at prescription level (default) and item-line level (source='lines')

Security: dimensions & measures are validated against whitelists — no arbitrary
ORM field injection from the client.
"""
from decimal import Decimal

from django.db.models import Sum, Count, F, DecimalField
from django.db.models.functions import TruncMonth, TruncDay, Coalesce

from .models import InsuranceClaimPrescription, InsuranceClaimLine


# ── Dimension whitelist ─────────────────────────────────────────────────────────
# key → (ORM field path, Arabic label, annotation function or None)
# Annotation fn is applied via .annotate() before grouping (e.g. month truncation).

_PRESCRIPTION_DIMS = {
    'department':     ('dept_name',                       'الإدارة'),
    'relative':       ('relative_degree',                 'درجة القرابة'),
    'hi_type':        ('hi_type_code',                    'نوع التأمين'),
    'branch':         ('softech_branchcode',              'الفرع'),
    'billing_group':  ('billing_group__name',             'فئة الفوترة'),
    'patient':        ('patient_name',                    'المريض'),
    'insurer':        ('claim__subclient__client__name',  'جهة التأمين'),
    'subclient':      ('claim__subclient__name',          'الفئة'),
    'month':          ('softech_docdate',                 'الشهر'),   # truncated below
    'day':            ('softech_docdate',                 'اليوم'),
}

_LINE_DIMS = {
    'item_category':  ('item_category',                   'تصنيف الصنف'),
    'item':           ('item_name',                       'الصنف'),
    'itemcode':       ('softech_itemcode',                'كود الصنف'),
    'department':     ('prescription__dept_name',         'الإدارة'),
    'relative':       ('prescription__relative_degree',   'درجة القرابة'),
    'branch':         ('prescription__softech_branchcode','الفرع'),
    'insurer':        ('prescription__claim__subclient__client__name', 'جهة التأمين'),
    'subclient':      ('prescription__claim__subclient__name',         'الفئة'),
}

# ── Measure whitelist ─────────────────────────────────────────────────────────
# key → (label, aggregate expression factory)
_dec = DecimalField(max_digits=16, decimal_places=2)

_PRESCRIPTION_MEASURES = {
    'net':          ('الصافى',           lambda: Sum('net_after')),
    'gross':        ('الإجمالى',         lambda: Sum('gross_before')),
    'discount':     ('الخصم',            lambda: Sum('total_discount')),
    'local':        ('محلى',             lambda: Sum('local_before')),
    'imported':     ('مستورد',           lambda: Sum('imported_before')),
    'tarsia':       ('ترسية',            lambda: Sum('tarsia_before')),
    'rx_count':     ('عدد الروشتات',     lambda: Count('id')),
    'patients':     ('عدد المرضى',       lambda: Count('patient_name', distinct=True)),
}

_LINE_MEASURES = {
    'line_total':   ('الإجمالى',         lambda: Sum('line_total')),
    'net':          ('الصافى',           lambda: Sum('net_amount')),
    'discount':     ('الخصم',            lambda: Sum('discount_amt')),
    'quantity':     ('الكمية',           lambda: Sum('quantity')),
    'line_count':   ('عدد البنود',       lambda: Count('id')),
}


def _dims_for(source):
    return _LINE_DIMS if source == 'lines' else _PRESCRIPTION_DIMS


def _measures_for(source):
    return _LINE_MEASURES if source == 'lines' else _PRESCRIPTION_MEASURES


def available_config(source='prescriptions'):
    """Return the whitelisted dimensions + measures for the UI selectors."""
    dims = _dims_for(source)
    meas = _measures_for(source)
    return {
        'dimensions': [{'key': k, 'label': v[1]} for k, v in dims.items()],
        'measures':   [{'key': k, 'label': v[0]} for k, v in meas.items()],
    }


def _base_queryset(source, filters):
    """Build the filtered base queryset for prescriptions or lines."""
    if source == 'lines':
        qs = InsuranceClaimLine.objects.all()
        claim_path  = 'prescription__claim_id'
        client_path = 'prescription__claim__subclient__client_id'
        date_path   = 'prescription__softech_docdate'
        excl_path   = 'prescription__exclusion__isnull'
    else:
        qs = InsuranceClaimPrescription.objects.all()
        claim_path  = 'claim_id'
        client_path = 'claim__subclient__client_id'
        date_path   = 'softech_docdate'
        excl_path   = 'exclusion__isnull'

    if filters.get('claim_id'):
        qs = qs.filter(**{claim_path: filters['claim_id']})
    if filters.get('client_id'):
        qs = qs.filter(**{client_path: filters['client_id']})
    if filters.get('subclient_id'):
        sc_path = ('prescription__claim__subclient_id' if source == 'lines'
                   else 'claim__subclient_id')
        qs = qs.filter(**{sc_path: filters['subclient_id']})
    if filters.get('date_from'):
        qs = qs.filter(**{f'{date_path}__gte': filters['date_from']})
    if filters.get('date_to'):
        qs = qs.filter(**{f'{date_path}__lte': filters['date_to']})
    # Always exclude soft-excluded prescriptions from analysis
    qs = qs.filter(**{excl_path: True})
    return qs


def _annotate_dim(qs, dim_key, source, alias):
    """Apply the grouping expression for a dimension, return (qs, group_field)."""
    dims = _dims_for(source)
    field_path = dims[dim_key][0]

    if dim_key == 'month':
        return qs.annotate(**{alias: TruncMonth(field_path)}), alias
    if dim_key == 'day':
        return qs.annotate(**{alias: TruncDay(field_path)}), alias
    # Plain field — group directly on its path (alias not needed)
    return qs, field_path


def _norm_val(v):
    if v is None:
        return '—'
    if hasattr(v, 'isoformat'):
        return v.isoformat()[:10]
    return str(v)


def build_pivot_multi(source='prescriptions', rows=None, cols=None,
                      measure='net', filters=None, limit=400):
    """
    Multi-dimension pivot: group by SEVERAL row dimensions and SEVERAL column
    dimensions at once (Excel-style nested pivot).

    rows / cols : lists of dimension keys (order = nesting order).  Either may be
    empty.  Falls back to the same aggregation engine as build_pivot.

    Returns:
      {
        row_dims:  [{key,label}...],  col_dims: [{key,label}...],
        measure_label,
        columns: [{key:'a|b', labels:['a','b']} ...],   # [] when no col dims
        rows:    [{dims:['x','y'], values:{colkey:num}, _total:num} ...],
        totals:  {colkey:num, ..., _total:num},
        grand_total: num,
      }
    """
    filters = filters or {}
    dims = _dims_for(source)
    meas = _measures_for(source)
    rows = [r for r in (rows or []) if r]
    cols = [c for c in (cols or []) if c]

    for k in rows + cols:
        if k not in dims:
            raise ValueError(f'بُعد غير صالح: {k}')
    if measure not in meas:
        raise ValueError(f'المقياس غير صالح: {measure}')
    if not rows and not cols:
        raise ValueError('اختر بُعداً واحداً على الأقل للصفوف أو الأعمدة')

    measure_label, measure_fn = meas[measure]
    qs = _base_queryset(source, filters)

    row_fields, col_fields = [], []
    for i, k in enumerate(rows):
        qs, f = _annotate_dim(qs, k, source, f'_r{i}')
        row_fields.append(f)
    for i, k in enumerate(cols):
        qs, f = _annotate_dim(qs, k, source, f'_c{i}')
        col_fields.append(f)

    agg = (qs.values(*(row_fields + col_fields))
             .annotate(_value=measure_fn())
             .order_by())

    def _num(v):
        return float(v) if isinstance(v, Decimal) else (v or 0)

    matrix    = {}   # row_tuple -> {col_key -> value}
    row_tot   = {}   # row_tuple -> total
    col_tot   = {}   # col_key -> total
    col_labels = {}  # col_key -> [label,...]
    grand = 0
    for r in agg:
        rt = tuple(_norm_val(r[f]) for f in row_fields)
        ct_labels = [_norm_val(r[f]) for f in col_fields]
        ck = '|'.join(ct_labels) if col_fields else '_total'
        val = _num(r['_value'])
        matrix.setdefault(rt, {})[ck] = matrix.setdefault(rt, {}).get(ck, 0) + val
        row_tot[rt] = row_tot.get(rt, 0) + val
        if col_fields:
            col_tot[ck]    = col_tot.get(ck, 0) + val
            col_labels[ck] = ct_labels
        grand += val

    ordered_cols = sorted(col_tot.keys(), key=lambda c: col_tot[c], reverse=True)
    ordered_rows = sorted(row_tot.keys(), key=lambda r: row_tot[r], reverse=True)[:limit]

    out_columns = [{'key': ck, 'labels': col_labels[ck]} for ck in ordered_cols]
    out_rows = []
    for rt in ordered_rows:
        cell = {'dims': list(rt), '_total': row_tot[rt]}
        if col_fields:
            cell['values'] = {ck: matrix[rt].get(ck, 0) for ck in ordered_cols}
        out_rows.append(cell)

    totals = {ck: col_tot[ck] for ck in ordered_cols}
    totals['_total'] = grand

    return {
        'row_dims':      [{'key': k, 'label': dims[k][1]} for k in rows],
        'col_dims':      [{'key': k, 'label': dims[k][1]} for k in cols],
        'measure_label': measure_label,
        'columns':       out_columns,
        'rows':          out_rows,
        'totals':        totals,
        'grand_total':   grand,
    }


def build_pivot(source='prescriptions', row=None, col=None,
                measure='net', filters=None, limit=200):
    """
    Build a pivot result.

    Args:
        source   : 'prescriptions' | 'lines'
        row      : row-dimension key (required)
        col      : optional column-dimension key (→ cross-tab)
        measure  : measure key
        filters  : dict — claim_id / client_id / subclient_id / date_from / date_to
        limit    : max row groups returned (safety cap)

    Returns dict:
        {
          'row_label', 'col_label', 'measure_label',
          'columns': [ {key,label} ... ]   # for cross-tab; [] for simple
          'rows':    [ {dimension, <colkey>:value ..., _total} ... ],
          'totals':  { <colkey>:value ..., _total },
          'grand_total': number,
        }
    """
    filters = filters or {}
    dims = _dims_for(source)
    meas = _measures_for(source)

    if row not in dims:
        raise ValueError(f'بُعد الصفوف غير صالح: {row}')
    if col is not None and col not in dims:
        raise ValueError(f'بُعد الأعمدة غير صالح: {col}')
    if measure not in meas:
        raise ValueError(f'المقياس غير صالح: {measure}')

    measure_label, measure_fn = meas[measure]
    qs = _base_queryset(source, filters)

    # ── Apply row (and optional col) grouping ────────────────────────────────
    qs, row_field = _annotate_dim(qs, row, source, '_row')
    group_fields = [row_field]
    col_field = None
    if col:
        qs, col_field = _annotate_dim(qs, col, source, '_col')
        group_fields.append(col_field)

    agg = (
        qs.values(*group_fields)
          .annotate(_value=measure_fn())
          .order_by()
    )

    # ── Shape output ──────────────────────────────────────────────────────────
    def _norm(v):
        if v is None:
            return '—'
        # Truncated dates → ISO month/day string
        if hasattr(v, 'isoformat'):
            return v.isoformat()[:10]
        return str(v)

    def _num(v):
        if isinstance(v, Decimal):
            return float(v)
        return v or 0

    row_label = dims[row][1]
    col_label = dims[col][1] if col else None

    if not col:
        # Simple summary
        rows = []
        grand = 0
        for r in agg:
            val = _num(r['_value'])
            grand += val
            rows.append({'dimension': _norm(r[row_field]), '_total': val})
        rows.sort(key=lambda x: x['_total'], reverse=True)
        rows = rows[:limit]
        return {
            'row_label':     row_label,
            'col_label':     None,
            'measure_label': measure_label,
            'columns':       [],
            'rows':          rows,
            'totals':        {'_total': grand},
            'grand_total':   grand,
        }

    # Cross-tab: collect distinct column values + matrix
    matrix = {}          # row_val → {col_val → value}
    col_keys = {}        # col_val → total (for ordering)
    row_totals = {}      # row_val → total
    grand = 0
    for r in agg:
        rv  = _norm(r[row_field])
        cv  = _norm(r[col_field])
        val = _num(r['_value'])
        matrix.setdefault(rv, {})[cv] = val
        col_keys[cv]   = col_keys.get(cv, 0) + val
        row_totals[rv] = row_totals.get(rv, 0) + val
        grand += val

    # Order columns by total desc, rows by total desc
    ordered_cols = sorted(col_keys.keys(), key=lambda c: col_keys[c], reverse=True)
    ordered_rows = sorted(row_totals.keys(), key=lambda r: row_totals[r], reverse=True)[:limit]

    columns = [{'key': c, 'label': c} for c in ordered_cols]
    rows = []
    for rv in ordered_rows:
        cell = {'dimension': rv, '_total': row_totals[rv]}
        for c in ordered_cols:
            cell[c] = matrix[rv].get(c, 0)
        rows.append(cell)

    totals = {c: col_keys[c] for c in ordered_cols}
    totals['_total'] = grand

    return {
        'row_label':     row_label,
        'col_label':     col_label,
        'measure_label': measure_label,
        'columns':       columns,
        'rows':          rows,
        'totals':        totals,
        'grand_total':   grand,
    }
