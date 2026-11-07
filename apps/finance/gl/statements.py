"""Financial statements over the ledger (finance-gl Task 7) — Egyptian layout as finance's sheets.

* trading_and_pl  — «الختامية»: trading account + profit & loss for a date range.
* financial_position — «الميزانية»: statement of financial position at a date.
* branch_pl — «الختامية فروع بالتوزيع»: per-branch P&L with HQ costs allocated by sales share.
* comparison — «الختامية المجمعة»: trading_and_pl per calendar year with % of sales.

All figures come from approved + reversed entries (same counting rule as balances.py), keyed by
GLAccount.statement_line.  Signs: asset/expense lines = Σdebit − Σcredit; liability/equity/revenue
lines = −(Σdebit − Σcredit).  Everything here is read-only: nothing is posted.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum
from django.utils import timezone

from apps.branches.models import Branch

from .balances import _base
from .names import normalize_ar

ZERO = Decimal('0.00')
_CENT = Decimal('0.01')
_RATIO = Decimal('0.000001')

TRADING_PL_SECTIONS = ('trading', 'pl')
BANK_GROUP = normalize_ar('النقديه بالبنوك')
RETAINED = '2409'

# P&L expense lines in the order of finance's sheet; allocated from HQ in branch_pl.
EXPENSE_LINES = ('general_expenses', 'selling_expenses', 'depreciation',
                 'operating_expenses', 'financing_expenses')
REVENUE_LINES = ('other_revenue', 'capital_gains')
TRADING_LINES = ('opening_stock', 'net_purchases', 'net_sales', 'closing_stock')
PL_KNOWN = set(EXPENSE_LINES) | set(REVENUE_LINES) | set(TRADING_LINES)

# Labels as on finance's «الختامية» sheet (Arabic first).
LABELS = {
    'opening_stock': 'رصيد اول المدة', 'net_purchases': 'صافى المشتريات',
    'net_sales': 'صافى المبيعات', 'closing_stock': 'رصيد اخر المدة',
    'cost_of_sales': 'تكلفة المبيعات', 'gross_profit': 'مجمل الربح',
    'general_expenses': 'المصاريف العمومية', 'selling_expenses': 'مصاريف البيع والتوزيع',
    'depreciation': 'الاهلاكات', 'operating_expenses': 'مصاريف التشغيل',
    'financing_expenses': 'المصاريف التمويلية', 'other_revenue': 'ايرادات',
    'capital_gains': 'ارباح راسمالية بيع اصول', 'net_profit': 'صافى الارباح',
    'total_expenses': 'اجمالى المصاريف', 'unclassified': 'حسابات بدون بند',
    'softech_sales': 'مبيعات سوفتيك', 'softech_cost': 'تكلفة المبيعات بنسبة سوفتيك',
    'softech_gross_profit': 'مجمل الربح بسوفتيك',
}


def _q(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


def _ratio(num: Decimal, den: Decimal) -> Decimal | None:
    if not den:
        return None
    return (num / den).quantize(_RATIO, rounding=ROUND_HALF_UP)


def _months(date_from: datetime.date, date_to: datetime.date) -> int:
    return max(1, (date_to.year - date_from.year) * 12 + date_to.month - date_from.month + 1)


def _line_branch_id(row) -> int | None:
    return row['branch_id'] if row['branch_id'] is not None else row['entry__branch_id']


def _signed_by_line(qs) -> dict[str, Decimal]:
    """statement_line -> Σdebit − Σcredit over trading/P&L accounts ('' = no line)."""
    out: dict[str, Decimal] = {}
    for r in (qs.filter(account__group__section__in=TRADING_PL_SECTIONS)
                .values('account__statement_line')
                .annotate(d=Sum('debit'), c=Sum('credit'))):
        line = r['account__statement_line'] or ''
        if line not in PL_KNOWN:
            line = ''
        out[line] = out.get(line, ZERO) + (r['d'] or ZERO) - (r['c'] or ZERO)
    return out


def _pl_from_signed(signed: dict[str, Decimal], months: int) -> dict:
    """Build the «الختامية» figures from signed statement-line balances."""
    g = lambda k: signed.get(k, ZERO)  # noqa: E731
    r = {
        'opening_stock': g('opening_stock'),
        'net_purchases': g('net_purchases'),
        'closing_stock': -g('closing_stock'),
        'net_sales': -g('net_sales'),
        'other_revenue': -g('other_revenue'),
        'capital_gains': -g('capital_gains'),
        **{k: g(k) for k in EXPENSE_LINES},
        'unclassified': g(''),  # signed: debit positive (reduces profit)
    }
    r['cost_of_sales'] = r['opening_stock'] + r['net_purchases'] - r['closing_stock']
    r['gross_profit'] = r['net_sales'] - r['cost_of_sales']
    r['total_expenses'] = sum((r[k] for k in EXPENSE_LINES), ZERO)
    r['expenses_ex_depreciation'] = r['total_expenses'] - r['depreciation']
    r['net_profit'] = (r['gross_profit'] + r['other_revenue'] + r['capital_gains']
                       - r['total_expenses'] - r['unclassified'])
    sales = r['net_sales']
    r['months'] = months
    r['gross_margin'] = _ratio(r['gross_profit'], sales)
    r['net_margin'] = _ratio(r['net_profit'], sales)
    r['net_margin_ex_depreciation'] = _ratio(r['net_profit'] + r['depreciation'], sales)
    # finance's «نسبة المصاريف لصافى المبيعات» excludes depreciation
    r['expense_ratio'] = _ratio(r['expenses_ex_depreciation'], sales)
    r['monthly_avg_sales'] = _q(sales / months)
    r['monthly_avg_expenses'] = _q(r['expenses_ex_depreciation'] / months)
    r['monthly_avg_net_profit'] = _q(r['net_profit'] / months)
    return r


def _range_qs(date_from, date_to, branch_id=None):
    return _base(branch_id).filter(entry__entry_date__gte=date_from,
                                   entry__entry_date__lte=date_to)


STOCK_ENTRIES, STOCK_SUPPLIED, STOCK_MISSING = 'entries', 'supplied', 'missing'
WARN_NO_CLOSING = ('لا يوجد مخزون آخر المدة لهذه الفترة (لا قيد على 5302 ولا قيمة مُدخلة): '
                   'تكلفة المبيعات ومجمل الربح وصافي الربح غير مكتملة.')
WARN_NO_OPENING = ('الفترة لا تشمل قيد مخزون أول المدة (5301)، فرصيد أول المدة = صفر: '
                   'تكلفة المبيعات ومجمل الربح لا تعبّر عن الفترة.')


def _line_exists(qs, line: str) -> bool:
    return qs.filter(account__statement_line=line).exists()


def _stock_basis(qs, closing_stock):
    """(basis, warnings) for the closing/opening stock behind a range queryset."""
    warnings = []
    if closing_stock is not None:
        basis = STOCK_SUPPLIED
    elif _line_exists(qs, 'closing_stock'):
        basis = STOCK_ENTRIES
    else:
        basis = STOCK_MISSING
        warnings.append(WARN_NO_CLOSING)
    if not _line_exists(qs, 'opening_stock'):
        warnings.append(WARN_NO_OPENING)
    return basis, warnings


def trading_and_pl(date_from: datetime.date, date_to: datetime.date, *,
                   branch_id: int | None = None,
                   closing_stock: Decimal | None = None) -> dict:
    """Trading account + P&L for [date_from, date_to].

    Closing stock = credit balance of 5302 (line closing_stock) in range, unless `closing_stock`
    is supplied: then the 5302 entries are ignored and the supplied value is used.
    `stock_basis` in entries | supplied | missing; `warnings` (Arabic) flag a missing closing
    stock and a range without the opening-stock (5301) entry.
    """
    qs = _range_qs(date_from, date_to, branch_id)
    basis, warnings = _stock_basis(qs, closing_stock)
    signed = _signed_by_line(qs)
    if closing_stock is not None:
        signed['closing_stock'] = -Decimal(closing_stock)
    r = _pl_from_signed(signed, _months(date_from, date_to))
    r['stock_basis'] = basis
    r['warnings'] = warnings
    return r


def financial_position(as_of: datetime.date, *, closing_stock_from_entries: bool = True,
                       closing_stock: Decimal | None = None) -> dict:
    """Statement of financial position at `as_of`.

    `unclosed_pl` is every unclosed trading/P&L balance to `as_of` as a profit (= the current
    year's net profit once earlier years are closed into 2409); `net_profit` is kept as an alias.
    Using all unclosed balances keeps `check` at 0 whenever the ledger balances.
    When `closing_stock` is supplied (required with closing_stock_from_entries=False), the
    closing-stock entries (lines inventory / closing_stock) are ignored and the supplied value
    is used for both inventory and the result, so `check` stays 0.
    `stock_basis` / `warnings` as in trading_and_pl, judged over 1-1 of as_of's year .. as_of.
    """
    if not closing_stock_from_entries and closing_stock is None:
        raise ValueError('closing_stock is required when closing_stock_from_entries=False')
    year_qs = _range_qs(datetime.date(as_of.year, 1, 1), as_of)
    basis, warnings = _stock_basis(year_qs, closing_stock)
    qs = _base().filter(entry__entry_date__lte=as_of)
    if closing_stock is not None:
        qs = qs.exclude(account__statement_line__in=('inventory', 'closing_stock'))
    rows = (qs.values('account__code', 'account__statement_line', 'account__group__name',
                      'account__group__section')
              .annotate(d=Sum('debit'), c=Sum('credit')))
    bs: dict[str, Decimal] = {}
    pl_signed = ZERO
    balance_2409 = ZERO
    unclassified = ZERO
    for r in rows:
        bal = (r['d'] or ZERO) - (r['c'] or ZERO)
        if r['account__group__section'] in TRADING_PL_SECTIONS:
            pl_signed += bal
            continue
        line = r['account__statement_line'] or ''
        if r['account__code'] == RETAINED or line == 'retained':
            balance_2409 += bal
            continue
        if line == 'cash' and bal < 0 and normalize_ar(r['account__group__name']) == BANK_GROUP:
            line = 'overdraft'
        if line not in _BS_SIGN:
            unclassified += bal
            continue
        bs[line] = bs.get(line, ZERO) + bal

    if closing_stock is not None:
        closing_stock = Decimal(closing_stock)
        bs['inventory'] = bs.get('inventory', ZERO) + closing_stock
        pl_signed -= closing_stock
    v = {k: bs.get(k, ZERO) * s + 0 for k, s in _BS_SIGN.items()}  # + 0: no -0.00
    r = dict(v)
    r['net_fixed_assets'] = v['fixed_assets'] - v['accumulated_depreciation']
    r['total_current_assets'] = sum((v[k] for k in CURRENT_ASSETS), ZERO)
    r['total_current_liabilities'] = sum((v[k] for k in CURRENT_LIABILITIES), ZERO)
    r['working_capital'] = r['total_current_assets'] - r['total_current_liabilities']
    r['unclassified'] = unclassified  # signed balance of BS accounts with no known line
    r['total_investment'] = r['net_fixed_assets'] + r['working_capital'] + unclassified
    r['retained_balance'] = balance_2409
    r['unclosed_pl'] = -pl_signed + 0
    r['net_profit'] = r['unclosed_pl']  # backward-compatible alias of unclosed_pl
    r['profit_and_loss'] = -(balance_2409 + pl_signed)
    r['total_equity'] = v['capital'] + v['partners'] + r['profit_and_loss']
    r['check'] = r['total_investment'] - r['total_equity']
    r['stock_basis'] = basis
    r['warnings'] = warnings
    return r


CURRENT_ASSETS = ('inventory', 'receivables', 'other_debtors', 'deposits', 'cash')
CURRENT_LIABILITIES = ('creditors', 'overdraft', 'notes_payable', 'suppliers')
_BS_SIGN = {
    'fixed_assets': 1, 'accumulated_depreciation': -1,
    **{k: 1 for k in CURRENT_ASSETS},
    **{k: -1 for k in CURRENT_LIABILITIES},
    'capital': -1, 'partners': -1,
}


# Every statement line an account may carry (PATCH accounts/ validates against it).
KNOWN_LINES = frozenset(PL_KNOWN | set(_BS_SIGN) | {'retained'})


def _allocate(amount: Decimal, shares: dict[int, Decimal]) -> dict[int, Decimal]:
    """round(share / total × amount, 2) half-up; the remainder goes to the largest share.

    Shares may be negative (HQ net sales can be); keys may be None (HQ)."""
    total = sum(shares.values(), ZERO)
    if not shares or total == 0 or amount == 0:
        return {k: ZERO for k in shares}
    out = {k: _q(s / total * amount) for k, s in shares.items()}
    largest = max(shares, key=lambda k: (shares[k], str(k)))
    out[largest] += amount - sum(out.values(), ZERO)
    return out


def branch_pl(date_from: datetime.date, date_to: datetime.date, *,
              allocation_basis: str = 'sales', today: datetime.date | None = None) -> list[dict]:
    """One column per branch (HQ first) + total; report-time HQ allocation, posts nothing.

    HQ = lines with no branch (line or entry header) or whose branch is kind HQ.  HQ expense
    lines (EXPENSE_LINES) are allocated across ALL columns, HQ included, by net-sales share, as
    finance's «الختامية فروع بالتوزيع» does (ruling R13); HQ's net sales may be negative, giving
    it a negative share.  HQ's own sales, cost of sales and revenue stay in the HQ column.  Each
    column carries the figures before allocation at top level, `allocation` (line → amount; on
    HQ = its own share − the HQ amount, so the allocations sum to 0) and `after`.  With zero
    total sales nothing is allocated.  The softech_* lines are SOFTECH's own figures, separate from
    the ledger (Ruling P34, _softech_lines); a branch with SOFTECH figures and no ledger line still
    gets a column.  `today` decides which months have started (tests inject it).
    """
    if allocation_basis != 'sales':
        raise ValueError(f'unknown allocation basis {allocation_basis!r}')
    rows = (_range_qs(date_from, date_to)
            .filter(account__group__section__in=TRADING_PL_SECTIONS)
            .values('branch_id', 'entry__branch_id', 'account__statement_line')
            .annotate(d=Sum('debit'), c=Sum('credit')))
    per: dict[int | None, dict[str, Decimal]] = {}
    raw = list(rows)
    ids = {_line_branch_id(r) for r in raw} - {None}
    branches = {b.pk: b for b in Branch.objects.filter(pk__in=ids)}
    hq_ids = {pk for pk, b in branches.items() if b.kind == Branch.KIND_HQ}
    for r in raw:
        bid = _line_branch_id(r)
        key = None if bid is None or bid in hq_ids else bid
        line = r['account__statement_line'] or ''
        if line not in PL_KNOWN:
            line = ''
        slot = per.setdefault(key, {})
        slot[line] = slot.get(line, ZERO) + (r['d'] or ZERO) - (r['c'] or ZERO)
    per.setdefault(None, {})
    per_code, missing = _softech_rows(date_from, date_to, today or timezone.localdate())
    by_code = {(b.softech_branch_id or '').strip(): b for b in Branch.objects.all()}
    hq_codes = {c for c, b in by_code.items() if b.kind == Branch.KIND_HQ}
    if not hq_codes and HQ_CODE not in by_code:
        hq_codes = {HQ_CODE}
    for softech_code in per_code:
        b = by_code.get(softech_code)
        if b is not None and b.kind != Branch.KIND_HQ:
            branches.setdefault(b.pk, b)
            per.setdefault(b.pk, {})
    months = _months(date_from, date_to)

    def order(k):
        sid = (branches[k].softech_branch_id or '').strip()
        return (0, int(sid), k) if sid.isdigit() else (1, sid, k)

    branch_keys = sorted((k for k in per if k is not None), key=order)
    keys = [None, *branch_keys]
    sales = {k: -per[k].get('net_sales', ZERO) for k in keys}
    allocation: dict[int | None, dict[str, Decimal]] = {k: {} for k in keys}
    for line in EXPENSE_LINES:
        hq_amount = per[None].get(line, ZERO)
        split = _allocate(hq_amount, sales)
        if sum(split.values(), ZERO) != hq_amount:  # zero total sales: nothing allocated
            split = {k: ZERO for k in keys}
            split[None] = hq_amount
        for k in keys:
            allocation[k][line] = split[k]
        allocation[None][line] = split[None] - hq_amount

    def column(key, name, is_hq):
        signed = per.get(key, {})
        after = dict(signed)
        for line, amt in allocation[key].items():
            after[line] = after.get(line, ZERO) + amt
        hq_branch = next((branches[i] for i in sorted(hq_ids)), None) if is_hq else None
        return {'branch_id': key if not is_hq else (hq_branch.pk if hq_branch else None),
                'name': name, 'is_hq': is_hq, 'is_total': False,
                **_pl_from_signed(signed, months),
                'allocation': {ln: allocation[key].get(ln, ZERO) for ln in EXPENSE_LINES},
                'after': _pl_from_signed(after, months)}

    hq_name = next((branches[i].name for i in sorted(hq_ids)), 'الرئيسى')
    cols = [column(None, hq_name, True)]
    cols += [column(k, branches[k].name, False) for k in branch_keys]
    consolidated = trading_and_pl(date_from, date_to)
    cols.append({'branch_id': None, 'name': 'الاجمالى', 'is_hq': False, 'is_total': True,
                 **consolidated,
                 'allocation': {ln: ZERO for ln in EXPENSE_LINES},
                 'after': consolidated})
    _softech_lines(cols, date_from, date_to, per_code, missing,
                   {k: (branches[k].softech_branch_id or '').strip() for k in branch_keys}, hq_codes)
    return cols


HQ_CODE = '100'
WARN_SOFTECH_MISSING = ('لا توجد أرقام سوفتيك لشهور: {months} — شغّل ترحيل المبيعات لها أو '
                        'gl_sync_branch_cost.')
WARN_SOFTECH_PARTIAL = 'الفترة أجزاء من شهور — أرقام سوفتيك للشهور كاملة'
WARN_SOFTECH_UNASSIGNED = ('أرقام سوفتيك لأكواد فروع غير معرّفة ({codes}) داخلة في عمود الإجمالي فقط: '
                           'مبيعات {sales:,.2f}، تكلفة {cost:,.2f}.')


def _softech_rows(date_from, date_to, today):
    """-> ({branch code: {'sales', 'cost'}} summed over the months the range touches,
    months that have started and have no GLBranchCost row at all)."""
    from apps.finance.models import GLBranchCost
    from .branch_cost import month_keys
    months = month_keys(date_from, date_to)
    per_code: dict[str, dict[str, Decimal]] = {}
    have = set()
    for r in GLBranchCost.objects.filter(year__gte=months[0][0], year__lte=months[-1][0]).values(
            'year', 'month', 'branch_code', 'net_cost', 'net_value'):
        if (r['year'], r['month']) not in months:
            continue
        have.add((r['year'], r['month']))
        slot = per_code.setdefault(r['branch_code'], {'sales': ZERO, 'cost': ZERO})
        slot['sales'] += r['net_value']
        slot['cost'] += r['net_cost']
    missing = [f'{y}-{m:02d}' for y, m in months
               if (y, m) not in have and datetime.date(y, m, 1) <= today]
    return per_code, missing


def _softech_lines(cols, date_from, date_to, per_code, missing, codes: dict, hq_codes: set) -> None:
    """Ruling P34: SOFTECH's own figures on one basis, separate from the ledger lines: per column
    ``softech_sales``, ``softech_cost`` and ``softech_gross_profit`` = the two's difference, for the
    whole months the range touches. ``softech_cost_months_missing`` and ``softech_partial_months``
    (the range cuts a month) on every column; the total also carries ``softech_unassigned`` (codes no
    column shows, so the columns + it = the total) and the warnings. Report-time only."""
    partial = date_from.day != 1 or (date_to + datetime.timedelta(days=1)).day != 1
    shown = hq_codes | set(codes.values())
    orphans = sorted(k for k in per_code if k not in shown)

    def total_of(wanted, key):
        return sum((per_code[k][key] for k in wanted if k in per_code), ZERO)

    for c in cols:
        if c['is_total']:
            wanted = list(per_code)
        else:
            wanted = hq_codes if c['is_hq'] else [codes.get(c['branch_id'], '')]
        c['softech_sales'] = total_of(wanted, 'sales')
        c['softech_cost'] = total_of(wanted, 'cost')
        c['softech_gross_profit'] = c['softech_sales'] - c['softech_cost']
        c['softech_cost_months_missing'] = missing
        c['softech_partial_months'] = partial
        if not c['is_total']:
            continue
        c['softech_unassigned'] = {'codes': orphans, 'sales': total_of(orphans, 'sales'),
                                   'cost': total_of(orphans, 'cost')}
        warnings = list(c.get('warnings', []))
        if missing:
            warnings.append(WARN_SOFTECH_MISSING.format(months='، '.join(missing)))
        if partial:
            warnings.append(WARN_SOFTECH_PARTIAL)
        if orphans:
            warnings.append(WARN_SOFTECH_UNASSIGNED.format(
                codes='، '.join(orphans), sales=total_of(orphans, 'sales'), cost=total_of(orphans, 'cost')))
        c['warnings'] = warnings


PCT_KEYS = ('opening_stock', 'net_purchases', 'closing_stock', 'net_sales', 'cost_of_sales',
            'gross_profit', 'other_revenue', 'capital_gains', *EXPENSE_LINES, 'total_expenses',
            'net_profit')


def comparison(years: list[int]) -> list[dict]:
    """trading_and_pl per calendar year, value + share of net sales (finance's «الختامية المجمعة»)."""
    out = []
    for y in years:
        start, end = datetime.date(y, 1, 1), datetime.date(y, 12, 31)
        values = trading_and_pl(start, end)
        empty = not _range_qs(start, end).filter(
            account__group__section__in=TRADING_PL_SECTIONS).exists()
        out.append({'year': y, 'empty': empty, 'values': values,
                    'pct_of_sales': {k: _ratio(values[k], values['net_sales']) for k in PCT_KEYS}})
    return out
