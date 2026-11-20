"""
apps/delivery/small_orders.py — C20: delivery small-order and fee-less invoice report
(docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md §C20; measured in
docs/product-review/05_PROPOSAL_BACKLOG.md, delivery economics + owner answers).

Read-only, from the SOFTECH sales mirror we already hold (customers.PurchaseHistory / lines):
a delivery invoice = a sale (doc 115) on sales channel 90 (توصيل); the delivery fee = item code 2
«D.L.V.» (13 EGP a unit, cost 0); the rider gets RIDER_PER_FEE_UNIT per fee unit.

Per invoice:
  goods        = invoice lines without the fee line
  margin       = goods − goods cost (cost_at_sale × qty) + fee (the fee has no cost)
  rider_cost   = RIDER_PER_FEE_UNIT × max(1, fee units)
  small        = goods < SMALL_ORDER_EGP
  below_rider  = margin < rider_cost  (the order does not pay its own ride)
  fee-less     = no fee line; «unexplained» when the same customer has no fee-carrying delivery
                 invoice the same day or the day before / after (the owner: most fee-less invoices
                 are companion orders of one customer).
The customer is the invoice's PIC (softech_phcode), else its customer record.

Any minimum-order or fee rule is pricing and the owner's decision (stop-and-ask): this only shows
the numbers. Branch-level: the user's own branches (core.branch_scope), live branches only.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

DELIVERY_CHANNEL = '90'
SALE_DOC = '115'
FEE_ITEM_CODE = '2'                       # «D.L.V.»
RIDER_PER_FEE_UNIT = Decimal('10')
SMALL_ORDER_EGP = Decimal('100')
MAX_DAYS = 92
LIST_CAP = 2000
ZERO = Decimal('0')


def _customer_key(inv):
    pic = (inv['softech_phcode'] or '').strip()
    return f'pic:{pic}' if pic else f'c:{inv["customer_id"]}'


def _invoices(qs, start, end):
    from apps.branches.models import Branch
    return (qs.filter(sales_channel=DELIVERY_CHANNEL, doc_code=SALE_DOC,
                      invoice_date__date__gte=start, invoice_date__date__lte=end,
                      branch__kind__in=[Branch.KIND_HQ, Branch.KIND_RETAIL]))


def _line_totals(invoice_ids):
    from apps.customers.models import PurchaseHistoryLine
    is_fee = Q(item__softech_id=FEE_ITEM_CODE)
    cost = ExpressionWrapper(F('cost_at_sale') * F('quantity'), output_field=DecimalField(max_digits=16, decimal_places=3))
    rows = (PurchaseHistoryLine.objects.filter(purchase_id__in=invoice_ids).values('purchase_id')
            .annotate(total=Sum('line_total'), fee=Sum('line_total', filter=is_fee),
                      fee_units=Sum('quantity', filter=is_fee), cost=Sum(cost, filter=~is_fee)))
    return {r['purchase_id']: r for r in rows}


def classify(goods, cost, fee, fee_units):
    """(margin, rider_cost, small, below_rider) for one invoice — pure."""
    margin = goods - cost + fee
    rider_cost = RIDER_PER_FEE_UNIT * max(Decimal('1'), fee_units)
    return margin, rider_cost, goods < SMALL_ORDER_EGP, margin < rider_cost


def has_companion(key, day, fee_days) -> bool:
    """A fee-carrying invoice for the same customer the same day or one day either side."""
    days = fee_days.get(key, ())
    return any(abs((d - day).days) <= 1 for d in days)


def build(qs, start: dt.date, end: dt.date) -> dict:
    """`qs` = the PurchaseHistory rows the user may see (already branch-scoped)."""
    head = list(_invoices(qs, start - dt.timedelta(days=1), end + dt.timedelta(days=1))
                .values('id', 'branch_id', 'branch__softech_branch_id', 'branch__name_ar', 'branch__name',
                        'docnumber', 'invoice_date', 'softech_phcode', 'customer_id', 'customer__name'))
    totals = _line_totals([h['id'] for h in head])
    fee_days = defaultdict(set)
    rows = []
    for h in head:
        t = totals.get(h['id'], {})
        fee = t.get('fee') or ZERO
        day = timezone.localtime(h['invoice_date']).date() if h['invoice_date'] else None
        if day is None:
            continue
        key = _customer_key(h)
        if fee > 0:
            fee_days[key].add(day)
        if not (start <= day <= end):
            continue                                     # the edge days only find companions
        goods = (t.get('total') or ZERO) - fee
        margin, rider_cost, small, below = classify(goods, t.get('cost') or ZERO, fee, t.get('fee_units') or ZERO)
        rows.append({'invoice_id': h['id'], 'key': key, 'day': day, 'branch_id': h['branch_id'],
                     'branch_code': h['branch__softech_branch_id'],
                     'branch_name': h['branch__name_ar'] or h['branch__name'] or '',
                     'docnumber': h['docnumber'], 'customer': h['customer__name'] or '',
                     'pic': (h['softech_phcode'] or '').strip(),
                     'goods': goods, 'fee': fee, 'margin': margin, 'rider_cost': rider_cost,
                     'small': small, 'below_rider': below, 'feeless': fee <= 0})
    by_branch = {}
    flagged = []
    for r in rows:
        r['feeless_unexplained'] = r['feeless'] and not has_companion(r['key'], r['day'], fee_days)
        b = by_branch.setdefault(r['branch_id'], {
            'branch_id': r['branch_id'], 'branch_code': r['branch_code'], 'branch_name': r['branch_name'],
            'orders': 0, 'small': 0, 'below_rider': 0, 'feeless': 0, 'feeless_unexplained': 0,
            'goods': ZERO, 'fees': ZERO, 'feeless_goods': ZERO})
        b['orders'] += 1
        b['goods'] += r['goods']
        b['fees'] += r['fee']
        for k in ('small', 'below_rider', 'feeless', 'feeless_unexplained'):
            b[k] += int(r[k])
        if r['feeless_unexplained']:
            b['feeless_goods'] += r['goods']
        if r['small'] or r['below_rider'] or r['feeless_unexplained']:
            flagged.append(r)
    flagged.sort(key=lambda r: (r['margin'] - r['rider_cost'], r['day'], r['docnumber']))
    out_rows = [{k: (float(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, dt.date) else v))
                 for k, v in r.items() if k != 'key'} for r in flagged[:LIST_CAP]]
    branches = sorted(by_branch.values(), key=lambda b: b['branch_code'] or '')
    for b in branches:
        for k in ('goods', 'fees', 'feeless_goods'):
            b[k] = float(round(b[k], 2))
    count = len(rows)
    return {
        'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'rules': {'small_order_egp': float(SMALL_ORDER_EGP), 'rider_per_fee_unit': float(RIDER_PER_FEE_UNIT),
                  'fee_item_code': FEE_ITEM_CODE, 'channel': DELIVERY_CHANNEL},
        'totals': {'orders': count, 'small': sum(b['small'] for b in branches),
                   'below_rider': sum(b['below_rider'] for b in branches),
                   'feeless': sum(b['feeless'] for b in branches),
                   'feeless_unexplained': sum(b['feeless_unexplained'] for b in branches),
                   'flagged': len(flagged), 'shown': len(out_rows)},
        'by_branch': branches,
        'orders': out_rows,
    }


def to_excel(rep) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from core.export_safety import neutralise_formulas
    wb = Workbook()
    head_font, head_fill = Font(name='Arial', bold=True, color='FFFFFF'), PatternFill('solid', fgColor='022871')

    def sheet(ws, title, heads, rows):
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append(heads)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append(r)
        ws.freeze_panes = 'A2'

    def label(code, name):
        return f'{code} · {name}' if name else code          # never a bare branch code

    def yes(v):
        return 'نعم' if v else ''

    sheet(wb.active, 'حسب الفرع',
          ['الفرع', 'طلبات التوصيل', 'أقل من 100 ج', 'أقل من أجر الطيار', 'بدون رسوم', 'بدون رسوم وبدون طلب مرافق',
           'قيمة الأصناف', 'الرسوم', 'أصناف الطلبات بدون رسوم غير المفسَّرة'],
          [[label(b['branch_code'], b['branch_name']), b['orders'], b['small'], b['below_rider'], b['feeless'],
            b['feeless_unexplained'], b['goods'], b['fees'], b['feeless_goods']] for b in rep['by_branch']])
    sheet(wb.create_sheet(), 'الطلبات',
          ['التاريخ', 'الفرع', 'رقم الفاتورة', 'العميل', 'PIC', 'قيمة الأصناف', 'الرسوم', 'الهامش + الرسوم',
           'أجر الطيار', 'أقل من 100 ج', 'أقل من أجر الطيار', 'بدون رسوم وبدون طلب مرافق'],
          [[r['day'], label(r['branch_code'], r['branch_name']), r['docnumber'], r['customer'], r['pic'], r['goods'],
            r['fee'], r['margin'], r['rider_cost'], yes(r['small']), yes(r['below_rider']),
            yes(r['feeless_unexplained'])] for r in rep['orders']])
    neutralise_formulas(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
