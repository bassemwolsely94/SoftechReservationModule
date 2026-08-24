"""
apps/pos_orders/pricing.py

Pure, deterministic implementation of the SOFTECH line/header computation,
empirically validated in docs/architecture/SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md §6d:

    transprice        = round(itemsaleprice * (1 - custdiscp/100), 2)
    transprice_total  = round(transprice * qty, 2)
    itemsalestax      = transprice_total - transprice_total/(1 + taxp/100)
    docvalue  = docvalue1 ... = Σ transprice_total            (net)
    docvalue_gross (docvalue1) = Σ itemsaleprice * qty          (pre-discount list)
    docvalue_cogs  (docvalue2) = Σ newcostprice * qty           (COGS)
    docvalue_tax   (docvalue3) = Σ itemsalestax                 (VAT)

No DB access — unit-testable in PG-only tests. Decimal throughout.
"""
from decimal import Decimal, ROUND_HALF_UP

Q2 = Decimal('0.01')
Q4 = Decimal('0.0001')


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _r2(v):
    return _d(v).quantize(Q2, rounding=ROUND_HALF_UP)


def _r4(v):
    return _d(v).quantize(Q4, rounding=ROUND_HALF_UP)


def compute_line(*, item_sale_price, sale_tax_pct, qty, cust_discp, new_cost_price=0):
    """
    Returns the computed numeric fields for one stktrans5 line.
    Inputs come from the branch `items` row (price/tax) + `stkbal.nowcostprice` (cost).
    """
    isp   = _d(item_sale_price)
    qty   = _d(qty)
    disc  = _d(cust_discp)
    taxp  = _d(sale_tax_pct)

    trans_price       = _r2(isp * (Decimal('1') - disc / Decimal('100')))
    trans_price_total = _r2(trans_price * qty)
    # tax is the portion of the (post-discount) total that is VAT
    if taxp > 0:
        net = trans_price_total / (Decimal('1') + taxp / Decimal('100'))
        item_sale_tax = _r4(trans_price_total - net)
    else:
        item_sale_tax = Decimal('0.0000')
    item_sale_price_tax = _r4(isp / (Decimal('1') + taxp / Decimal('100'))) if taxp > 0 else _r4(isp)

    return {
        'trans_price':         trans_price,
        'trans_price_total':   trans_price_total,
        'item_sale_tax':       item_sale_tax,
        'item_sale_price_tax': item_sale_price_tax,
        'new_cost_price':      _r4(new_cost_price),
        'line_cogs':           _r2(_d(new_cost_price) * qty),
        'line_gross':          _r2(isp * qty),
    }


def compute_header(lines):
    """
    lines: iterable of dicts with trans_price_total, item_sale_tax, line_cogs, line_gross.
    Returns the header money aggregates (mirrors docvalue / docvalue1/2/3).
    """
    doc_value       = sum((_d(l['trans_price_total']) for l in lines), Decimal('0'))
    doc_value_gross = sum((_d(l['line_gross'])        for l in lines), Decimal('0'))
    doc_value_cogs  = sum((_d(l['line_cogs'])         for l in lines), Decimal('0'))
    doc_value_tax   = sum((_d(l['item_sale_tax'])     for l in lines), Decimal('0'))
    return {
        'doc_value':       _r2(doc_value),
        'doc_value_gross': _r2(doc_value_gross),
        'doc_value_cogs':  _r2(doc_value_cogs),
        'doc_value_tax':   _r2(doc_value_tax),
    }


def split_payment(channel, doc_value, tenders=None):
    """
    Resolve payment posture (spec §6c/§6e):
      cash/delivery/etc → full non-credit tender; patient_payment = 0
      contract          → caller supplies tenders (cash part + credit remainder, paymenttype 10)
    `tenders`: optional explicit list of {'pay_type','amount'} the operator entered.
    Returns (doc_value_pay, patient_payment, normalized_tenders).
      doc_value_pay   = Σ non-credit tenders (collected now)
      patient_payment = the cash down-payment on a credit sale (0 for pure cash)
    """
    doc_value = _r2(doc_value)
    if not tenders:
        # default tender: contract & employee (موظفين) are 100% credit/آجل (settled later — employee
        # deducted from salary; verified native ptclassif 11 → single credit tender, pay=0). All other
        # channels (cash/delivery/permanent/…) collect the full amount as cash now.
        if channel in ('contract', 'employee'):
            tenders = [{'pay_type': 'credit', 'amount': doc_value}]
        else:
            tenders = [{'pay_type': 'cash', 'amount': doc_value}]

    norm = [{'pay_type': t['pay_type'], 'amount': _r2(t['amount'])} for t in tenders]
    non_credit = sum((t['amount'] for t in norm if t['pay_type'] != 'credit'), Decimal('0'))
    doc_value_pay = _r2(non_credit)
    # patient_payment (ما يسدده المريض/العميل) = the cash the NAMED account pays now. Anonymous walk-ins
    # (cash/delivery) record 0; named channels record the collected cash — permanent=full, contract=co-pay,
    # employee=0 (all credit). Verified native: permanent 7025 patient=docvalue, contract 7824 patient=co-pay,
    # employee 7024 patient=0, cash 7021 / delivery 7831 patient=0.
    patient_payment = Decimal('0.00') if channel in ('cash', 'delivery') else doc_value_pay
    return doc_value_pay, patient_payment, norm
