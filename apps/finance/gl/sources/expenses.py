"""``expenses`` reader: SOFTECH dailyexpenses rows, one doc per (branch, date, interval, day_sno)."""
from apps.finance.queries import sybase_gl

from . import READERS, SourceDoc
from .sales import code, q, to_date


def read_expenses(date_from, date_to, fetch):
    seen: dict = {}
    dup: set = set()
    order = []
    for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
        for r in fetch(sybase_gl.sql_expenses(d1, d2)):
            d = to_date(r['expensedate'])
            if not (d1 <= d <= d2):
                continue
            branch = code(r['branchcode'])
            key = f"exp:{branch}:{d.isoformat()}:{code(r['intervalcode'])}:{code(r['day_sno'])}:{code(r.get('cheqsno'))}"
            if key in seen:
                dup.add(key)
                continue
            expcode = code(r['expcode'])
            v_date = r.get('v_cheqdate')
            linked = sybase_gl.expense_voucher_linked(
                code(r.get('v_personcode')), to_date(v_date) if v_date else None, d)
            bankcode = code(r.get('bankcode')) if linked else ''   # Ruling P20: no voucher -> unmapped
            seen[key] = SourceDoc('expenses', key, d, branch, expcode, '', {'amount': q(r['expvalue'])},
                                  {'expcode': expcode, 'bankcode': bankcode,
                                   'cheqsno': code(r.get('cheqsno')), 'comment': (r.get('expcomment') or '').strip()})
            order.append(key)
    for key in order:
        base = seen[key]
        if key in dup:   # never merge: surface the clash so the engine raises an exception
            yield SourceDoc('expenses', key, base.doc_date, base.branch_code, '__duplicate__', '', {},
                            {'expcode': base.attrs['expcode']})
        else:
            yield base


READERS['expenses'] = read_expenses
