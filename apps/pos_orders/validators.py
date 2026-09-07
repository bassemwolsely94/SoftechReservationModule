"""
apps/pos_orders/validators.py

Server-side validation for an Indirect-POS order — backend is the final authority
(UI checks are UX only). Every field is checked here before an order can go READY or
be pushed. Rules are layered:

  • structural   — branch/channel/doc_kind/store present and valid
  • line-level   — itemcode, qty>0, price>=0, discount 0..100, expiry/batch for stock
  • payment      — valid tender types, amounts, and balance vs the order total
  • channel      — contract/insurance need a named customer + a claim record
  • return       — must reference the original invoice

Things that need SOFTECH business logic we have NOT yet fully reverse-engineered are
flagged as TODO and validated only at the safe/basic level (see module docstring of
writer.py and the runbook §7): batch availability, out-of-stock→reservation, and the
POS-discount authority hierarchy (customer tier vs item line vs manager override).
"""
from decimal import Decimal

from django.conf import settings
from rest_framework.exceptions import ValidationError

from .models import CHANNEL_TO_PTCLASSIF, PAYTYPE_TO_SOFTECH, CLAIM_CHANNELS

# channels that sell to a named account and (for returnability) need claim/patient data. Native gives a
# companiesitems claim + branchesalescc to contract/insurance AND employee (موظفين) / permanent (عميل دائم)
# — all named-account channels — so they all use the per-contract emp-data form (verified 7024/7025).
# CLAIM_CHANNELS imported from .models (single source): contract/insurance/employee/permanent/
# compensation/donation/card_receipt — every named-account channel carries claim + credit records.
# channels where the balance is collected now (no credit line)
COLLECTED_CHANNELS = {'cash', 'delivery'}
# channels that must carry a PIC to save (SOFTECH "must provide PIC": Home Delivery = ON)
PIC_REQUIRED_CHANNELS = {'delivery'}

MAX_DISCOUNT = Decimal('100')
# limits from SOFTECH "Sales Setup Options" (2026-07-29)
MAX_FAKKA = Decimal('0.50')     # max L.C. for خصم فكة (change/rounding discount)
MAX_QTY_LINE = Decimal('10000')  # max item sales quantity per POS line


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def validate_order(order, *, for_push=False):
    """
    Validate an order. Raises rest_framework ValidationError({field: msg, ...}) with
    Arabic messages. `for_push=True` adds the stricter checks required before a real
    SOFTECH write (balance, claim data).
    """
    errs = {}

    # ── structural ────────────────────────────────────────────────────────────
    if not order.branch_id:
        errs['branch'] = 'الفرع مطلوب.'
    elif not order.branch.can_transact:
        errs['branch'] = 'الفرع مغلق أو غير قيد التشغيل — لا يمكن إنشاء معاملات.'
    if order.channel not in CHANNEL_TO_PTCLASSIF:
        errs['channel'] = 'قناة بيع غير صحيحة.'
    if order.doc_kind not in ('sale', 'return'):
        errs['doc_kind'] = 'نوع المستند غير صحيح.'
    if order.doc_kind == 'return' and not order.return_of_invoice:
        errs['return_of_invoice'] = 'رقم الفاتورة الأصلية مطلوب للمرتجع.'
    if not (order.softech_branchcode or '').strip():
        errs['softech_branchcode'] = 'كود فرع SOFTECH مطلوب.'
    if not (order.store_code or '').strip():
        errs['store_code'] = 'كود المخزن مطلوب.'

    # ── customer / channel ────────────────────────────────────────────────────
    if order.channel in CLAIM_CHANNELS and not (order.softech_pic or '').strip():
        errs['softech_pic'] = 'عميل التعاقد/التأمين يتطلب تحديد العميل (PIC).'
    # Home-Delivery PIC is a "must provide to SAVE" rule (SOFTECH config) — enforce it only on
    # the live push, never on the dry-run preview, so previewing a delivery order isn't blocked.
    if for_push and order.channel in PIC_REQUIRED_CHANNELS and not (order.softech_pic or '').strip():
        errs['softech_pic'] = 'التوصيل المنزلى يتطلب تحديد العميل (PIC) قبل الحفظ.'

    # ── change/rounding discount (خصم فكة) cap ────────────────────────────────
    if _d(order.change_discount) > MAX_FAKKA:
        errs['change_discount'] = f'خصم الفكة يتجاوز الحد المسموح ({MAX_FAKKA} جنيه).'

    # ── lines ─────────────────────────────────────────────────────────────────
    lines = list(order.lines.all())
    if not lines:
        errs['lines'] = 'يجب إضافة صنف واحد على الأقل.'
    line_errs = []
    for i, ln in enumerate(lines):
        le = {}
        if not (ln.softech_itemcode or '').strip():
            le['softech_itemcode'] = 'كود الصنف مطلوب.'
        if _d(ln.qty) <= 0:
            le['qty'] = 'الكمية يجب أن تكون أكبر من صفر.'
        elif _d(ln.qty) > MAX_QTY_LINE:
            le['qty'] = f'الكمية تتجاوز الحد الأقصى للسطر ({MAX_QTY_LINE:.0f}).'
        if _d(ln.item_sale_price) < 0:
            le['item_sale_price'] = 'سعر البيع غير صحيح.'
        if not (Decimal('0') <= _d(ln.cust_discp) <= MAX_DISCOUNT):
            le['cust_discp'] = 'نسبة الخصم يجب أن تكون بين 0 و 100.'
        if _d(ln.sale_tax_pct) < 0:
            le['sale_tax_pct'] = 'نسبة الضريبة غير صحيحة.'
        # NOTE: item_expiry is NO LONGER required on the order line — the writer's FEFO allocator
        # (_allocate_line) resolves the batch(es) live from stkbalexpiry at push time and reserves any
        # shortfall, exactly like native. Requiring it here would wrongly block reservation/partial
        # pushes (OOS lines legitimately have no expiry). Batch correctness is guaranteed by the writer.
        if le:
            le['index'] = i
            line_errs.append(le)
    if line_errs:
        errs['lines_detail'] = line_errs

    # ── payments ──────────────────────────────────────────────────────────────
    pays = list(order.payments.all())
    pay_errs = []
    for i, p in enumerate(pays):
        pe = {}
        if p.pay_type not in PAYTYPE_TO_SOFTECH:
            pe['pay_type'] = 'طريقة سداد غير صحيحة.'
        if _d(p.amount) <= 0:
            pe['amount'] = 'مبلغ السداد يجب أن يكون أكبر من صفر.'
        if p.pay_type == 'credit' and order.channel in COLLECTED_CHANNELS:
            pe['pay_type'] = 'لا يُسمح بالسداد الآجل في قناة نقدى/توصيل.'
        if pe:
            pe['index'] = i
            pay_errs.append(pe)
    if pay_errs:
        errs['payments_detail'] = pay_errs

    # ── push-only: points safety ──────────────────────────────────────────────
    # VERIFIED LIVE (2026-08-19): SOFTECH's finalization COPIES the pending header's personnewbal
    # (it does NOT recompute), and personnewbal's per-item value is internal to SOFTECH's POS
    # (not reproducible read-only, no DB proc). So our writer can't set it correctly, and a
    # points-eligible sale to an identified PIC would settle with personnewbal=0 → the enrolled
    # customer earns ZERO points. Block it from the live writer (such sales stay on the native
    # cashier) unless explicitly overridden. Contract/insurance earn 0 points, so they're fine.
    if for_push and getattr(settings, 'POS_BLOCK_POINTS_SALES', True):
        from . import points as _points
        if _points.channel_earns_points(order.channel) and (order.softech_pic or '').strip():
            errs['points'] = ('بيع مكتسب للنقاط لعميل مُعرّف (PIC) — يجب إتمامه من شاشة الكاشير '
                              'الأصلية حتى لا تُفقد نقاط العميل (شاشتنا لا تحسب personnewbal).')

    # ── push-only: balance + claim data ───────────────────────────────────────
    if for_push:
        if pays:
            total = sum((_d(p.amount) for p in pays), Decimal('0'))
            # the customer pays net of the rounding/change discount (خصم فكة)
            due = _d(order.doc_value) - _d(order.change_discount)
            if abs(total - due) > Decimal('0.01'):
                errs['payments'] = f'مجموع طرق السداد ({total}) لا يساوي المطلوب ({due}).'
        if order.channel in CLAIM_CHANNELS and not order.source_companies_raw:
            errs['claim'] = ('بيانات المريض/المطالبة مطلوبة لعميل التعاقد/التأمين '
                             '(انسخ من أمر يحتوي عليها حتى يكون قابلاً للإرجاع).')

    if errs:
        raise ValidationError(errs)
    return True
