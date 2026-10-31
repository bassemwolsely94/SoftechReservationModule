"""
apps/finance/cash_view.py

P-40 «النقدية ١٣ أسبوع» (docs/product-review/06_SPEC_P-40_13_week_cash_view.md). PostgreSQL only, Decimal throughout,
no SOFTECH call. Weeks run Saturday–Friday (owner 2026-10-31); week 1 contains `as_of`. A dated item on a non-banking
day moves to the next banking day (cheques.engine.next_banking_day).

  build_cash_view(as_of, weeks=13, purchase_budget_weekly=None)   lines × weeks (low / base / high) + closings
  line_rows(as_of, key, week, …)                                  the rows behind one cell (base)

Lines
  In   cash_sales            channels in SystemSetting `cash_view_cash_channels` (default 91,90), 115 − 30;
                             base = mean of the last 8 complete weeks, low = min, high = max
       contract_collections  P-41 expected_contract_inflows: base = expected date, low = late placement
  Out  supplier_cheques      post-dated supplier bank cheques (financialdoccode 20, date = cheqdate) after as_of
       supplier_payables     P-42 slices by due date, net of the same supplier's unallocated post-dated cheques
                             (earliest due first) so nothing is counted twice; overdue → week 1
       new_purchases         13-week run rate per supplier × category (or the "what if" weekly budget, same mix)
                             placed at that supplier's terms; suppliers without terms are not placed
       fixed_outflows        FixedOutflow schedules (finance input)
       planned_cheques       pending instalments of active cheque plans (apps/cheques)
  Memo internal_accounts     cheques + payables of `finance_internal_supplier_codes` — never in the closings
       early_pay             P-42 early_pay_by_week: discount on offer per week (foregone in the note)
       no_terms              open real payables without terms — week 1 of the pessimistic closing only

Missing inputs degrade, never guess: no opening balance → no closings (weekly nets only).
"""
import calendar as _cal
import datetime as dt
import hashlib
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from . import supplier_terms as ST

ZERO = Decimal('0')
CENT = Decimal('0.01')
WEEKS = 13
SALES_WEEKS = 8
PURCHASE_WEEKS = 13
DEFAULT_CASH_CHANNELS = '91,90'
NATIVE = ('softech', 'written')
VOIDED = ('reversed', 'reversal')

LINES = [
    # key, label_ar, group, source, freshness_domain
    ('cash_sales',           'مبيعات نقدي وتوصيل',     'in',   'estimate',       'sales'),
    ('contract_collections', 'تحصيل التعاقدات',        'in',   'softech_mirror', 'ar_contracts'),
    ('supplier_cheques',     'شيكات صادرة مؤجلة',      'out',  'softech_mirror', 'ap_reconciliation'),
    ('supplier_payables',    'مستحقات الموردين',       'out',  'softech_mirror', 'ap_reconciliation'),
    ('new_purchases',        'مشتريات جديدة',          'out',  'estimate',       'purchases'),
    ('fixed_outflows',       'مصروفات ثابتة',          'out',  'finance_input',  ''),
    ('planned_cheques',      'شيكات مخططة',            'out',  'finance_input',  ''),
    ('internal_accounts',    'حسابات داخلية',          'memo', 'softech_mirror', 'ap_reconciliation'),
    ('early_pay',            'خصم دفع مبكر متاح',      'memo', 'finance_input',  'ap_reconciliation'),
    ('no_terms',             'مستحقات بدون شروط',      'memo', 'softech_mirror', 'ap_reconciliation'),
]


def _q(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def cash_channels():
    from apps.config.models import SystemSetting
    raw = SystemSetting.get('cash_view_cash_channels', DEFAULT_CASH_CHANNELS) or ''
    return [c.strip() for c in str(raw).split(',') if c.strip()]


class _Grid:
    """Per line: low / base / high per week + the base rows behind each cell."""

    def __init__(self, as_of, n):
        from apps.cheques.engine import next_banking_day
        self.as_of, self.n = as_of, n
        self.start = ST.week_start(as_of)
        self.end = self.start + dt.timedelta(days=7 * n - 1)
        self._nbd = next_banking_day
        self.cells = {k: {'low': [ZERO] * n, 'base': [ZERO] * n, 'high': [ZERO] * n} for k, *_ in LINES}
        self.rows = {k: [[] for _ in range(n)] for k, *_ in LINES}
        self.notes = defaultdict(list)

    def week(self, day, shift=True):
        """Week index of `day` (banking-day shifted); earlier than as_of → week 1; past the horizon → None."""
        if day is None:
            return None
        day = max(day, self.as_of)
        if shift:
            day = self._nbd(day)
        i = (day - self.start).days // 7
        return i if 0 <= i < self.n else None

    def add(self, key, i, amount, row=None, cases=('low', 'base', 'high')):
        if i is None or not amount:
            return
        for c in cases:
            self.cells[key][c][i] += amount
        if row is not None and 'base' in cases:
            self.rows[key][i].append(row)


# ── in ───────────────────────────────────────────────────────────────────────

def _cash_sales(g):
    from django.db.models import Sum
    from django.db.models.functions import TruncDate
    from django.utils import timezone
    from apps.customers.models import PurchaseHistory
    since = g.start - dt.timedelta(days=7 * SALES_WEEKS)
    aware = lambda d: timezone.make_aware(dt.datetime.combine(d, dt.time.min))       # noqa: E731
    weekly = [ZERO] * SALES_WEEKS
    seen = False
    for r in (PurchaseHistory.objects.filter(invoice_date__gte=aware(since), invoice_date__lt=aware(g.start),
                                             sales_channel__in=cash_channels(), doc_code__in=('115', '30'))
              .annotate(day=TruncDate('invoice_date')).values('day', 'doc_code').annotate(s=Sum('total_amount'))):
        seen = True
        i = (r['day'] - since).days // 7
        if 0 <= i < SALES_WEEKS:
            weekly[i] += (r['s'] or ZERO) * (-1 if r['doc_code'] == '30' else 1)
    if not seen:
        g.notes['cash_sales'].append('لا مبيعات نقدية في آخر 8 أسابيع')
        return
    low, high, base = min(weekly), max(weekly), _q(sum(weekly, ZERO) / SALES_WEEKS)
    hist = [{'week_start': since + dt.timedelta(days=7 * i), 'amount': w} for i, w in enumerate(weekly)]
    for i in range(g.n):
        g.cells['cash_sales']['low'][i] += low
        g.cells['cash_sales']['base'][i] += base
        g.cells['cash_sales']['high'][i] += high
        g.rows['cash_sales'][i] = hist


def _contracts(g):
    from .receivables import expected_contract_inflows
    unplaced = ZERO
    for r in expected_contract_inflows(g.as_of):
        if r['base_date'] is None:
            unplaced += r['amount']
            continue
        row = {**r, 'date': r['base_date']}
        g.add('contract_collections', g.week(r['base_date']), r['amount'], row, cases=('base', 'high'))
        g.add('contract_collections', g.week(r['low_date']), r['amount'], cases=('low',))
    if unplaced:
        g.notes['contract_collections'].append(f'بلا تاريخ متوقع: {_q(unplaced):,.2f}')


# ── out ──────────────────────────────────────────────────────────────────────

def _suppliers(g):
    """Post-dated cheques, payables net of unallocated cheques, internal accounts and no-terms."""
    from django.db.models import Sum
    from .models import Allocation, Payment
    internal = ST.internal_codes()
    cheques = list(Payment.objects.filter(party_type='supplier', direction='out', financial_doc_code='20',
                                          voucher_date__gt=g.as_of)
                   .exclude(chain_role__in=VOIDED).select_related('party'))
    allocated = dict(Allocation.objects.filter(payment__in=cheques, origin__in=NATIVE)
                     .values('payment_id').annotate(s=Sum('amount')).values_list('payment_id', 's'))
    credit = defaultdict(lambda: ZERO)
    for c in cheques:
        pc = c.party.softech_personcode
        credit[pc] += max(ZERO, c.amount - (allocated.get(c.pk) or ZERO))
        row = {'personcode': pc, 'supplier': c.party.name, 'branchcode': c.branchcode, 'cheqsno': c.cheqsno,
               'date': c.voucher_date, 'amount': c.amount, 'note': c.note}
        g.add('internal_accounts' if pc in internal else 'supplier_cheques', g.week(c.voucher_date), c.amount, row)

    slices = defaultdict(list)
    for s in ST._slices():
        slices[s.invoice.party.softech_personcode].append(s)
    no_terms, no_terms_n = ZERO, 0
    for pc, items in slices.items():
        left = credit.get(pc, ZERO)
        for s in sorted(items, key=lambda s: (s.due_date is None, s.due_date or dt.date.max, s.invoice_id)):
            take = min(left, s.open_amount)
            left -= take
            amount = s.open_amount - take
            if amount <= 0:
                continue
            inv = s.invoice
            row = {'personcode': pc, 'supplier': inv.party.name, 'branchcode': inv.branchcode,
                   'docnumber': ST._docno(inv.docnumber), 'docdate': inv.docdate, 'category': s.category,
                   'date': s.due_date, 'amount': amount, 'netted_by_cheque': take}
            if pc in internal:
                g.add('internal_accounts', g.week(s.due_date or g.as_of), amount, row)
            elif s.due_date is None:
                no_terms += amount
                no_terms_n += 1
                g.rows['no_terms'][0].append(row)
            else:
                g.add('supplier_payables', g.week(s.due_date), amount, row)
    if no_terms:
        for c in ('low', 'base', 'high'):
            g.cells['no_terms'][c][0] = no_terms
        g.notes['no_terms'].append(f'{no_terms_n} شريحة فاتورة بلا شروط — في الأسبوع الأول للحالة المتشائمة فقط')


def _new_purchases(g, budget_weekly=None):
    """Run rate per (supplier, category) over the last 13 complete weeks of real-supplier purchases (10 − 120), each
    week's buying placed at that supplier's terms. Week 1 counts only the days after as_of. A weekly budget keeps the
    same mix. Suppliers without terms are not placed (noted)."""
    from django.db.models import Sum
    from apps.procurement.models import PurchaseLine
    from .models import ReconParty
    since = g.start - dt.timedelta(days=7 * PURCHASE_WEEKS)
    internal = ST.internal_codes()
    rate = defaultdict(lambda: ZERO)
    for r in (PurchaseLine.objects.filter(doccode__in=('10', '120'), doc_date__gte=since, doc_date__lt=g.start)
              .exclude(supplier_code__in=internal)
              .values('supplier_code', 'item_id', 'item__is_imported').annotate(s=Sum('net_value'))):
        cat = 'unclassified' if r['item_id'] is None else ('imported' if r['item__is_imported'] else 'local')
        rate[(str(r['supplier_code']).strip(), cat)] += (r['s'] or ZERO) / PURCHASE_WEEKS
    total = sum((v for v in rate.values() if v > 0), ZERO)
    if total <= 0:
        g.notes['new_purchases'].append('لا مشتريات في آخر 13 أسبوعًا')
        return
    scale = (Decimal(budget_weekly) / total) if budget_weekly is not None else Decimal('1')
    parties = {p.softech_personcode: p for p in ReconParty.objects.filter(
        softech_personcode__in={pc for pc, _ in rate}, party_type='supplier')}
    terms = ST._terms_by_party({p.pk for p in parties.values()})
    unplaced = ZERO
    for (pc, cat), weekly in rate.items():
        if weekly <= 0:
            continue
        weekly *= scale
        p = parties.get(pc)
        t = ST.term_for(terms.get(p.pk, []), cat, g.as_of) if p else None
        if t is None:
            unplaced += weekly
            continue
        for k in range(g.n):
            bought = g.start + dt.timedelta(days=7 * k)
            share = Decimal(1)
            if k == 0:
                bought = g.as_of
                share = Decimal((g.start + dt.timedelta(days=6) - g.as_of).days) / 7
            amount = weekly * share
            due = ST.due_date(t, bought)
            g.add('new_purchases', g.week(due), amount,
                  {'personcode': pc, 'supplier': p.name, 'category': cat, 'bought_week': bought, 'date': due,
                   'amount': amount, 'credit_days': t.credit_days})
    if unplaced:
        g.notes['new_purchases'].append(f'مشتريات أسبوعية بلا شروط لم تُوزَّع: {_q(unplaced):,.2f}')


def _fixed(g):
    from .models import FixedOutflow
    for f in FixedOutflow.objects.filter(is_active=True):
        dates = []
        if f.frequency == 'weekly':
            dates = [g.start + dt.timedelta(days=7 * k) for k in range(g.n)]
        elif f.frequency == 'monthly':
            y, m = g.start.year, g.start.month
            while dt.date(y, m, 1) <= g.end:
                dates.append(dt.date(y, m, min(f.day_of_month or 1, _cal.monthrange(y, m)[1])))
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        elif f.date:
            dates = [f.date]
        for d in dates:
            if d < g.as_of or d > g.end or (f.start and d < f.start) or (f.end and d > f.end):
                continue
            g.add('fixed_outflows', g.week(d), f.amount,
                  {'id': f.pk, 'label': f.label, 'category': f.get_category_display(), 'date': d, 'amount': f.amount})


def _planned(g):
    from apps.cheques.models import ChequeInstalment
    for c in (ChequeInstalment.objects.filter(plan__status='active', status='pending', due_date__lte=g.end)
              .select_related('plan')):
        g.add('planned_cheques', g.week(c.due_date), c.amount,
              {'plan': c.plan.title, 'payee': c.plan.payee_name, 'instalment_no': c.instalment_no,
               'date': c.due_date, 'amount': c.amount})


def _early_pay(g):
    e = ST.early_pay_by_week(g.as_of, g.n)
    for i, w in enumerate(e['weeks']):
        g.add('early_pay', i, w['available_value'],
              {'date': w['start'], 'amount': w['available_value'], 'pay_amount': w['pay_amount']})
    if e['foregone_value']:
        g.notes['early_pay'].append(f'خصم فات: {_q(e["foregone_value"]):,.2f}')


# ── assembly ─────────────────────────────────────────────────────────────────

def opening_balance(as_of):
    from .models import CashOpeningBalance
    return CashOpeningBalance.objects.filter(as_of__lte=as_of).order_by('-as_of', '-entered_at').first()


def _grid(as_of, weeks, purchase_budget_weekly, only=None):
    """All lines, or (for a drill-down) only the step that fills `only`."""
    g = _Grid(as_of, weeks)
    steps = [(('cash_sales',), lambda: _cash_sales(g)),
             (('contract_collections',), lambda: _contracts(g)),
             (('supplier_cheques', 'supplier_payables', 'internal_accounts', 'no_terms'), lambda: _suppliers(g)),
             (('new_purchases',), lambda: _new_purchases(g, purchase_budget_weekly)),
             (('fixed_outflows',), lambda: _fixed(g)),
             (('planned_cheques',), lambda: _planned(g)),
             (('early_pay',), lambda: _early_pay(g))]
    for keys, run in steps:
        if only is None or only in keys:
            run()
    return g


def build_cash_view(as_of, weeks=WEEKS, purchase_budget_weekly=None):
    from .models import ContractReceivableTerms
    g = _grid(as_of, weeks, purchase_budget_weekly)
    lines = []
    for key, label, group, source, domain in LINES:
        c = g.cells[key]
        lines.append({'key': key, 'label_ar': label, 'group': group, 'source': source, 'freshness_domain': domain,
                      'low': [_q(x) for x in c['low']], 'base': [_q(x) for x in c['base']],
                      'high': [_q(x) for x in c['high']], 'notes': g.notes.get(key, [])})

    def total(group, case):
        return [sum((ln[case][i] for ln in lines if ln['group'] == group), ZERO) for i in range(weeks)]
    in_low, in_base, in_high = total('in', 'low'), total('in', 'base'), total('in', 'high')
    out_base = total('out', 'base')
    no_terms = next(ln for ln in lines if ln['key'] == 'no_terms')['base']
    out_high = [o + (no_terms[0] if i == 0 else ZERO) for i, o in enumerate(out_base)]
    net = {'low': [a - b for a, b in zip(in_low, out_high)], 'base': [a - b for a, b in zip(in_base, out_base)],
           'high': [a - b for a, b in zip(in_high, out_base)]}
    ob = opening_balance(as_of)
    closing = {'low': None, 'base': None, 'high': None}
    if ob is not None:
        for case in closing:
            run, out = ob.amount, []
            for x in net[case]:
                run += x
                out.append(run)
            closing[case] = out
    tracked = ContractReceivableTerms.objects.filter(is_tracked=True)
    return {
        'as_of': as_of,
        'weeks': [{'index': i, 'start': g.start + dt.timedelta(days=7 * i),
                   'end': g.start + dt.timedelta(days=7 * i + 6)} for i in range(weeks)],
        'opening': {'as_of': ob.as_of, 'amount': ob.amount, 'note': ob.note} if ob else None,
        'lines': lines,
        'totals': {'in_base': in_base, 'out_base': out_base, 'in_low': in_low, 'in_high': in_high,
                   'out_high': out_high},
        'net': net, 'closing': closing,
        'purchase_budget_weekly': purchase_budget_weekly,
        'coverage': {'opening_as_of': ob.as_of if ob else None, 'supplier_terms': ST.terms_coverage(),
                     'contracts_tracked': tracked.count(),
                     'contracts_with_agreed_days': tracked.filter(agreed_days__isnull=False).count()},
    }


def line_rows(as_of, key, week, purchase_budget_weekly=None, weeks=WEEKS):
    """The rows behind one cell (base case). Week is 0-based."""
    if key not in {k for k, *_ in LINES} or not 0 <= week < weeks:
        return []
    g = _grid(as_of, weeks, purchase_budget_weekly, only=key)
    if not 0 <= week < weeks:
        return []
    return g.rows[key][week]


def snapshot(as_of):
    """Store the view built on `as_of` (one per date — re-running replaces it)."""
    from .models import CashViewSnapshot
    v = build_cash_view(as_of)
    data = json.loads(json.dumps(v, default=str))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    obj, _ = CashViewSnapshot.objects.update_or_create(as_of=as_of, defaults={'weeks': data, 'inputs_hash': digest})
    return obj
