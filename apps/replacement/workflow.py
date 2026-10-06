"""
apps/replacement/workflow.py — the LIVE بدل case lifecycle (doc 25 §5, Phase 1).

    DRAFT ──calculate──▶ CALCULATED ──submit──▶ AWAITING_APPROVAL ──approve──▶ APPROVED
      ▲  (edit items)        │  ▲                    │ reject / return            │ legs (legs.py)
      └──────── reopen ◀─────┘  └────────────────────┘                            ▼
                                                                         EXECUTING → ENTITLEMENT_ACTIVE …

Rules enforced here (server-side, never in React):
  • every mutation is atomic, locks the case row and checks the client's `version`
    (optimistic concurrency → 409 on a stale screen)
  • a submitted case is LOCKED: items/calculation cannot change until rejected or reopened
  • approval is bound to the calculation fingerprint; it goes through apps.approvals
    (existing inbox) and maker-checker (approver ≠ creator) is enforced twice
  • every transition is written to AuditLog with the case correlation id
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.models import AuditLog

from . import authz
from . import config as C
from . import rules as RULES
from .models import CaseException as X, PostingOperation as Op, ReplacementCase as RC, ReplacementItem

EDITABLE = (RC.STATUS_DRAFT, RC.STATUS_CALCULATED)
POSTED_OPS = (Op.ST_POSTING, Op.ST_POSTED, Op.ST_VERIFIED)


class StaleVersion(ValidationError):
    """The client acted on an out-of-date case (someone else changed it)."""


def _audit(action, case, user, *, old=None, new=None, note='', request=None, **extra):
    AuditLog.log(action, user=user, obj=case, old_data=old, new_data=new, note=(note or '')[:255],
                 extra={'correlation_id': str(case.correlation_id), **extra}, request=request)


def _lock(case_id, version=None) -> RC:
    case = RC.objects.select_for_update(of=('self',)).get(pk=case_id)
    if version is not None and int(version) != case.version:
        raise StaleVersion('تم تعديل الحالة من مستخدم آخر — أعد تحميل الصفحة.')
    return case


def _bump(case, *fields):
    case.version += 1
    case.save(update_fields=list(fields) + ['version', 'updated_at'])


def _require_editable(case):
    if case.origin != RC.ORIGIN_LIVE:
        raise ValidationError('الحالات التاريخية للقراءة فقط.')
    if case.status not in EDITABLE or case.locked_at:
        raise ValidationError('الحالة مقفلة — لا يمكن التعديل بعد الإرسال للاعتماد.')


def _item_price(item) -> Decimal:
    price = Decimal(str(item.pack_price or 0))
    if price <= 0:
        raise ValidationError(f'لا يوجد سعر جمهور للصنف {item.softech_id}.')
    return price


# ─────────────────────────────────────────────────────────────────────────────
# Create / edit
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_case(*, user, branch, source_type, settlement_mode, softech_pic='', contract_personcode='',
                items=(), is_shortage_item=False, prescription_no='', approval_no='', notes='',
                from_sale=None, request=None) -> RC:
    """items: [{item_id, qty}] to replace. from_sale: a customers.PurchaseHistory contract sale
    whose lines prefill the prescription (dispensed items) and the patient/contract."""
    from apps.catalog.models import Item
    from apps.customers.models import Customer
    if source_type not in dict(RC.SOURCE_CHOICES) or settlement_mode not in ('products', 'cash', 'mixed'):
        raise ValidationError('نوع الحالة أو طريقة الصرف غير صالحة.')
    probe = RC(branch=branch, source_type=source_type, settlement_mode=settlement_mode)
    authz.require(user, 'create', case=probe)
    if from_sale is not None:
        softech_pic = softech_pic or (from_sale.softech_phcode or '').strip()
        contract_personcode = contract_personcode or (from_sale.cust_branch_code or '').strip()
    if source_type == RC.SOURCE_INSURANCE_RX and not softech_pic:
        raise ValidationError('حالة روشتة التأمين تتطلب كود المريض (PIC).')
    cust = Customer.objects.filter(softech_pic__iexact=softech_pic).first() if softech_pic else None
    today = timezone.localdate()
    case = RC.objects.create(
        origin=RC.ORIGIN_LIVE, status=RC.STATUS_DRAFT, source_type=source_type,
        settlement_mode=settlement_mode, branch=branch, branchcode=branch.softech_branch_id,
        customer=cust, softech_pic=softech_pic, patient_name=cust.name if cust else '',
        contract_personcode=contract_personcode, supplier_personcode='', purchase_date=today,
        is_shortage_item=is_shortage_item, prescription_no=prescription_no, approval_no=approval_no,
        notes=notes, created_by=user, rules_version=C.RULES_VERSION)
    case.assign_number()
    if from_sale is not None:
        from .reconstruct import ref_for_sale
        from .models import CaseDocument as CD
        CD.objects.create(case=case, document=ref_for_sale(from_sale), role=CD.ROLE_CONTRACT_SALE,
                          status=CD.STATUS_CONFIRMED, origin='manual', confidence=100,
                          amount=from_sale.total_amount,
                          evidence=[{'signal': 'human', 'points': 100, 'detail': 'اختيرت عند إنشاء الحالة'}])
        rx = {}                          # one row per item: SOFTECH pre-splits an item over several lines
        for ln in from_sale.lines.select_related('item'):
            if ln.item_id:
                r = rx.setdefault(ln.item_id, {'ln': ln, 'qty': Decimal('0')})
                r['qty'] += ln.quantity
        for r in rx.values():
            ln = r['ln']
            ReplacementItem.objects.create(
                case=case, item=ln.item, itemcode=ln.item.softech_id, item_name=ln.item.name[:255],
                disposition=ReplacementItem.DISP_DISPENSED, qty_prescribed=r['qty'], qty_replaced=0,
                public_unit_price=ln.list_price or ln.item.pack_price or 0, contract_unit_price=ln.unit_price)
    _set_items(case, items, Item)
    _audit('replacement_case_created', case, user, request=request,
           new={'source': source_type, 'mode': settlement_mode, 'pic': softech_pic, 'branch': case.branchcode,
                'items': [dict(i) for i in items]})
    return case


def _set_items(case, items, Item):
    """Mark items for replacement. Prescription lines become selected_for_replacement (fully or
    partially); items not on the prescription are added as replaced lines (type B / no Rx)."""
    for it in items or ():
        item = Item.objects.get(pk=it['item_id'])
        qty = Decimal(str(it['qty']))
        if qty <= 0:
            raise ValidationError('الكمية يجب أن تكون أكبر من صفر.')
        rx = case.items.filter(itemcode=item.softech_id).first()
        price = _item_price(item)
        if rx:
            if rx.qty_prescribed is not None and qty > rx.qty_prescribed:
                raise ValidationError(f'كمية الاستبدال أكبر من كمية الروشتة للصنف {item.softech_id}.')
            full = rx.qty_prescribed is None or qty == rx.qty_prescribed
            rx.qty_replaced = qty
            rx.disposition = ReplacementItem.DISP_REPLACED if full else ReplacementItem.DISP_PARTIAL
            rx.public_unit_price = price
            rx.save()
        else:
            ReplacementItem.objects.create(case=case, item=item, itemcode=item.softech_id,
                                           item_name=item.name[:255], disposition=ReplacementItem.DISP_REPLACED,
                                           qty_replaced=qty, public_unit_price=price)


@transaction.atomic
def set_items(case_id, *, user, version, items, request=None) -> RC:
    from apps.catalog.models import Item
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    _require_editable(case)
    before = list(case.items.values('itemcode', 'disposition', 'qty_replaced'))
    case.items.exclude(qty_prescribed__isnull=False).delete()          # non-Rx replaced lines
    case.items.filter(qty_prescribed__isnull=False).update(disposition=ReplacementItem.DISP_DISPENSED,
                                                           qty_replaced=0)
    _set_items(case, items, Item)
    case.status, case.current_calc = RC.STATUS_DRAFT, None             # calculation is now stale
    _bump(case, 'status', 'current_calc')
    _audit('replacement_case_updated', case, user, old={'items': before}, new={'items': [dict(i) for i in items]},
           request=request)
    return case


# ─────────────────────────────────────────────────────────────────────────────
# Calculate
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def calculate(case_id, *, user, version, override_pct=None, override_reason='', request=None) -> RC:
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    _require_editable(case)
    calc = RULES.calculate(case, user=user, override_pct=override_pct, override_reason=override_reason)
    authz.require(user, 'create', case=case, amount=calc.entitlement)
    rule = calc.rule
    case.current_calc = calc
    case.status = RC.STATUS_CALCULATED
    case.supplier_personcode = rule.supplier_personcode
    case.supplier_tier_pct = C.supplier_cfg(rule.supplier_personcode).get('tier')
    case.applied_deduction_pct = calc.applied_deduction_pct
    case.public_value = calc.public_value
    case.entitlement = calc.entitlement
    _bump(case, 'current_calc', 'status', 'supplier_personcode', 'supplier_tier_pct', 'applied_deduction_pct',
          'public_value', 'entitlement')
    _audit('replacement_case_calculated', case, user, request=request,
           new={'calc': calc.seq, 'rule': f'{rule.rule_key} v{rule.version}', 'rule_pct': str(rule.deduction_pct),
                'applied_pct': str(calc.applied_deduction_pct), 'public': str(calc.public_value),
                'entitlement': str(calc.entitlement), 'override_reason': calc.override_reason})
    return case


# ─────────────────────────────────────────────────────────────────────────────
# Submit / approve / reject
# ─────────────────────────────────────────────────────────────────────────────

def approval_route(case) -> tuple[str | None, list[str]]:
    """Which approval workflow (None = auto) and why — deterministic & explainable (§8)."""
    calc = case.current_calc
    reasons, level = [], 0
    if case.settlement_mode in ('cash', 'mixed') and C.get('APPROVAL_CASH_ALWAYS'):
        level, reasons = max(level, 1), reasons + ['صرف نقدي']
    if calc.applied_deduction_pct < calc.rule_deduction_pct and C.get('APPROVAL_OVERRIDE_ALWAYS'):
        level, reasons = max(level, 1), reasons + [f'تخفيض نسبة الخصم من {calc.rule_deduction_pct}% '
                                                   f'إلى {calc.applied_deduction_pct}%']
    since = timezone.now() - timedelta(days=C.get('APPROVAL_AGGREGATION_DAYS'))
    rolling = calc.entitlement
    if case.softech_pic:
        rolling += (RC.objects.filter(origin=RC.ORIGIN_LIVE, softech_pic=case.softech_pic, created_at__gte=since)
                    .exclude(pk=case.pk).exclude(status__in=[RC.STATUS_CANCELLED, RC.STATUS_DRAFT,
                                                              RC.STATUS_CALCULATED])
                    .aggregate(s=Sum('entitlement'))['s'] or Decimal('0'))
    if rolling > C.get('APPROVAL_AUTO_MAX'):
        level = max(level, 1)
        reasons.append(f'إجمالي أرصدة المريض خلال {C.get("APPROVAL_AGGREGATION_DAYS")} أيام = {rolling}')
    if rolling > C.get('APPROVAL_MANAGER_ABOVE'):
        level = max(level, 2)
        reasons.append(f'يتجاوز حد المدير ({C.get("APPROVAL_MANAGER_ABOVE")})')
    return ({0: None, 1: C.get('WORKFLOW_SUPERVISOR'), 2: C.get('WORKFLOW_MANAGER')}[level], reasons)


@transaction.atomic
def submit(case_id, *, user, version, request=None) -> RC:
    from apps.approvals.service import ApprovalService
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case, amount=case.entitlement)
    _require_editable(case)
    if case.status != RC.STATUS_CALCULATED or not case.current_calc_id:
        raise ValidationError('احسب الرصيد قبل الإرسال.')
    workflow, reasons = approval_route(case)
    case.locked_at = timezone.now()
    if workflow is None:
        case.status, case.approved_at, case.approved_by = RC.STATUS_APPROVED, timezone.now(), None
        _bump(case, 'locked_at', 'status', 'approved_at', 'approved_by')
        _audit('replacement_case_approved', case, user, request=request,
               new={'auto': True, 'entitlement': str(case.entitlement), 'fingerprint': case.current_calc.fingerprint},
               note='اعتماد تلقائي — ضمن الحدود')
        return case
    req = ApprovalService.submit(
        workflow_code=workflow, subject_object=case, requested_by=user,
        title=f'اعتماد بدل {case.number} — {case.entitlement} ج.م',
        body='؛ '.join(reasons),
        context_data={'case': case.number, 'fingerprint': case.current_calc.fingerprint,
                      'entitlement': str(case.entitlement), 'reasons': reasons,
                      'correlation_id': str(case.correlation_id)})
    case.approval_request, case.status = req, RC.STATUS_AWAITING_APPROVAL
    _bump(case, 'locked_at', 'approval_request', 'status')
    _audit('replacement_case_submitted', case, user, request=request,
           new={'workflow': workflow, 'reasons': reasons, 'approval_request': req.pk})
    return case


@transaction.atomic
def decide(case_id, *, user, version, approve: bool, note='', request=None) -> RC:
    """Approve / reject from the case workspace. Maker-checker + grant limits checked here;
    step eligibility (role / branch) is checked by apps.approvals."""
    from apps.approvals.models import ApprovalDecision as AD
    from apps.approvals.service import ApprovalError, ApprovalService
    case = _lock(case_id, version)
    authz.require(user, 'approve', case=case, amount=case.entitlement if approve else None)
    if case.status != RC.STATUS_AWAITING_APPROVAL or not case.approval_request_id:
        raise ValidationError('الحالة ليست بانتظار الاعتماد.')
    if case.created_by_id and case.created_by_id == user.pk:
        raise PermissionDenied('لا يمكن اعتماد حالة أنشأتها بنفسك (فصل المهام).')
    if not approve and not (note or '').strip():
        raise ValidationError('سبب الرفض مطلوب.')
    try:
        ApprovalService.decide(request=case.approval_request, decided_by=user, notes=note or '',
                               decision=AD.DECISION_APPROVED if approve else AD.DECISION_REJECTED)
    except ApprovalError as e:
        raise PermissionDenied(str(e))
    case.refresh_from_db()            # the outcome handler may have moved the case
    return case


def on_approval_outcome(approval_request, outcome: str) -> None:
    """apps.approvals outcome hook — also covers decisions made from the generic /approvals inbox."""
    from apps.approvals.models import ApprovalDecision as AD
    case = RC.objects.select_for_update().filter(approval_request=approval_request).first()
    if case is None or case.status != RC.STATUS_AWAITING_APPROVAL:
        return
    deciders = list(AD.objects.filter(request=approval_request, decision=AD.DECISION_APPROVED)
                    .values_list('decided_by_id', flat=True))
    last = AD.objects.filter(request=approval_request).order_by('-id').first()
    if outcome == 'approved':
        stale = approval_request.context_data.get('fingerprint') != (case.current_calc.fingerprint
                                                                      if case.current_calc_id else None)
        self_ok = case.created_by_id not in deciders
        if stale or not self_ok:
            X.objects.update_or_create(
                case=case, exception_type='self_approval' if not self_ok else 'stale_approval', key='',
                defaults={'severity': X.SEV_HIGH, 'status': X.STATUS_OPEN,
                          'detail': 'اعتماد من منشئ الحالة نفسه — مرفوض (فصل المهام)' if not self_ok
                          else 'تغيرت بيانات الحساب بعد الإرسال — الاعتماد غير صالح'})
            case.status, case.locked_at = RC.STATUS_CALCULATED, None
            _bump(case, 'status', 'locked_at')
            return
        case.status, case.approved_at = RC.STATUS_APPROVED, timezone.now()
        case.approved_by_id = last.decided_by_id if last else None
        _bump(case, 'status', 'approved_at', 'approved_by')
        _audit('replacement_case_approved', case, last.decided_by if last else None,
               new={'approval_request': approval_request.pk, 'fingerprint': case.current_calc.fingerprint})
    else:
        case.status, case.locked_at = RC.STATUS_CALCULATED, None        # back to the maker for changes
        _bump(case, 'status', 'locked_at')
        _audit('replacement_case_rejected', case, last.decided_by if last else None,
               note=(last.notes if last else '')[:255], new={'approval_request': approval_request.pk})


# ─────────────────────────────────────────────────────────────────────────────
# Reopen / cancel
# ─────────────────────────────────────────────────────────────────────────────

def _has_posted(case) -> bool:
    return case.operations.filter(status__in=POSTED_OPS).exists()


@transaction.atomic
def reopen(case_id, *, user, version, reason, request=None) -> RC:
    """Unlock an approved / submitted case for correction — only while NOTHING has been posted
    to SOFTECH. After a posting, corrections are compensating transactions (Phase 6)."""
    from apps.approvals.service import ApprovalService
    case = _lock(case_id, version)
    authz.require(user, 'approve', case=case)
    if not (reason or '').strip():
        raise ValidationError('سبب إعادة الفتح مطلوب.')
    if case.status not in (RC.STATUS_AWAITING_APPROVAL, RC.STATUS_APPROVED, RC.STATUS_CALCULATED):
        raise ValidationError('لا يمكن إعادة فتح الحالة في وضعها الحالي.')
    if _has_posted(case):
        raise ValidationError('تم ترحيل مستندات لهذه الحالة — التصحيح يكون بمستندات عكسية وليس بإعادة الفتح.')
    if case.approval_request_id and not case.approval_request.is_terminal:
        try:
            ApprovalService.cancel(request=case.approval_request, cancelled_by=user, reason=reason)
        except Exception:
            pass
    case.operations.exclude(status__in=POSTED_OPS).update(status=Op.ST_CANCELLED)
    old = case.status
    case.status, case.locked_at, case.approval_request = RC.STATUS_DRAFT, None, None
    case.approved_at = case.approved_by = None
    _bump(case, 'status', 'locked_at', 'approval_request', 'approved_at', 'approved_by')
    _audit('replacement_case_reopened', case, user, old={'status': old}, new={'status': case.status},
           note=reason, request=request)
    return case


@transaction.atomic
def cancel(case_id, *, user, version, reason, request=None) -> RC:
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    if not (reason or '').strip():
        raise ValidationError('سبب الإلغاء مطلوب.')
    if case.origin != RC.ORIGIN_LIVE or _has_posted(case):
        raise ValidationError('لا يمكن إلغاء حالة لها مستندات مُرحّلة — استخدم العكس.')
    if case.status in (RC.STATUS_CANCELLED, RC.STATUS_CLOSED):
        raise ValidationError('الحالة منتهية بالفعل.')
    if case.approval_request_id and not case.approval_request.is_terminal:
        from apps.approvals.service import ApprovalService     # withdraw it from approvers' inboxes
        try:
            ApprovalService.cancel(request=case.approval_request, cancelled_by=user, reason=reason)
        except Exception:
            case.approval_request.status = case.approval_request.STATUS_CANCELLED
            case.approval_request.save(update_fields=['status'])
    case.operations.exclude(status__in=POSTED_OPS).update(status=Op.ST_CANCELLED)
    old = case.status
    case.status = RC.STATUS_CANCELLED
    _bump(case, 'status')
    _audit('replacement_case_cancelled', case, user, old={'status': old}, note=reason, request=request)
    return case
