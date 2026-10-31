"""
apps/finance/receivables_probe.py

P-41 step 0 (docs/product-review/06_SPEC_P-41_contract_receivables.md): one SELECT-only pass per contract account
over SOFTECH — sales (115) and returns (30) on stktransm, receipts on cheques, and SOFTECH's own receipt → invoice
links on chequestrans — to measure how long each contract takes to pay and how much of its sales those links
cover. It decides, per contract, whether measured collection days can be trusted.

Every query is filtered to ONE contract's personcode (the shared query functions in
queries/sybase_reconciliation.py with personcode=…), so nothing reads all retail sales or every voucher.
Writes nothing to SOFTECH or to our database.

    collection days = Σ(link amount × (receipt date − invoice date)) / Σ link amount     (value-weighted)
    link coverage   = Σ links to the window's sales invoices ÷ Σ sales invoice value
    on account      = Σ receipt value − Σ of those receipts linked to invoices
"""
import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from apps.finance.queries.sybase_reconciliation import (get_allocations, get_invoices, get_party_balances,
                                                        get_vouchers)

RELIABLE_COVERAGE_PCT = Decimal('70')    # below this, measured days are labelled unreliable (owner decides — Q1)
CONTRACT_CHANNEL = '10'                  # تعاقدات / آجل


def _d(v):
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal('0')


def _date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _q1(v):
    return v.quantize(Decimal('0.1'), ROUND_HALF_UP)


def contract_personcodes(days=365):
    """Contract accounts that bought on channel 10 in the last `days` (customers.PurchaseHistory)."""
    from django.utils import timezone
    from apps.customers.models import PurchaseHistory
    since = timezone.now() - dt.timedelta(days=days)
    codes = (PurchaseHistory.objects.filter(sales_channel=CONTRACT_CHANNEL, invoice_date__gte=since)
             .exclude(softech_personcode='').values_list('softech_personcode', flat=True).distinct())
    return sorted({str(c).strip() for c in codes if str(c).strip()})


def summarize(personcode, invoices, receipts, allocations):
    """One contract's figures from the three row lists (rows as returned by the query functions)."""
    sales = [r for r in invoices if str(r.get('doccode')) == '115']
    returns = [r for r in invoices if str(r.get('doccode')) == '30']
    sales_keys = {(str(r['branchcode']), str(r['docnumber'])) for r in sales}
    invoice_value = sum((_d(r['docvalue']) for r in sales), Decimal('0'))
    receipt_day = {(str(r['branchcode']), str(r['cheqsno'])): _date(r['cheqdate']) for r in receipts}
    by_type = defaultdict(lambda: {'count': 0, 'value': Decimal('0')})
    for r in receipts:
        t = by_type[str(r.get('cheqtype') or '')]
        t['count'] += 1
        t['value'] += _d(r['cheqvalue'])

    weighted, linked, linked_to_window, max_days = Decimal('0'), Decimal('0'), Decimal('0'), None
    linked_by_receipt = defaultdict(Decimal)
    for a in allocations:
        if str(a.get('doccode')) != '115':
            continue
        amount = _d(a.get('docvaluepaynow'))
        if amount <= 0:
            continue
        rkey = (str(a.get('cheqbranchcode')), str(a.get('cheqsno')))
        linked_by_receipt[rkey] += amount
        if (str(a.get('branchcode')), str(a.get('docnumber'))) in sales_keys:
            linked_to_window += amount
        paid_on, issued = receipt_day.get(rkey), _date(a.get('docdate'))
        if paid_on is None or issued is None:
            continue
        days = (paid_on - issued).days
        weighted += amount * days
        linked += amount
        max_days = days if max_days is None else max(max_days, days)

    on_account = sum((max(Decimal('0'), _d(r['cheqvalue']) - linked_by_receipt.get(
        (str(r['branchcode']), str(r['cheqsno'])), Decimal('0'))) for r in receipts if str(r.get('cheqtype')) == '10'),
        Decimal('0'))
    coverage = _q1(linked_to_window * 100 / invoice_value) if invoice_value else Decimal('0.0')
    return {
        'personcode': personcode,
        'invoice_count': len(sales), 'invoice_value': invoice_value,
        'return_count': len(returns), 'return_value': sum((_d(r['docvalue']) for r in returns), Decimal('0')),
        'receipts_by_type': dict(by_type),
        'collection_days': _q1(weighted / linked) if linked else None,
        'collection_days_max': max_days,
        'allocation_coverage_pct': coverage,
        'on_account': on_account,
        'reliable': bool(linked) and coverage >= RELIABLE_COVERAGE_PCT,
    }


def probe(personcode, date_from, date_to):
    """Read one contract (SELECT-only) and summarize it. Returns (summary, error or '')."""
    rows = [get_invoices('customer', date_from, date_to, personcode=personcode),
            get_vouchers('customer', date_from, date_to, personcode=personcode),
            get_allocations('customer', date_from, date_to, personcode=personcode)]
    for r in rows:
        if r and isinstance(r[0], dict) and '_error' in r[0]:
            return None, r[0]['_error']
    return summarize(personcode, *rows), ''
