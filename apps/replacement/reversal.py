"""
apps/replacement/reversal.py — B4: returns, reversals and corrections (doc 25 §24).

Reversal, never deletion. Every SOFTECH document here is posted NATIVELY (no writer is switched on):
  • A reversal request carries the reason and the approval (band G: supervisor; manager once any of the
    balance was used) on the existing apps.approvals inbox, maker ≠ checker. Approved → the case is
    «reversing» (no new funding or cash) and the cashier gets a supplier-return instruction.
  • The daily check matches the native supplier return (doccode 120, already booked to the ledger by
    reconstruction step 5) to the approved request: amount checked, request executed, case reversed.
    A supplier return with no approved request is HIGH.
  • Live cases also watch their own sales: a full return of the contract sale is HIGH (cancelled), a
    partial one a WARNING; a contract return after the change-of-mind window (owner Q4: 7 days AND the
    same month) a WARNING; a return of a replacement-product receipt a WARNING (how the balance is
    restored natively is still an owner decision — detection only).
  • An insurer rejection is recorded on the case (owner: "what's done is done" — no reversal).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from . import authz
from . import config as C
from . import ledger as L
from .models import (CaseDocument as CD, CaseException as X, CashPayout, PostingOperation as Op,
                     ReplacementCase as RC, ReversalRequest as RR)

CENT = Decimal('0.01')
TOL = Decimal('0.05')


def change_of_mind_until(sale_day: date) -> date:
    """Owner Q4: within CHANGE_OF_MIND_DAYS of the sale AND before that month ends."""
    month_end = date(sale_day.year, sale_day.month, calendar.monthrange(sale_day.year, sale_day.month)[1])
    return min(sale_day + timedelta(days=C.get('CHANGE_OF_MIND_DAYS')), month_end)


def _open_reservations(case) -> bool:
    from .legs import ACTIVE_OPS
    return (case.operations.filter(kind=Op.KIND_PRODUCT_SALE, status__in=ACTIVE_OPS)
            .exclude(result__has_key='voucher_linked').exists()
            or case.payouts.filter(status=CashPayout.ST_INSTRUCTED).exists())


# ─────────────────────────────────────────────────────────────────────────────
# Request → approval → native supplier return
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def request_reversal(case_id, *, user, version, kind, reason, amount=None, request=None) -> RC:
    from apps.approvals.service import ApprovalService
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    if case.origin != RC.ORIGIN_LIVE:
        raise ValidationError('الحالات التاريخية للقراءة فقط.')
    if kind not in dict(RR.KIND_CHOICES):
        raise ValidationError('نوع العكس غير صالح.')
    if not (reason or '').strip():
        raise ValidationError('سبب العكس مطلوب.')
    if not case.purchase_ref_id or case.status in (RC.STATUS_CANCELLED, RC.STATUS_REVERSED):
        raise ValidationError('لا توجد فاتورة شراء قائمة لعكسها.')
    if case.reversals.filter(status__in=RR.OPEN).exists():
        raise ValidationError('يوجد طلب عكس مفتوح لهذه الحالة.')
    if _open_reservations(case):
        raise ValidationError('ألغِ تمويل الطلبات وتعليمات الصرف المفتوحة أولاً.')
    balance = L.balance(case)
    if balance <= CENT:
        raise ValidationError('الرصيد مستهلك بالكامل — أرجع فواتير المنتجات أولاً ثم اطلب العكس.')
    amount = Decimal(str(amount)).quantize(CENT) if amount not in (None, '') else balance.quantize(CENT)
    if amount <= 0 or amount > balance:
        raise ValidationError(f'قيمة المرتجع يجب أن تكون بين 0 والرصيد القائم {balance}.')
    used = balance < case.entitlement - CENT
    rr = RR.objects.create(case=case, kind=kind, reason=reason.strip(), amount=amount, balance_used=used,
                           requested_by=user)
    workflow = C.get('WORKFLOW_MANAGER') if used else C.get('WORKFLOW_SUPERVISOR')
    req = ApprovalService.submit(
        workflow_code=workflow, subject_object=rr, requested_by=user,
        title=f'عكس حالة بدل {case.number} — {amount} ج.م',
        body=f'{rr.get_kind_display()}: {rr.reason}',
        context_data={'case': case.number, 'kind': kind, 'amount': str(amount), 'balance_used': used,
                      'correlation_id': str(case.correlation_id)})
    rr.approval_request = req
    rr.save(update_fields=['approval_request', 'updated_at'])
    _bump(case, 'status')
    _audit('replacement_case_updated', case, user, request=request, note=reason[:255],
           new={'reversal_requested': rr.pk, 'kind': kind, 'amount': str(amount), 'workflow': workflow})
    return case


def _reversal(case, rr_id):
    try:
        return case.reversals.select_for_update().get(pk=rr_id)
    except RR.DoesNotExist:
        raise ValidationError('طلب العكس غير موجود.')


@transaction.atomic
def decide_reversal(case_id, rr_id, *, user, version, approve: bool, note='', request=None) -> RC:
    from apps.approvals.models import ApprovalDecision as AD
    from apps.approvals.service import ApprovalError, ApprovalService
    from .workflow import _lock
    case = _lock(case_id, version)
    authz.require(user, 'approve', case=case)
    rr = _reversal(case, rr_id)
    if rr.status != RR.ST_AWAITING or not rr.approval_request_id:
        raise ValidationError('الطلب ليس بانتظار الموافقة.')
    if rr.requested_by_id == user.pk:
        raise PermissionDenied('لا يمكن اعتماد طلب عكس قدمته بنفسك (فصل المهام).')
    if not approve and not (note or '').strip():
        raise ValidationError('سبب الرفض مطلوب.')
    try:
        ApprovalService.decide(request=rr.approval_request, decided_by=user, notes=note or '',
                               decision=AD.DECISION_APPROVED if approve else AD.DECISION_REJECTED)
    except ApprovalError as e:
        raise PermissionDenied(str(e))
    return RC.objects.get(pk=case.pk)


def on_reversal_outcome(approval_request, outcome: str) -> None:
    """apps.approvals hook — decisions from the workspace or the generic /approvals inbox."""
    from apps.approvals.models import ApprovalDecision as AD
    from .workflow import _audit, _bump
    rr = RR.objects.select_for_update().filter(approval_request=approval_request).select_related('case').first()
    if rr is None or rr.status != RR.ST_AWAITING:
        return
    case = RC.objects.select_for_update().get(pk=rr.case_id)
    last = AD.objects.filter(request=approval_request).order_by('-id').first()
    deciders = set(AD.objects.filter(request=approval_request, decision=AD.DECISION_APPROVED)
                   .values_list('decided_by_id', flat=True))
    if outcome == 'approved' and rr.requested_by_id in deciders:
        X.objects.update_or_create(case=case, exception_type='self_approval', key=f'rr{rr.pk}', defaults={
            'severity': X.SEV_HIGH, 'status': X.STATUS_OPEN,
            'detail': 'اعتماد طلب عكس من مقدّمه نفسه — مرفوض (فصل المهام)'})
        outcome = 'rejected'
    rr.decided_by = last.decided_by if last else None
    rr.decided_at = timezone.now()
    rr.note = (last.notes if last else '')[:300]
    if outcome == 'approved':
        rr.status = RR.ST_APPROVED
        case.status = RC.STATUS_REVERSING
        _bump(case, 'status')
    else:
        rr.status = RR.ST_REJECTED
        _bump(case, 'status')
    rr.save(update_fields=['status', 'decided_by', 'decided_at', 'note', 'updated_at'])
    _audit('replacement_case_updated', case, rr.decided_by,
           new={'reversal': rr.pk, 'outcome': rr.status, 'approval_request': approval_request.pk})


def _restore_status(case):
    case.status = RC.STATUS_ENTITLEMENT_ACTIVE if L.balance(case) > CENT else RC.STATUS_SETTLED


@transaction.atomic
def cancel_reversal(case_id, rr_id, *, user, version, reason, request=None) -> RC:
    from apps.approvals.service import ApprovalService
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    if not (reason or '').strip():
        raise ValidationError('سبب الإلغاء مطلوب.')
    rr = _reversal(case, rr_id)
    if rr.status not in RR.OPEN or rr.supplier_return_id:
        raise ValidationError('لا يمكن إلغاء الطلب في وضعه الحالي.')
    if rr.approval_request_id and not rr.approval_request.is_terminal:
        try:
            ApprovalService.cancel(request=rr.approval_request, cancelled_by=user, reason=reason)
        except Exception:
            rr.approval_request.status = rr.approval_request.STATUS_CANCELLED
            rr.approval_request.save(update_fields=['status'])
    rr.status, rr.note = RR.ST_CANCELLED, reason[:300]
    rr.save(update_fields=['status', 'note', 'updated_at'])
    if case.status == RC.STATUS_REVERSING:
        _restore_status(case)
    _bump(case, 'status')
    _audit('replacement_case_updated', case, user, request=request, note=reason[:255],
           new={'reversal_cancelled': rr.pk})
    return case


def instruction(case, rr) -> dict:
    """What staff post natively: a supplier return (مرتجع للمورد, doccode 120) on the case purchase."""
    p = case.purchase_ref
    return {'reversal': rr.pk, 'amount': str(rr.amount), 'supplier': case.supplier_personcode,
            'supplier_name': p.party_name if p else '', 'branch': p.branchcode if p else case.branchcode,
            'purchase': p.docnumber if p else '',
            'note': f'مرتجع للمورد من فاتورة الشراء رقم {p.docnumber} (الرقم المرجعي)' if p else ''}


@transaction.atomic
def record_insurer_rejection(case_id, *, user, version, note, request=None) -> RC:
    """Owner: the insurer's later rejection changes nothing already done — it is recorded for reports."""
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    authz.require(user, 'edit', case=case)
    if not (note or '').strip():
        raise ValidationError('اكتب تفاصيل الرفض.')
    X.objects.update_or_create(case=case, exception_type='insurer_rejected', key='', defaults={
        'severity': X.SEV_INFO, 'status': X.STATUS_ACK, 'detail': note.strip()[:2000], 'owner': user})
    from .reconstruct import recount_exceptions
    recount_exceptions(case)
    _bump(case, 'status')
    _audit('replacement_case_updated', case, user, request=request, note=note[:255], new={'insurer_rejected': True})
    return case


# ─────────────────────────────────────────────────────────────────────────────
# Daily check (live cases) — called from reconstruct.reconstruct_invoice
# ─────────────────────────────────────────────────────────────────────────────

def match_supplier_return(case, r_ref, amt, issue) -> None:
    rr = case.reversals.filter(supplier_return=r_ref).first()
    if rr is not None:
        if abs(rr.amount - amt) > TOL:
            issue('reversal_amount_mismatch', X.SEV_HIGH, key=r_ref.pk, amount=amt - rr.amount,
                  detail=f'مرتجع المورد {r_ref.docnumber} = {amt} وطلب العكس {rr.amount}')
        return
    rr = case.reversals.filter(status=RR.ST_APPROVED, supplier_return__isnull=True).first()
    if rr is None:
        issue('return_without_approval', X.SEV_HIGH, key=r_ref.pk, amount=amt,
              detail=f'مرتجع للمورد {r_ref.docnumber} بقيمة {amt} بدون طلب عكس معتمد')
        return
    if abs(rr.amount - amt) > TOL:
        issue('reversal_amount_mismatch', X.SEV_HIGH, key=r_ref.pk, amount=amt - rr.amount,
              detail=f'مرتجع المورد {r_ref.docnumber} = {amt} وطلب العكس المعتمد {rr.amount}')
        return
    rr.supplier_return, rr.status, rr.executed_at = r_ref, RR.ST_EXECUTED, timezone.now()
    rr.save(update_fields=['supplier_return', 'status', 'executed_at', 'updated_at'])


def ageing_issues(case, issue) -> None:
    cutoff = timezone.now() - timedelta(days=C.get('REVERSAL_EXECUTE_DAYS'))
    for rr in case.reversals.filter(status=RR.ST_APPROVED, decided_at__lt=cutoff):
        issue('reversal_not_executed', X.SEV_WARNING, key=f'rr{rr.pk}', amount=rr.amount,
              detail=f'طلب عكس معتمد ({rr.get_kind_display()}) منذ {(timezone.now() - rr.decided_at).days} يوم '
                     f'ولم يظهر مرتجع المورد')


def apply_status(case) -> None:
    """After the ledger is rebuilt: an executed reversal that left no balance closes the case as
    reversed; an approved one keeps it reversing."""
    if case.reversals.filter(status=RR.ST_APPROVED).exists():
        case.status = RC.STATUS_REVERSING
    elif case.reversals.filter(status=RR.ST_EXECUTED).exists() and abs(case.outstanding) <= CENT:
        case.status = RC.STATUS_REVERSED


def _ph(ref):
    from apps.customers.models import PurchaseHistory
    if ref.source_model != 'customers.purchasehistory' or not ref.source_pk:
        return None
    return PurchaseHistory.objects.filter(pk=ref.source_pk).select_related('branch').prefetch_related('lines__item').first()


def _returns_of(sale, *, contract: bool):
    """Same-patient returns (doc 30) on the sale's branch, inside the watch window, whose items are all
    on the sale — the same pairing rule reconstruction uses, with a longer window for live cases."""
    from apps.customers.models import PurchaseHistory
    from .reconstruct import _local_date
    pic = (sale.softech_phcode or '').strip()
    if not pic or not sale.invoice_date:
        return []
    day = _local_date(sale.invoice_date)
    qs = (PurchaseHistory.objects.filter(branch=sale.branch, doc_code='30', softech_phcode=pic,
                                         invoice_date__date__gte=day,
                                         invoice_date__date__lte=day + timedelta(days=C.get('LIVE_RETURN_WATCH_DAYS')))
          .prefetch_related('lines__item').select_related('branch'))
    qs = qs.filter(sales_channel__in=C.CONTRACT_CHANNELS) if contract else qs.exclude(sales_channel__in=C.CONTRACT_CHANNELS)
    items = {l.item.softech_id for l in sale.lines.all() if l.item_id}
    return [r for r in qs if {l.item.softech_id for l in r.lines.all() if l.item_id} <= items]


def detect_returns(case, issue) -> None:
    from .reconstruct import _casedoc, _local_date, _q2, _own_receipts, ref_for_sale
    for cd in case.documents.filter(role=CD.ROLE_CONTRACT_SALE, status=CD.STATUS_CONFIRMED).select_related('document'):
        sale = _ph(cd.document)
        if sale is None:
            continue
        until = change_of_mind_until(_local_date(sale.invoice_date))
        for r in _returns_of(sale, contract=True):
            r_ref = ref_for_sale(r)
            full = abs(_q2(r.total_amount) - _q2(sale.total_amount)) <= CENT
            _casedoc(case, r_ref, CD.ROLE_CONTRACT_VOID if full else CD.ROLE_CONTRACT_RETURN,
                     status=CD.STATUS_CONFIRMED, confidence=90, amount=_q2(r.total_amount))
            if full:
                issue('contract_cancelled', X.SEV_HIGH, key=r_ref.pk, amount=_q2(r.total_amount),
                      detail=f'فاتورة التعاقد {sale.docnumber} أُلغيت بالمرتجع {r.docnumber} — راجع الرصيد وطلب العكس')
            else:
                issue('contract_partially_returned', X.SEV_WARNING, key=r_ref.pk, amount=_q2(r.total_amount),
                      detail=f'مرتجع جزئي {r.docnumber} من فاتورة التعاقد {sale.docnumber}')
            if _local_date(r.invoice_date) > until:
                issue('late_contract_return', X.SEV_WARNING, key=r_ref.pk, amount=_q2(r.total_amount),
                      detail=f'مرتجع التعاقد {r.docnumber} بتاريخ {_local_date(r.invoice_date)} بعد مهلة التراجع ({until})')
    from apps.customers.models import PurchaseHistory
    for ph in PurchaseHistory.objects.filter(pk__in=list(_own_receipts(case))).select_related('branch') \
            .prefetch_related('lines__item'):
        for r in _returns_of(ph, contract=False):
            r_ref = ref_for_sale(r)
            issue('product_sale_returned', X.SEV_WARNING, key=r_ref.pk, amount=_q2(r.total_amount),
                  detail=f'مرتجع {r.docnumber} من فاتورة منتجات البدل {ph.docnumber} — استعادة الرصيد تتم في SOFTECH')
