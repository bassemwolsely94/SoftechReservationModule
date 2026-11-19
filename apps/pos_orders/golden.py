"""
apps/pos_orders/golden.py — field-by-field comparison of a NATIVE SOFTECH pending sale with the rows our
writer produces for the same basket (doc 39 §4.1, the "POS writer golden-template verify" method).

Pure: no database, no SOFTECH. The command `pos_checkout_golden` reads both sides (the native rows, and
the probe rows inside a transaction that is always rolled back) and hands them here.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

TABLES = ('stktransm5', 'stktrans5', 'branchesales5', 'companiesitems5', 'branchesalescc5')

# Columns that differ between ANY two sales by construction — reported as "expected", never as a fail.
EXPECTED_DIFFERENT = {
    '*': {'docnumber', 'docdate', 'trans_time', 's_docdate', 'table_dumped', 'r_docdate'},
    'stktransm5': {'vf2', 'hour_of_day', 'docnumber2'},       # vf2 = our 'POS<pk>' idempotency tag
    'branchesales5': {'paymentsno', 'ref_docnumber'},
    'stktrans5': set(),
    'companiesitems5': {'cdate'},
    'branchesalescc5': set(),
}


def _norm(v):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        try:
            return v.decode('cp1256').strip()
        except Exception:
            return v.hex()
    if isinstance(v, str):
        s = v.strip()
        try:
            return Decimal(s) if s and s.replace('.', '', 1).lstrip('-').isdigit() else s
        except InvalidOperation:
            return s
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        try:
            return Decimal(str(v)).normalize()
        except InvalidOperation:
            return v
    return v


def _same(a, b):
    a, b = _norm(a), _norm(b)
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a.compare(b) == 0
    if a in ('', None) and b in ('', None):
        return True
    return a == b


def _expected(table, col):
    return col in EXPECTED_DIFFERENT['*'] or col in EXPECTED_DIFFERENT.get(table, set())


def _key(table, row, i):
    if table == 'stktrans5':
        return f"line {i + 1} · {str(row.get('itemcode') or '').strip()}"
    if table == 'branchesales5':
        return f"payment {i + 1} · type {str(row.get('paymenttype') or '').strip()}"
    return f'row {i + 1}'


def _order_rows(table, rows):
    if table == 'stktrans5':
        return sorted(rows, key=lambda r: (str(r.get('itemcode') or '').strip(), str(r.get('dblitemflag') or '')))
    if table == 'branchesales5':
        return sorted(rows, key=lambda r: (str(r.get('paymenttype') or '').strip(), str(r.get('paymentvalue'))))
    return list(rows)


def diff_tables(native: dict, probe: dict, *, also_ignore=()):
    """native / probe: {table: [row dict, ...]}. Returns {'fails': [...], 'expected': [...],
    'row_count': [...]} where each item is (table, row, column, native value, probe value).
    Every column present on either side is compared — nothing is skipped silently."""
    out = {'fails': [], 'expected': [], 'row_count': []}
    extra = set(also_ignore)
    for table in TABLES:
        n_rows = _order_rows(table, native.get(table) or [])
        p_rows = _order_rows(table, probe.get(table) or [])
        if len(n_rows) != len(p_rows):
            out['row_count'].append((table, '', 'rows', len(n_rows), len(p_rows)))
        for i in range(max(len(n_rows), len(p_rows))):
            n = n_rows[i] if i < len(n_rows) else {}
            p = p_rows[i] if i < len(p_rows) else {}
            key = _key(table, n or p, i)
            for col in sorted(set(n) | set(p)):
                a, b = n.get(col), p.get(col)
                if _same(a, b):
                    continue
                item = (table, key, col, _norm(a), _norm(b))
                if _expected(table, col) or col in extra:
                    out['expected'].append(item)
                else:
                    out['fails'].append(item)
    return out


def report_markdown(title, diff, *, notes=()):
    """The 39a report section for one basket."""
    def _rows(items):
        lines = ['| table | row | column | native | ours |', '|---|---|---|---|---|']
        lines += [f'| {t} | {k} | `{c}` | {a} | {b} |' for t, k, c, a, b in items]
        return lines

    ok = not diff['fails'] and not diff['row_count']
    md = [f'### {title} — {"PASS" if ok else "DIFFERENCES"}', '']
    md += [f'- {n}' for n in notes]
    if diff['row_count']:
        md += ['', '**Row counts differ:**', ''] + _rows(diff['row_count'])
    if diff['fails']:
        md += ['', '**Fields that differ (must be explained before rollout):**', ''] + _rows(diff['fails'])
    if diff['expected']:
        md += ['', '<details><summary>Expected differences (serial, dates, our vf2 tag)</summary>', '']
        md += _rows(diff['expected']) + ['', '</details>']
    return '\n'.join(md) + '\n'
