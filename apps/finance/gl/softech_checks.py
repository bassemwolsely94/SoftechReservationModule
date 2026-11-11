"""SOFTECH side of the ledger comparison (finance-gl Plan 3, Task 4). Read-only.

Each source answers ``(period) -> {(branch_code | None, party_code | ''): Decimal}`` (the SOFTECH figure in the
check's own sign: what the ledger should show) and ``detail(period, branch_code, party_code='') -> [dict]``
(rows with at least ``date`` and ``amount``, ``amount`` summing to the figure; a stock check has ``date`` only as
the snapshot). ``branch_code=None`` in ``detail`` means the codes that map to no ``Branch``.

SOFTECH is reached only through ``sybase_gl`` / ``sybase_accounting`` (SELECT-only), imported lazily: nothing
under ``gl/`` imports ``config.sybase`` at load.
"""
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger('elrezeiky.finance')

ZERO = Decimal('0.00')


def _sybase_gl():
    from apps.finance.queries import sybase_gl   # lazy: gl/ never imports config.sybase at load
    return sybase_gl


def _sybase_accounting():
    from apps.finance.queries import sybase_accounting
    return sybase_accounting


def _dec(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


def _code(v) -> str:
    return str(v if v is not None else '').strip()


def _day(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v).strip()[:10])


def _known_codes() -> set:
    from apps.branches.models import Branch
    return set(Branch.objects.values_list('softech_branch_id', flat=True))


def _wanted(code: str, branch_code, known: set) -> bool:
    """`branch_code` is a Branch code or None (= every code with no Branch)."""
    return code == branch_code if branch_code is not None else code not in known


def _sum_by_branch(rows, branch_key, amount_key) -> dict:
    out: dict = {}
    for r in rows:
        k = (_code(r[branch_key]) or None, '')
        out[k] = out.get(k, ZERO) + _dec(r[amount_key])
    return out


# ── sales ────────────────────────────────────────────────────────────────────────────────────────────
def sales(period) -> dict:
    rows = _sybase_gl().sales_net_by_day(period.period_start, period.period_end)
    return _sum_by_branch(rows, 'branchcode', 'net')


def sales_detail(period, branch_code, party_code='') -> list:
    known = _known_codes()
    rows = _sybase_gl().sales_net_by_day(period.period_start, period.period_end)
    return sorted(({'date': _day(r['docdate']), 'branch_code': _code(r['branchcode']), 'amount': _dec(r['net'])}
                   for r in rows if _wanted(_code(r['branchcode']), branch_code, known)),
                  key=lambda d: d['date'])


# ── purchases (Postgres mirror of doccode 10 / 120) ──────────────────────────────────────────────────
def _invoices(period):
    from apps.finance.models import APInvoice
    return APInvoice.objects.filter(party_type='supplier', doccode__in=('10', '120'),
                                    docdate__gte=period.period_start, docdate__lte=period.period_end)


def purchases(period) -> dict:
    out: dict = {}
    for i in _invoices(period).only('branchcode', 'doccode', 'doc_value'):
        k = (_code(i.branchcode) or None, '')
        out[k] = out.get(k, ZERO) + (-i.doc_value if i.doccode == '120' else i.doc_value)
    return out


def purchases_detail(period, branch_code, party_code='') -> list:
    known = _known_codes()
    rows = []
    for i in _invoices(period).select_related('party').order_by('docdate', 'docnumber'):
        if not _wanted(_code(i.branchcode), branch_code, known):
            continue
        rows.append({'date': i.docdate, 'branch_code': _code(i.branchcode), 'doccode': i.doccode,
                     'docnumber': i.docnumber, 'party': i.party.name,
                     'amount': -i.doc_value if i.doccode == '120' else i.doc_value})
    return rows


# ── stock at cost ────────────────────────────────────────────────────────────────────────────────────
def stock_at_cost(period) -> dict:
    from .softech_stock import valuation
    out: dict = {}
    for s in valuation(period.period_end).stores:
        if s['included']:
            k = (_code(s['branch_code']) or None, '')
            out[k] = out.get(k, ZERO) + _dec(s['value'])
    return out


def stock_at_cost_detail(period, branch_code, party_code='') -> list:
    from .softech_stock import valuation
    known = _known_codes()
    return [{'date': s['snapshot_date'], 'store_code': s['store_code'], 'store_name': s['store_name'],
             'rows': s['rows'], 'carried': s['carried'], 'amount': _dec(s['value'])}
            for s in valuation(period.period_end).stores
            if s['included'] and _wanted(_code(s['branch_code']), branch_code, known)]


# ── expenses ─────────────────────────────────────────────────────────────────────────────────────────
def expenses(period) -> dict:
    rows = _sybase_accounting().get_dailyexpenses_by_branch_month(period.year, period.month)
    if any('_error' in r for r in rows):
        logger.error('dailyexpenses read failed: %s', rows[0]['_error'])
        raise RuntimeError('تعذرت قراءة المصروفات من SOFTECH')
    return _sum_by_branch(rows, 'branchcode', 'total_expenses')


def expenses_detail(period, branch_code, party_code='') -> list:
    known = _known_codes()
    rows = _sybase_gl().expense_rows(period.period_start, period.period_end)
    return sorted(({'date': _day(r['expensedate']), 'branch_code': _code(r['branchcode']),
                    'expcode': _code(r['expcode']), 'note': _code(r['expcomment']), 'amount': _dec(r['expvalue'])}
                   for r in rows if _wanted(_code(r['branchcode']), branch_code, known)),
                  key=lambda d: d['date'])


# ── supplier balances (owed, per GL party) ───────────────────────────────────────────────────────────
def _recon_party(personcode):
    from apps.finance.models import ReconParty
    return ReconParty.objects.filter(softech_personcode=personcode).first()


def supplier_balance(period) -> dict:
    from apps.finance.models import ReconParty
    from apps.finance.recon_balances import ap_balances_as_of
    from . import plan2_adapter
    codes = plan2_adapter.all_party_personcodes('supplier')
    parties = {p.softech_personcode: p
               for p in ReconParty.objects.filter(softech_personcode__in=list(codes.values()))}
    balances = ap_balances_as_of(parties.values(), period.period_end)
    out: dict = {}
    for gl_code, personcode in codes.items():
        party = parties.get(personcode)
        bal = balances.get(party.pk) if party else None
        if bal is not None:
            out[(None, gl_code)] = bal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return out


def supplier_balance_detail(period, branch_code, party_code='') -> list:
    from apps.finance.recon_balances import ap_balance_as_of
    from . import plan2_adapter
    personcode = plan2_adapter.party_personcodes([party_code]).get(party_code)
    party = _recon_party(personcode) if personcode else None
    if party is None:
        return []
    start_day = date.fromordinal(period.period_start.toordinal() - 1)
    rows = []
    opening = ap_balance_as_of(party, start_day)
    if opening is not None:
        rows.append({'date': start_day, 'kind': 'opening', 'ref': '', 'amount': opening})
    for i in party.invoices.filter(docdate__gte=period.period_start, docdate__lte=period.period_end):
        rows.append({'date': i.docdate, 'kind': 'return' if i.is_return else 'invoice',
                     'ref': f'{i.doccode}/{i.branchcode}/{i.docnumber}',
                     'amount': -i.doc_value if i.is_return else i.doc_value})
    for p in party.payments.filter(voucher_date__gte=period.period_start, voucher_date__lte=period.period_end):
        rows.append({'date': p.voucher_date, 'kind': 'payment', 'ref': f'{p.branchcode}/{p.cheqsno}',
                     'amount': -p.amount})
    return sorted(rows, key=lambda r: r['date'])


# explicit: the source key is a database value (editable with ledger.edit); late-bound so tests can patch
SOURCES = {
    'sales': (lambda p: sales(p), lambda *a: sales_detail(*a)),
    'purchases': (lambda p: purchases(p), lambda *a: purchases_detail(*a)),
    'stock_at_cost': (lambda p: stock_at_cost(p), lambda *a: stock_at_cost_detail(*a)),
    'expenses': (lambda p: expenses(p), lambda *a: expenses_detail(*a)),
    'supplier_balance': (lambda p: supplier_balance(p), lambda *a: supplier_balance_detail(*a)),
}


def _source(key):
    try:
        return SOURCES[key]
    except KeyError:
        raise ValueError(f'مصدر مقارنة غير معروف: {key}') from None


def figures(source: str, period) -> dict:
    return _source(source)[0](period)


def detail(source: str, period, branch_code, party_code='') -> list:
    return _source(source)[1](period, branch_code, party_code)
