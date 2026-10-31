"""
apps/finance/receivables.py

P-41 (docs/product-review/06_SPEC_P-41_contract_receivables.md): who owes us on contract, since when. PostgreSQL only
— reads the customer side of the A/P–A/R mirror (APInvoice 115 / 30, Payment, Allocation) that
`sync_ap_reconciliation --party-type customer --contracts` fills for the tracked accounts. Decimal throughout.

    open (invoice)  = doc_value − max(doc_value_pay, Σ SOFTECH links)          links = Allocation softech / written
    expected date   = end of the invoice month + agreed days   (owner 2026-10-31)
                      no agreed days → invoice date + measured days, labelled «مقاس»
    overdue         = open > 0.01 and expected date < as of
    measured days   = value-weighted (receipt date − invoice date) over SOFTECH's links, when they cover ≥ 70 % of the
                      contract's sales in the year; otherwise an estimate paying the oldest invoices first with each
                      receipt («تقدير — أقدم فاتورة أولاً», owner 2026-10-31)
    on account      = receipts not linked to any invoice («على الحساب»); open returns (30) are a credit
    difference      = (Σ open − on account − open returns) − SOFTECH's receivable  — shown, never hidden

Nothing here writes to SOFTECH; recon_writer refuses customer allocations.
"""
import calendar
import datetime as dt
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from apps.finance.queries.sybase_reconciliation import get_party_balances

ZERO = Decimal('0')
CENT = Decimal('0.01')
WINDOW_DAYS = 365
RELIABLE_COVERAGE_PCT = Decimal('70')
BUCKETS = (('0-30', 30), ('31-60', 60), ('61-90', 90), ('91-180', 180), ('>180', None))
NATIVE = ('softech', 'written')
_COPAY = re.compile(r'\s*(\d+\s*%|بدون\s*تحمل).*$')


def group_name(name):
    """«D M S 10%» → «D M S»: the company an insurance co-pay account belongs to."""
    return _COPAY.sub('', str(name or '')).strip(' -') or str(name or '').strip()


def group_key(name):
    """One company whatever SOFTECH's spelling: «Med sure» and «Med Sure» are the same group."""
    return ' '.join(str(name or '').split()).casefold()


def month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _q1(v):
    return v.quantize(Decimal('0.1'), ROUND_HALF_UP)


def _bucket(age):
    for label, limit in BUCKETS:
        if limit is None or age <= limit:
            return label
    return BUCKETS[-1][0]


def _invoices(personcode):
    from apps.finance.models import APInvoice
    return APInvoice.objects.filter(party__softech_personcode=personcode, party_type='customer')


def _native_paid(invoice_ids):
    from django.db.models import Sum
    from apps.finance.models import Allocation
    return {r['invoice_id']: r['s'] for r in (Allocation.objects.filter(invoice_id__in=invoice_ids, origin__in=NATIVE)
                                              .values('invoice_id').annotate(s=Sum('amount')))}


def _terms(personcode):
    from apps.finance.models import ContractReceivableTerms
    return ContractReceivableTerms.objects.filter(personcode=personcode).first()


def measured_days(personcode, as_of, window_days=WINDOW_DAYS):
    """{'days', 'max_days', 'coverage_pct', 'method': linked | fifo | none, 'sample'} over the year to `as_of`."""
    from apps.finance.models import Allocation, Payment
    since = as_of - dt.timedelta(days=window_days)
    sales = list(_invoices(personcode).filter(doccode='115', docdate__gt=since, docdate__lte=as_of)
                 .order_by('docdate', 'docnumber', 'pk'))
    sales_value = sum((i.doc_value for i in sales), ZERO)
    ids = {i.pk for i in sales}
    links = list(Allocation.objects.filter(invoice__in=sales, origin__in=NATIVE, payment__voucher_date__lte=as_of)
                 .select_related('payment', 'invoice'))
    linked = sum((a.amount for a in links if a.invoice_id in ids), ZERO)
    coverage = _q1(linked * 100 / sales_value) if sales_value else Decimal('0.0')
    pairs = [(a.amount, (a.payment.voucher_date - a.invoice.docdate).days) for a in links if a.amount > 0]
    method = 'linked'
    if not pairs or coverage < RELIABLE_COVERAGE_PCT:
        method, pairs = 'fifo', []
        queue = [[i.docdate, i.doc_value] for i in sales]
        receipts = (Payment.objects.filter(party__softech_personcode=personcode, party_type='customer', cheqtype='10',
                                           direction='in', voucher_date__gt=since, voucher_date__lte=as_of)
                    .order_by('voucher_date', 'cheqsno'))
        for r in receipts:
            left = r.amount
            while left > 0 and queue:
                day, due = queue[0]
                take = min(left, due)
                if day <= r.voucher_date:
                    pairs.append((take, (r.voucher_date - day).days))
                queue[0][1] -= take
                left -= take
                if queue[0][1] <= 0:
                    queue.pop(0)
    weight = sum((amt for amt, _ in pairs), ZERO)
    if not weight:
        return {'days': None, 'max_days': None, 'coverage_pct': coverage, 'method': 'none', 'sample': 0}
    return {'days': _q1(sum((amt * d for amt, d in pairs), ZERO) / weight), 'max_days': max(d for _, d in pairs),
            'coverage_pct': coverage, 'method': method, 'sample': len(pairs)}


def open_invoices(personcode, as_of, measured=None):
    """The contract's open sales invoices with age, bucket, expected date and overdue."""
    terms = _terms(personcode)
    agreed = terms.agreed_days if terms else None
    sales = list(_invoices(personcode).filter(doccode='115', docdate__lte=as_of).order_by('docdate', 'docnumber'))
    paid = _native_paid([i.pk for i in sales])
    if agreed is None and measured is None:
        measured = measured_days(personcode, as_of)
    out = []
    for i in sales:
        open_ = i.doc_value - max(i.doc_value_pay or ZERO, paid.get(i.pk, ZERO))
        if open_ <= CENT:
            continue
        age = (as_of - i.docdate).days
        if agreed is not None:
            expected, basis = month_end(i.docdate) + dt.timedelta(days=agreed), 'agreed'
        elif measured and measured['days'] is not None:
            days = int(measured['days'].quantize(Decimal('1'), ROUND_HALF_UP))
            expected, basis = i.docdate + dt.timedelta(days=days), 'measured'
        else:
            expected, basis = None, 'none'
        out.append({'id': i.pk, 'branchcode': i.branchcode, 'docnumber': i.docnumber, 'docdate': i.docdate,
                    'value': i.doc_value, 'open': open_, 'age': age, 'bucket': _bucket(age),
                    'expected_date': expected, 'expected_basis': basis,
                    'overdue': bool(expected and expected < as_of)})
    return out


def contract_summary(personcode, as_of):
    from django.db.models import Sum
    from apps.finance.models import Allocation, Payment, ReconParty
    terms = _terms(personcode)
    measured = measured_days(personcode, as_of)
    rows = open_invoices(personcode, as_of, measured=measured)
    buckets = {label: ZERO for label, _ in BUCKETS}
    for r in rows:
        buckets[r['bucket']] += r['open']
    receipts = Payment.objects.filter(party__softech_personcode=personcode, party_type='customer', cheqtype='10',
                                      direction='in', voucher_date__lte=as_of)
    linked = dict(Allocation.objects.filter(payment__in=receipts, origin__in=NATIVE)
                  .values('payment_id').annotate(s=Sum('amount')).values_list('payment_id', 's'))
    on_account = sum((max(ZERO, p.amount - linked.get(p.pk, ZERO)) for p in receipts), ZERO)
    returns = _invoices(personcode).filter(doccode='30', docdate__lte=as_of)
    open_returns = sum((max(ZERO, r.doc_value - (r.doc_value_pay or ZERO)) for r in returns), ZERO)
    open_total = sum((r['open'] for r in rows), ZERO)
    net = open_total - on_account - open_returns
    party = ReconParty.objects.filter(softech_personcode=personcode).first()
    softech = -(party.softech_balance or ZERO) if party else None      # owed convention: negative = they owe us
    return {
        'personcode': personcode, 'name': (terms.name if terms else '') or (party.name if party else ''),
        'group_name': terms.group_name if terms else '', 'agreed_days': terms.agreed_days if terms else None,
        'open': open_total, 'buckets': buckets, 'overdue': sum((r['open'] for r in rows if r['overdue']), ZERO),
        'on_account': on_account, 'open_returns': open_returns, 'net_receivable': net,
        'softech_receivable': softech, 'difference': (net - softech) if softech is not None else None,
        'softech_balance_at': party.softech_balance_at if party else None,
        'measured_days': measured['days'], 'measured_max': measured['max_days'],
        'measured_method': measured['method'], 'link_coverage_pct': measured['coverage_pct'],
        'open_count': len(rows),
    }


def summary(as_of):
    """Every tracked contract, grouped by company, with totals."""
    from apps.finance.models import ContractReceivableTerms
    groups, labels = defaultdict(list), {}
    for t in ContractReceivableTerms.objects.filter(is_tracked=True).order_by('group_name', 'personcode'):
        label = t.group_name or t.name or t.personcode
        key = group_key(label)
        labels.setdefault(key, label)
        groups[key].append(contract_summary(t.personcode, as_of))
    keys = ('open', 'overdue', 'on_account', 'open_returns', 'net_receivable')
    out, totals = [], {k: ZERO for k in keys}
    for key, contracts in groups.items():
        g = {'group_name': labels[key], 'contracts': contracts}
        for k in keys:
            g[k] = sum((c[k] for c in contracts), ZERO)
            totals[k] += g[k]
        weight = sum((c['open'] for c in contracts if c['measured_days'] is not None), ZERO)
        g['measured_days'] = (_q1(sum((c['open'] * c['measured_days'] for c in contracts
                                       if c['measured_days'] is not None), ZERO) / weight) if weight else None)
        out.append(g)
    out.sort(key=lambda g: -g['net_receivable'])
    all_c = [c for g in out for c in g['contracts'] if c['measured_days'] is not None]
    w = sum((c['open'] for c in all_c), ZERO)
    totals['measured_days'] = _q1(sum((c['open'] * c['measured_days'] for c in all_c), ZERO) / w) if w else None
    return {'as_of': as_of, 'groups': out, 'totals': totals}


def seed_terms():
    """Create a tracked row for every contract account in our sales history (channel 10, last year) that has none;
    names from SOFTECH (SELECT-only), co-pay accounts grouped by company. Returns the number created."""
    from apps.finance import receivables_probe
    from apps.finance.models import ContractReceivableTerms, ReconParty
    codes = [c for c in receivables_probe.contract_personcodes()
             if not ContractReceivableTerms.objects.filter(personcode=c).exists()]
    if not codes:
        return 0
    names = {}
    rows = get_party_balances(codes)
    if rows and '_error' not in rows[0]:
        names = {str(r['personcode']).strip(): str(r.get('personname') or '').strip() for r in rows}
    parties = {p.softech_personcode: p for p in ReconParty.objects.filter(softech_personcode__in=codes)}
    known = {group_key(g): g for g in ContractReceivableTerms.objects.exclude(group_name='')
             .values_list('group_name', flat=True)}
    for c in codes:
        name = names.get(c) or (parties[c].name if c in parties else '')
        g = group_name(name)
        g = known.setdefault(group_key(g), g)            # one spelling per company
        ContractReceivableTerms.objects.create(personcode=c, party=parties.get(c), name=name, group_name=g)
    return len(codes)
