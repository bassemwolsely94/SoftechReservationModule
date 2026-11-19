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


# ── D-18 server checkout: the نقدى / آجل split from the cashier's INTENT (doc 39 §2.6) ──────────────
# The browser no longer sends tender amounts on the new path, only what the cashier meant: the channel
# default, a fixed آجل amount, or ما يسدده المريض. The amounts are worked out here, in Decimal, so they
# add up to the amount due exactly (no ±0.01). Tenders stay نقدى / آجل only (POS screen scope).
TENDER_INTENT_KINDS = ('default', 'credit_portion', 'patient_copay')
_COLLECT_NOW_CHANNELS = ('cash', 'delivery')          # walk-in channels: no آجل
_CREDIT_DEFAULT_CHANNELS = ('contract', 'employee')   # split_payment's 100% آجل default


def _intent_amount(intent, key, label):
    raw = (intent or {}).get(key)
    if raw is None or str(raw).strip() == '':
        raise ValueError(f'أدخل {label}.')
    try:
        return _r2(Decimal(str(raw).strip()))
    except Exception:
        raise ValueError(f'{label} غير صحيح.')


def resolve_tenders(channel, doc_value, change_discount, intent, *, is_platform=False, claim_channels=()):
    """Pure (no DB, no I/O). Returns a list of {'pay_type', 'amount': Decimal} or None.

    None means "let writer.prepare_order apply today's rules" — channel default and the contract
    co-pay from personsdata — and is returned only when that default already equals the amount due
    (intent default, no خصم فكة, not a platform account). Otherwise the rows add up to
    due = doc_value − change_discount exactly: the first row is rounded and the second is due − first,
    so rounding can never break the sum. No zero rows, at most one نقدى and one آجل row, never a
    negative amount. Out-of-range intents raise ValueError with an Arabic message.
    """
    kind = str((intent or {}).get('kind') or 'default')
    if kind not in TENDER_INTENT_KINDS:
        raise ValueError('طريقة سداد غير معروفة.')
    cd = _r2(change_discount)
    if cd < 0:
        raise ValueError('خصم الفكة لا يمكن أن يكون سالباً.')
    if is_platform and kind != 'default':
        raise ValueError('حساب المنصة يُسجّل آجل بالكامل — لا يمكن تعديل السداد.')
    if kind == 'default' and cd == 0 and not is_platform:
        return None
    due = _r2(doc_value) - cd
    if due <= 0:
        raise ValueError('لا يوجد مبلغ مستحق للسداد (خصم الفكة يساوي قيمة الفاتورة أو يزيد عليها).')

    def _rows(first_type, first_amount, second_type):
        rows = []
        if first_amount > 0:
            rows.append({'pay_type': first_type, 'amount': first_amount})
        rest = due - first_amount
        if rest > 0:
            rows.append({'pay_type': second_type, 'amount': rest})
        return rows

    if is_platform:
        return [{'pay_type': 'credit', 'amount': due}]
    if kind == 'default':
        pay_type = 'credit' if channel in _CREDIT_DEFAULT_CHANNELS else 'cash'
        return [{'pay_type': pay_type, 'amount': due}]
    if kind == 'credit_portion':
        if channel in _COLLECT_NOW_CHANNELS:
            raise ValueError('لا يُسمح بالآجل في قناة نقدى/توصيل.')
        credit = _intent_amount(intent, 'credit', 'مبلغ الآجل')
        if credit < 0 or credit > due:
            raise ValueError(f'مبلغ الآجل يجب أن يكون بين 0 و {due}.')
        return _rows('cash', due - credit, 'credit')
    # patient_copay
    if channel not in claim_channels:
        raise ValueError('ما يسدده المريض متاح لقنوات التعاقد فقط.')
    patient = _intent_amount(intent, 'patient', 'ما يسدده المريض')
    if patient < 0 or patient > due:
        raise ValueError(f'ما يسدده المريض يجب أن يكون بين 0 و {due}.')
    return _rows('cash', patient, 'credit')
