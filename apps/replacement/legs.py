"""
apps/replacement/legs.py — executing an APPROVED case through the EXISTING SOFTECH writers
(doc 25 §11). Nothing here writes SOFTECH itself:

  purchase leg      → apps.invoices  SupplierInvoice  + writer.push_final   (doccode 10, virtual supplier)
  contract-sale leg → apps.pos_orders SoftechSalesOrder(channel=contract) + writer.push_order (pending → cashier)
                      or LINK the contract sale already made at the POS
  product-sale leg  → apps.pos_orders SoftechSalesOrder(channel=cash|delivery) + writer.push_order
  voucher (سداد)    → stays MANUAL at the cashier (owner D11); the case shows the exact instruction
                      and the nightly reconstruction links + checks the voucher

Every leg is a PostingOperation (unique idempotency key). With REPLACEMENT_POSTING_ENABLED off
(default) a post returns the writer's DRY-RUN plan and nothing reaches SOFTECH; the invoices / POS
writers keep their own gates as a second lock.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.lineage.models import DocumentRef as Ref

from . import authz
from . import config as C
from . import ledger as L
from .models import (CaseDocument as CD, CaseException as X, EntitlementLedgerEntry as E,
                     PostingOperation as Op, ReplacementCase as RC, ReplacementItem)
from .workflow import _audit, _bump, _lock

ACTIVE_OPS = (Op.ST_PLANNED, Op.ST_DRY_RUN, Op.ST_POSTING, Op.ST_POSTED, Op.ST_VERIFIED)
CENT = Decimal('0.01')


def posting_enabled() -> bool:
    return bool(C.get('POSTING_ENABLED'))


def purchase_token(case) -> str:
    return f'{C.get("PURCHASE_TOKEN_PREFIX")}{case.pk:07d}'


def _require_executable(case):
    if case.origin != RC.ORIGIN_LIVE:
        raise ValidationError('الحالات التاريخية للقراءة فقط.')
    if case.status not in (RC.STATUS_APPROVED, RC.STATUS_EXECUTING, RC.STATUS_ENTITLEMENT_ACTIVE,
                           RC.STATUS_SETTLED):
        raise ValidationError('الحالة غير معتمدة بعد.')


def _vendor(personcode):
    from apps.finance.recon_models import ReconParty
    from apps.invoices.models import VendorProfile
    v = VendorProfile.objects.filter(softech_personcode=personcode).first()
    if v:
        return v
    party = ReconParty.objects.filter(softech_personcode=personcode).first()
    name = (party.name if party and party.name else C.supplier_cfg(personcode).get('label') or f'مورد {personcode}')
    return VendorProfile.objects.create(name=name[:200], softech_personcode=personcode,
                                        notes='مورد بدل الروشتة (حساب افتراضي) — أُنشئ تلقائياً')


# ─────────────────────────────────────────────────────────────────────────────
# Remaining entitlement (live)
# ─────────────────────────────────────────────────────────────────────────────

def available(case) -> dict:
    """What the patient can still take. Native ledger (vouchers already linked) + product orders
    prepared/posted in this case whose voucher is not yet linked (reserved)."""
    if case.purchase_ref_id:
        native_bal = L.balance(case)
    else:
        native_bal = case.entitlement
    reserved = sum((o.expected_value for o in case.operations.filter(
        kind=Op.KIND_PRODUCT_SALE, status__in=ACTIVE_OPS).exclude(result__has_key='voucher_linked')),
        Decimal('0'))
    return {'entitlement': case.entitlement, 'balance': native_bal, 'reserved': reserved,
            'available': max(Decimal('0'), native_bal - reserved)}


# ─────────────────────────────────────────────────────────────────────────────
# Purchase leg
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def prepare_purchase(case_id, *, user, version, request=None) -> Op:
    """Build the virtual-supplier purchase invoice from the APPROVED calculation (once per case)."""
    from apps.invoices.models import InvoiceLine, SupplierInvoice
    case = _lock(case_id, version)
    authz.require(user, 'post', case=case)
    _require_executable(case)
    key = f'{case.pk}:purchase'
    op = Op.objects.filter(idempotency_key=key).first()
    if op and op.status != Op.ST_CANCELLED:
        return op
    calc = case.current_calc
    if calc is None:
        raise ValidationError('لا يوجد حساب معتمد.')
    inv = SupplierInvoice.objects.create(
        branch=case.branch, doc_kind='purchase', vendor=_vendor(calc.rule.supplier_personcode),
        created_by=user, status='confirmed', supplier_name=_vendor(calc.rule.supplier_personcode).name,
        invoice_number=purchase_token(case), invoice_date=timezone.localdate(),
        notes=f'بدل الروشتة {case.number}')
    items = {i.itemcode: i for i in case.items.all()}
    for n, l in enumerate(calc.lines):
        it = items[l['itemcode']]
        InvoiceLine.objects.create(
            invoice=inv, item=it.item, manual_name=it.item_name, quantity=Decimal(l['qty']),
            public_price=Decimal(l['public_price']), discount_pct=Decimal(l['deduction_pct']),
            unit_price=Decimal(l['unit_net']), line_total=Decimal(l['entitlement']),
            is_confirmed=True, order=n)
    if op:                                   # a cancelled op is replaced by a fresh one
        op.idempotency_key = f'{key}:void:{op.pk}'
        op.save(update_fields=['idempotency_key'])
    op = Op.objects.create(case=case, kind=Op.KIND_PURCHASE, idempotency_key=key, supplier_invoice=inv,
                           expected_value=calc.entitlement, requested_by=user)
    case.status = RC.STATUS_EXECUTING
    _bump(case, 'status')
    _audit('replacement_leg_prepared', case, user, request=request,
           new={'kind': op.kind, 'op': str(op.op_id), 'invoice': inv.pk, 'token': purchase_token(case),
                'expected': str(op.expected_value)})
    return op


def _verify_purchase(op, inv) -> list[str]:
    """Post-write verification against what was APPROVED (never trust 'ok' alone, §62)."""
    from apps.invoices import writer as W
    problems = []
    if inv.status != 'finalized' or not inv.softech_docnumber:
        problems.append('الفاتورة لم تُرحّل نهائياً')
    _, header = W.compute(inv)
    total = Decimal(str(header.get('doc_value', 0))).quantize(CENT)
    if abs(total - op.expected_value) > Decimal('0.05'):
        problems.append(f'قيمة الفاتورة {total} ≠ الرصيد المعتمد {op.expected_value}')
    if inv.vendor.softech_personcode != op.case.current_calc.rule.supplier_personcode:
        problems.append('المورد لا يطابق القاعدة')
    rb = inv.erp_readback or {}
    if rb and rb.get('ok') is False:
        problems.append('قراءة التحقق من SOFTECH فشلت')
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# Sales legs (contract / products)
# ─────────────────────────────────────────────────────────────────────────────

def _order_lines(items):
    from apps.catalog.models import Item
    out = []
    for it in items:
        item = it['item'] if 'item' in it else Item.objects.get(pk=it['item_id'])
        out.append({'item': item.pk, 'softech_itemcode': item.softech_id, 'qty': str(it['qty']),
                    'item_sale_price': str(item.pack_price or 0), 'sale_tax_pct': str(item.sale_tax_pct or 0),
                    'cust_discp': str(it.get('cust_discp') or 0)})
    return out


def _create_order(case, user, *, channel, lines, claim=None, customer_name=''):
    from apps.pos_orders.serializers import OrderSerializer
    data = {'channel': channel, 'branch': case.branch_id, 'softech_pic': case.softech_pic,
            'customer_name': customer_name or case.patient_name, 'lines': lines,
            'notes': f'بدل الروشتة {case.number}'}           # PG-only field — never written to SOFTECH
    if channel == 'contract':
        data['cust_branch_code'] = case.contract_personcode
        if claim:
            data['claim'] = claim
    if case.customer_id:
        data['customer'] = case.customer_id
    ser = OrderSerializer(data=data)
    ser.is_valid(raise_exception=True)
    import uuid
    return ser.save(created_by=user, seller_usercode=(user.softech_user_id or '').strip(),
                    client_token=uuid.uuid4())


def estimate_order(lines) -> Decimal:
    """Indicative total via the POS pricing engine (authoritative pricing happens in the POS writer)."""
    from apps.pos_orders import pricing
    total = Decimal('0')
    for l in lines:
        c = pricing.compute_line(item_sale_price=Decimal(l['item_sale_price']), sale_tax_pct=Decimal(l['sale_tax_pct']),
                                 qty=Decimal(l['qty']), cust_discp=Decimal(l['cust_discp']))
        total += Decimal(str(c['trans_price_total']))
    return total.quantize(CENT)


@transaction.atomic
def prepare_contract_sale(case_id, *, user, version, claim=None, request=None) -> Op:
    """Draft the contract (insurance) sale of the WHOLE prescription — dispensed + replaced items —
    as a pending order for the cashier. Type A only, and only if no contract sale is linked yet."""
    case = _lock(case_id, version)
    authz.require(user, 'post', case=case)
    _require_executable(case)
    if case.source_type != RC.SOURCE_INSURANCE_RX:
        raise ValidationError('بيع التعاقد خاص بحالات روشتة التأمين.')
    if not case.contract_personcode:
        raise ValidationError('حدد حساب التعاقد أولاً.')
    if case.documents.filter(role=CD.ROLE_CONTRACT_SALE, status=CD.STATUS_CONFIRMED).exists():
        raise ValidationError('فاتورة التعاقد مرتبطة بالحالة بالفعل.')
    key = f'{case.pk}:contract'
    op = Op.objects.filter(idempotency_key=key).exclude(status=Op.ST_CANCELLED).first()
    if op:
        return op
    rx = [{'item': i.item, 'qty': i.qty_prescribed or i.qty_replaced}
          for i in case.items.select_related('item') if i.item_id]
    claim = dict(claim or {})
    claim.setdefault('roshettano', case.prescription_no)
    order = _create_order(case, user, channel='contract', lines=_order_lines(rx), claim=claim)
    Op.objects.filter(idempotency_key=key).update(idempotency_key=f'{key}:void:{timezone.now().timestamp()}')
    op = Op.objects.create(case=case, kind=Op.KIND_CONTRACT_SALE, idempotency_key=key, sales_order=order,
                           expected_value=estimate_order(_order_lines(rx)), requested_by=user)
    _bump(case, 'status')
    _audit('replacement_leg_prepared', case, user, request=request,
           new={'kind': op.kind, 'op': str(op.op_id), 'order': order.pk})
    return op


@transaction.atomic
def link_contract_sale(case_id, *, user, version, branchcode, docnumber, docdate, request=None) -> RC:
    """Attach the contract sale already made at the POS / SOFTECH (the common path)."""
    from apps.customers.models import PurchaseHistory
    from .reconstruct import ref_for_sale
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    ph = (PurchaseHistory.objects.filter(branch__softech_branch_id=branchcode, doc_code='115',
                                         docnumber=str(docnumber), invoice_date__date=docdate)
          .select_related('branch').first())
    if ph is None:
        raise ValidationError('لم يتم العثور على فاتورة التعاقد في المرآة (قد تحتاج مزامنة).')
    if ph.sales_channel not in C.CONTRACT_CHANNELS:
        raise ValidationError('هذه ليست فاتورة تعاقد.')
    if case.softech_pic and (ph.softech_phcode or '').strip() != case.softech_pic:
        raise ValidationError('فاتورة التعاقد لمريض آخر.')
    ref = ref_for_sale(ph)
    CD.objects.update_or_create(case=case, document=ref, role=CD.ROLE_CONTRACT_SALE, defaults={
        'status': CD.STATUS_CONFIRMED, 'origin': 'manual', 'confidence': 100, 'amount': ph.total_amount,
        'evidence': [{'signal': 'human', 'points': 100, 'detail': f'ربط يدوي بواسطة {user.full_name}'}]})
    if not case.contract_personcode:
        case.contract_personcode = (ph.cust_branch_code or '').strip()
    _bump(case, 'contract_personcode')
    _audit('replacement_contract_linked', case, user, request=request, new={'sale': str(ref)})
    return case


@transaction.atomic
def prepare_product_sale(case_id, *, user, version, channel, items, request=None) -> Op:
    """Draft a cash / home-delivery sale of replacement products funded by the entitlement.
    Products are priced by the existing POS pricing engine; the patient may pay a difference
    (customer top-up) up to MAX_TOPUP_PCT of what is still available."""
    case = _lock(case_id, version)
    authz.require(user, 'post', case=case)
    _require_executable(case)
    if channel not in ('cash', 'delivery'):
        raise ValidationError('قناة البيع يجب أن تكون نقدي أو توصيل.')
    if case.settlement_mode == RC.MODE_CASH:
        raise ValidationError('هذه حالة صرف نقدي — لا يوجد صرف منتجات.')
    if not items:
        raise ValidationError('أضف منتجات.')
    lines = _order_lines(items)
    total = estimate_order(lines)
    av = available(case)
    funded = min(total, av['available'])
    topup = total - funded
    if funded <= 0:
        raise ValidationError('لا يوجد رصيد متاح.')
    if topup > av['available'] * C.get('MAX_TOPUP_PCT'):
        raise ValidationError(f'قيمة المنتجات ({total}) تتجاوز الرصيد المتاح ({av["available"]}) بأكثر من المسموح.')
    order = _create_order(case, user, channel=channel, lines=lines)
    n = case.operations.filter(kind=Op.KIND_PRODUCT_SALE).count() + 1
    op = Op.objects.create(case=case, kind=Op.KIND_PRODUCT_SALE, idempotency_key=f'{case.pk}:product:{n}',
                           sales_order=order, expected_value=funded, requested_by=user,
                           result={'estimated_total': str(total), 'customer_topup': str(topup)})
    _bump(case, 'status')
    _audit('replacement_leg_prepared', case, user, request=request,
           new={'kind': op.kind, 'op': str(op.op_id), 'order': order.pk, 'total': str(total),
                'funded': str(funded), 'topup': str(topup)})
    return op


# ─────────────────────────────────────────────────────────────────────────────
# Posting (all legs)
# ─────────────────────────────────────────────────────────────────────────────

def _fail(op, case, user, msg, request=None):
    op.status, op.error = Op.ST_FAILED, msg[:2000]
    op.save(update_fields=['status', 'error', 'updated_at'])
    X.objects.update_or_create(case=case, exception_type='posting_failed', key=str(op.op_id),
                               defaults={'severity': X.SEV_HIGH, 'status': X.STATUS_OPEN, 'detail': msg[:2000],
                                         'amount': op.expected_value})
    _audit('replacement_leg_failed', case, user, request=request, new={'op': str(op.op_id), 'error': msg[:500]})


@transaction.atomic
def post(case_id, op_id, *, user, version, force=False, request=None) -> Op:
    """Post one prepared leg through its writer. Idempotent: a posted op is returned as-is; the
    writers' own guards (docnumber2 dup-check / client_token + vf2 recovery) block a 2nd write."""
    from apps.invoices import writer as IW
    from apps.pos_orders import writer as PW
    case = _lock(case_id, version)
    authz.require(user, 'post', case=case)
    _require_executable(case)
    op = Op.objects.select_for_update().get(op_id=op_id, case=case)
    if (op.result or {}).get('native'):
        raise ValidationError('هذا المستند مُدخل يدوياً في SOFTECH — لا يُرحّل من المنصة (أعد ربطه إن كان الرقم خطأ).')
    if op.status in (Op.ST_POSTED, Op.ST_VERIFIED):
        return op
    if op.status in (Op.ST_CANCELLED, Op.ST_POSTING):
        raise ValidationError('لا يمكن ترحيل هذه العملية الآن.')
    live = posting_enabled()
    try:
        if op.kind == Op.KIND_PURCHASE:
            res = IW.push_final(op.supplier_invoice, dry_run=not live, force=force)
        else:
            res = PW.push_order(op.sales_order, dry_run=not live, live=live)
    except Exception as exc:                       # writer raised after rolling back
        _fail(op, case, user, f'{type(exc).__name__}: {exc}', request)
        return op
    mode = res.get('mode')
    if mode == 'dry_run':
        op.status, op.result = Op.ST_DRY_RUN, {**op.result, 'plan': res.get('plan'), 'at': timezone.now().isoformat()}
        op.save(update_fields=['status', 'result', 'updated_at'])
        _audit('replacement_leg_posted', case, user, request=request, new={'op': str(op.op_id), 'mode': 'dry_run'})
        return op
    if mode == 'queued':
        op.status, op.error = Op.ST_PLANNED, 'الفرع غير متصل — سيُعاد المحاولة'
        op.save(update_fields=['status', 'error', 'updated_at'])
        return op
    if not res.get('ok') and mode not in ('idempotent', 'idempotent_recovered'):
        _fail(op, case, user, f'الترحيل لم يكتمل: {res}', request)
        return op
    op.result_docnumber = str(res.get('docnumber') or '')
    op.result = {**op.result, 'writer': {k: v for k, v in res.items() if k != 'plan'}}
    if op.kind == Op.KIND_PURCHASE:
        inv = op.supplier_invoice
        inv.refresh_from_db()
        problems = _verify_purchase(op, inv)
        if problems:
            _fail(op, case, user, 'تحقق ما بعد الترحيل فشل: ' + '؛ '.join(problems), request)
            return op
        ref = Ref.objects.get_or_create(
            system=Ref.SYSTEM_SOFTECH, branchcode=inv.softech_branchcode, doccode='10',
            docnumber=str(int(inv.softech_docnumber)), docdate=inv.softech_docdate,
            defaults={'doc_kind': Ref.KIND_PURCHASE, 'amount': op.expected_value,
                      'party_code': inv.vendor.softech_personcode, 'party_name': inv.vendor.name[:300],
                      'source_model': 'invoices.supplierinvoice', 'source_pk': inv.pk})[0]
        case.purchase_ref, case.purchase_date = ref, inv.softech_docdate
        CD.objects.get_or_create(case=case, document=ref, role=CD.ROLE_PURCHASE, defaults={
            'status': CD.STATUS_CONFIRMED, 'origin': 'posted', 'confidence': 100, 'amount': op.expected_value})
        L.ensure(case, E.TYPE_CREATED, op.expected_value, document=ref, user=user,
                 note=f'فاتورة شراء {ref.label} — {inv.vendor.name}', origin=RC.ORIGIN_LIVE)
        case.status = RC.STATUS_ENTITLEMENT_ACTIVE
        case.outstanding = L.balance(case)
        _bump(case, 'purchase_ref', 'purchase_date', 'status', 'outstanding')
        op.status = Op.ST_VERIFIED
    else:
        op.status = Op.ST_POSTED              # pending at the cashier; verified when it settles
        _bump(case, 'status')
    op.save(update_fields=['status', 'result_docnumber', 'result', 'updated_at'])
    _audit('replacement_leg_posted', case, user, request=request,
           new={'op': str(op.op_id), 'kind': op.kind, 'docnumber': op.result_docnumber, 'status': op.status})
    return op


def voucher_instruction(case) -> dict | None:
    """What the CASHIER must enter natively (D11) — supplier, invoice and amount — so the
    voucher links cleanly and the nightly check can verify it."""
    if not case.purchase_ref_id:
        return None
    pending = [o for o in case.operations.filter(kind=Op.KIND_PRODUCT_SALE, status__in=(Op.ST_POSTED, Op.ST_VERIFIED))
               if 'voucher_linked' not in o.result]
    amount = sum((o.expected_value for o in pending), Decimal('0'))
    if case.settlement_mode in (RC.MODE_CASH, RC.MODE_MIXED):
        amount = max(amount, Decimal('0'))
    return {'supplier': case.supplier_personcode, 'supplier_name': case.purchase_ref.party_name,
            'invoice': case.purchase_ref.docnumber, 'branch': case.purchase_ref.branchcode,
            'amount_for_products': str(amount), 'balance': str(L.balance(case)),
            'note': f'سداد جزء من فاتورة رقم {case.purchase_ref.docnumber}'}


# ─────────────────────────────────────────────────────────────────────────────
# Parallel entry (owner 2026-10-07): staff post the purchase / product sales NATIVELY in SOFTECH
# and type the document number here. We only LINK and VERIFY — nothing is written to SOFTECH.
# ─────────────────────────────────────────────────────────────────────────────

def _native_key(branchcode, docnumber, docdate) -> dict:
    from .reconstruct import _docno
    return {'branchcode': str(branchcode).strip(), 'docnumber': _docno(docnumber),
            'docdate': docdate.isoformat()}


def _case_touched_by_people(case) -> bool:
    """A reconstructed case someone worked on is history — never retired automatically."""
    from apps.lineage.models import DocumentEdge as Edge
    refs = list(case.documents.values_list('document_id', flat=True))
    return (case.origin != RC.ORIGIN_RECONSTRUCTED or case.operations.exists()
            or case.documents.filter(origin='manual').exists()
            or case.exceptions.filter(status__in=[X.STATUS_ACK, X.STATUS_RESOLVED]).exists()
            or Edge.objects.filter(decided_by__isnull=False)
                .filter(Q(from_ref_id__in=refs) | Q(to_ref_id__in=refs)).exists())


def _retire_duplicate(dup, live_case, user):
    """The nightly run built a case from a purchase that belongs to a live case. Retire it: reverse
    its ledger (append-only — compensating entries), drop its derived links/items/exceptions, free
    the purchase for the live case and mark it cancelled. Audited."""
    for e in L.active_entries(dup):
        L.reverse(e, note=f'حالة مكررة — الفاتورة تخص الحالة {live_case.number}', user=user)
    dup.documents.all().delete()
    dup.items.all().delete()
    dup.exceptions.all().delete()
    old_ref = dup.purchase_ref_id
    dup.purchase_ref = dup.purchase_invoice = None
    dup.status, dup.outstanding = RC.STATUS_CANCELLED, Decimal('0')
    dup.notes = (dup.notes + f'\nأُلغيت: فاتورة الشراء مربوطة يدوياً بالحالة {live_case.number}').strip()
    dup.save(update_fields=['purchase_ref', 'purchase_invoice', 'status', 'outstanding', 'notes', 'updated_at'])
    _audit('replacement_case_cancelled', dup, user, new={'superseded_by': live_case.number,
                                                          'purchase_ref': str(old_ref)})


def resolve_native_purchase(op, *, user=None) -> bool:
    """Attach the natively-posted purchase once the A/P mirror has it, then let reconstruction
    book the entitlement, vouchers and returns exactly as for any case. True when attached."""
    from apps.finance.recon_models import APInvoice
    from . import reconstruct as R
    from datetime import date
    nk = (op.result or {}).get('native') or {}
    case = RC.objects.select_for_update().get(pk=op.case_id)
    inv = (APInvoice.objects.select_related('party')
           .filter(branchcode=nk.get('branchcode'), doccode='10', docnumber=nk.get('docnumber'),
                   docdate=date.fromisoformat(nk['docdate'])).first())
    if inv is None:
        if not op.error:
            op.error = 'لم تظهر الفاتورة في مرآة الموردين بعد — ستُربط تلقائياً بعد المزامنة.'
            op.save(update_fields=['error', 'updated_at'])
        return False
    calc = case.current_calc
    want = calc.rule.supplier_personcode if calc else case.supplier_personcode
    if want and inv.party.softech_personcode != want:
        _fail(op, case, user, f'فاتورة SOFTECH على المورد {inv.party.softech_personcode} '
                              f'وقاعدة الحالة على المورد {want} — راجع الرقم.')
        return False
    p_ref = R.ref_for_apinvoice(inv)
    other = RC.objects.select_for_update().filter(purchase_ref=p_ref).exclude(pk=case.pk).first() \
        or RC.objects.select_for_update().filter(purchase_invoice=inv).exclude(pk=case.pk).first()
    if other is not None:
        if _case_touched_by_people(other):
            _fail(op, case, user, f'فاتورة الشراء مرتبطة بالحالة {other.number} — راجعها قبل الربط.')
            return False
        _retire_duplicate(other, case, user)
    case.purchase_ref, case.purchase_date = p_ref, inv.docdate
    case.supplier_personcode = case.supplier_personcode or inv.party.softech_personcode
    case.save(update_fields=['purchase_ref', 'purchase_date', 'supplier_personcode', 'updated_at'])
    R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics(), user=user)    # live → attaches, never duplicates
    op.status, op.error = Op.ST_VERIFIED, ''
    op.result = {**op.result, 'native': {**nk, 'doc_value': str(inv.doc_value),
                                         'verified_at': timezone.now().isoformat()}}
    op.save(update_fields=['status', 'error', 'result', 'updated_at'])
    return True


@transaction.atomic
def link_native_purchase(case_id, *, user, version, branchcode, docnumber, docdate, request=None) -> RC:
    """Record the purchase the staff posted natively in SOFTECH (parallel entry). Attached now if the
    mirror already has it, otherwise by the scheduled check after the next A/P sync."""
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    _require_executable(case)
    nk = _native_key(branchcode, docnumber, docdate)
    if not nk['branchcode'] or not nk['docnumber']:
        raise ValidationError('أدخل الفرع ورقم فاتورة الشراء.')
    key = f'{case.pk}:purchase'
    op = Op.objects.filter(idempotency_key=key).first()
    if op and op.status != Op.ST_CANCELLED:
        if op.supplier_invoice_id:
            raise ValidationError('فاتورة الشراء مُجهّزة للترحيل من المنصة — لا يمكن ربط فاتورة يدوية معها.')
        if (op.result or {}).get('native', {}).get('docnumber') == nk['docnumber'] and op.status != Op.ST_FAILED:
            return case                                   # same link again → idempotent
        if op.status == Op.ST_VERIFIED:
            raise ValidationError('الحالة مرتبطة بالفعل بفاتورة شراء أخرى.')
        op.idempotency_key = f'{key}:void:{op.pk}'        # replace a pending / failed link
        op.status = Op.ST_CANCELLED
        op.save(update_fields=['idempotency_key', 'status', 'updated_at'])
    clash = (Op.objects.filter(kind=Op.KIND_PURCHASE, result_docnumber=nk['docnumber'],
                               result__native__branchcode=nk['branchcode'], result__native__docdate=nk['docdate'])
             .exclude(case=case).exclude(status__in=[Op.ST_CANCELLED, Op.ST_FAILED]).select_related('case').first())
    if clash:
        raise ValidationError(f'هذه الفاتورة مربوطة بالحالة {clash.case.number}.')
    calc = case.current_calc
    op = Op.objects.create(case=case, kind=Op.KIND_PURCHASE, idempotency_key=key, status=Op.ST_POSTED,
                           result_docnumber=nk['docnumber'], expected_value=calc.entitlement if calc else 0,
                           requested_by=user, result={'native': nk, 'linked_by': user.full_name})
    case.status = RC.STATUS_EXECUTING
    _bump(case, 'status')
    _audit('replacement_leg_posted', case, user, request=request,
           new={'op': str(op.op_id), 'kind': op.kind, 'mode': 'native_link', **nk})
    resolve_native_purchase(op, user=user)
    return RC.objects.get(pk=case.pk)


def resolve_pending_native_links(user=None) -> dict:
    """Scheduled: attach every pending natively-posted purchase the mirror now has."""
    out = {'pending': 0, 'attached': 0}
    for op_id in Op.objects.filter(kind=Op.KIND_PURCHASE, status=Op.ST_POSTED, supplier_invoice__isnull=True,
                                   result__has_key='native').values_list('pk', flat=True):
        out['pending'] += 1
        with transaction.atomic():
            op = Op.objects.select_for_update().get(pk=op_id)
            if op.status == Op.ST_POSTED and resolve_native_purchase(op, user=user):
                out['attached'] += 1
    return out


@transaction.atomic
def link_native_product_sale(case_id, *, user, version, branchcode, docnumber, docdate, request=None) -> RC:
    """Record a cash / delivery sale of replacement products made natively at the POS. The case then
    owns that receipt, so the cashier's سداد voucher is matched to it and the leg is verified."""
    from apps.customers.models import PurchaseHistory
    from .reconstruct import ref_for_sale, tabdeel_pics
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    _require_executable(case)
    if case.settlement_mode == RC.MODE_CASH:
        raise ValidationError('هذه حالة صرف نقدي — لا يوجد صرف منتجات.')
    nk = _native_key(branchcode, docnumber, docdate)
    ph = (PurchaseHistory.objects.filter(branch__softech_branch_id=nk['branchcode'], doc_code='115',
                                         docnumber=nk['docnumber'], invoice_date__date=docdate)
          .select_related('branch').first())
    if ph is None:
        raise ValidationError('لم يتم العثور على فاتورة المنتجات في المرآة (قد تحتاج مزامنة).')
    if ph.sales_channel in C.CONTRACT_CHANNELS:
        raise ValidationError('هذه فاتورة تعاقد — اربطها كفاتورة التعاقد.')
    pic = (ph.softech_phcode or '').strip()
    if case.softech_pic and pic and pic != case.softech_pic and pic not in tabdeel_pics():
        raise ValidationError('فاتورة المنتجات على عميل آخر (المسموح: كود المريض أو حساب «عميل تبديل»).')
    ref = ref_for_sale(ph)
    elsewhere = (CD.objects.filter(document=ref, role=CD.ROLE_PRODUCT_SALE, status=CD.STATUS_CONFIRMED)
                 .exclude(case=case).select_related('case').first()) or \
        (Op.objects.filter(kind=Op.KIND_PRODUCT_SALE, result__native_receipt=ph.pk)
         .exclude(case=case).exclude(status=Op.ST_CANCELLED).select_related('case').first())
    if elsewhere:
        raise ValidationError(f'فاتورة المنتجات مربوطة بالحالة {elsewhere.case.number}.')
    key = f'{case.pk}:native:{ref.pk}'
    op = Op.objects.filter(idempotency_key=key).first()
    if op:
        return case
    total = Decimal(str(ph.total_amount or 0)).quantize(CENT)
    funded = min(total, available(case)['available']) if case.purchase_ref_id else total
    op = Op.objects.create(case=case, kind=Op.KIND_PRODUCT_SALE, idempotency_key=key, status=Op.ST_POSTED,
                           result_docnumber=nk['docnumber'], expected_value=funded, requested_by=user,
                           result={'native': nk, 'native_receipt': ph.pk, 'linked_by': user.full_name,
                                   'estimated_total': str(total), 'customer_topup': str(total - funded)})
    _bump(case, 'status')
    _audit('replacement_leg_posted', case, user, request=request,
           new={'op': str(op.op_id), 'kind': op.kind, 'mode': 'native_link', **nk, 'total': str(total)})
    return case
