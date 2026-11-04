"""Sales readers: ``sales_tenders`` (branch-day-tender) and ``credit_sales`` (one doc per credit invoice)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from apps.finance.queries import sybase_gl

from . import READERS, SourceDoc

CENT = Decimal('0.01')
TENDER_KINDS = {'30': 'cash', '40': 'card', '60': 'change_discount'}


def q(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def code(v) -> str:
    """'1234.0' -> '1234'; None -> ''."""
    s = str(v if v is not None else '').strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


def to_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def read_sales_tenders(date_from, date_to, fetch):
    acc: dict = {}
    for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
        for r in fetch(sybase_gl.sql_branchesales(d1, d2)):
            pt = code(r['paymenttype'])
            d = to_date(r['docdate'])
            if pt == '10' or not (d1 <= d <= d2):
                continue
            slot = acc.setdefault((code(r['branchcode']), d, pt), {'sales': Decimal(0), 'returns': Decimal(0)})
            slot['returns' if code(r['doccode']) == '30' else 'sales'] += Decimal(str(r['s'] or 0))
    for (branch, d, pt), v in sorted(acc.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
        sales, returns = q(v['sales']), q(v['returns'])
        yield SourceDoc('sales_tenders', f'bs:{branch}:{d.isoformat()}:{pt}', d, branch,
                        TENDER_KINDS.get(pt, f'pt{pt}'), '',
                        {'sales': sales, 'returns': returns, 'net': sales - returns}, {'paymenttype': pt})


def read_credit_sales(date_from, date_to, fetch):
    for d1, d2 in sybase_gl.month_chunks(date_from, date_to):
        for r in fetch(sybase_gl.sql_credit_docs(d1, d2)):
            d = to_date(r['docdate'])
            if not (d1 <= d <= d2):
                continue
            branch, doccode, num = code(r['branchcode']), code(r['doccode']), code(r['docnumber'])
            sign = -1 if doccode == '30' else 1
            credit = Decimal(str(r['credit'] or 0))
            value = Decimal(str(r['docvalue'] or 0))
            if value == 0:
                gross, tax = credit, Decimal(0)
            else:
                gross = credit * Decimal(str(r['docvalue1'] or 0)) / value
                tax = credit * Decimal(str(r['docvalue3'] or 0)) / value
            gross_q = q(gross) * sign
            credit_q = q(credit) * sign
            pmin, pmax = code(r['pmin']), code(r['pmax'])
            attrs = {'doccode': doccode, 'docnumber': num}
            if pmin != pmax:
                attrs['mixed_personcodes'] = [pmin, pmax]
            yield SourceDoc('credit_sales', f'cs:{branch}:{doccode}:{num}:{d.isoformat()}', d, branch,
                            'return' if sign < 0 else 'sale', pmin if pmin == pmax else '',
                            {'credit': credit_q, 'gross_share': gross_q, 'discount_share': gross_q - credit_q,
                             'tax_share': q(tax) * sign},
                            attrs)


READERS['sales_tenders'] = read_sales_tenders
READERS['credit_sales'] = read_credit_sales
