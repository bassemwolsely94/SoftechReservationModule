"""
apps/replacement/cash.py — B3: cash handed to the patient (doc 25 §23).

Owner Q2: the CASHIER makes the سداد voucher natively in SOFTECH — there is no voucher writer. The module
  1. records the instruction (amount within what is available, covered by the case approval — the cash
     band ran on the whole balance at submit), which reserves that amount;
  2. links the native voucher in the daily check and verifies it: amount = instruction, made by someone
     other than the case creator above the cash threshold, executed in time;
  3. takes the handing employee's confirmation (optional reference).
A voucher on a live cash / mixed case with no declared product receipts and no matching instruction is
cash that left the drawer without one → HIGH. Products-only cases never pay cash: the owner's rule is a
supplier return and a new purchase at the cash rate (B4).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import authz
from . import config as C
from .models import CaseException as X, CashPayout as P, ReplacementCase as RC

CENT = Decimal('0.01')
PAYABLE_STATUSES = (RC.STATUS_EXECUTING, RC.STATUS_ENTITLEMENT_ACTIVE, RC.STATUS_SETTLED, RC.STATUS_RECONCILED)


def reserved(case) -> Decimal:
    return sum((p.amount for p in case.payouts.filter(status=P.ST_INSTRUCTED)), Decimal('0'))


@transaction.atomic
def request_payout(case_id, *, user, version, amount, note='', request=None) -> RC:
    from .legs import available
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    amount = Decimal(str(amount or 0)).quantize(CENT)
    authz.require(user, 'create', case=case)
    if case.origin != RC.ORIGIN_LIVE:
        raise ValidationError('الحالات التاريخية للقراءة فقط.')
    if case.settlement_mode not in (RC.MODE_CASH, RC.MODE_MIXED):
        raise ValidationError('حالة منتجات — الصرف النقدي يكون بمرتجع للمورد وشراء جديد بنسبة النقدي.')
    if case.status not in PAYABLE_STATUSES or not case.purchase_ref_id:
        raise ValidationError('اربط فاتورة الشراء أولاً — السند يُسدَّد عليها.')
    if amount <= 0:
        raise ValidationError('أدخل مبلغ الصرف.')
    av = available(case)['available']
    if amount > av:
        raise ValidationError(f'المبلغ {amount} أكبر من المتاح {av}.')
    p = P.objects.create(case=case, amount=amount, requested_by=user, note=(note or '')[:300])
    _bump(case, 'status')
    _audit('replacement_leg_prepared', case, user, request=request,
           new={'kind': 'cash_payout', 'payout': p.pk, 'amount': str(amount), 'available_before': str(av)})
    return case


def _payout(case, payout_id):
    try:
        return case.payouts.select_for_update().get(pk=payout_id)
    except P.DoesNotExist:
        raise ValidationError('تعليمات الصرف غير موجودة.')


@transaction.atomic
def cancel_payout(case_id, payout_id, *, user, version, reason, request=None) -> RC:
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    if not (reason or '').strip():
        raise ValidationError('سبب الإلغاء مطلوب.')
    p = _payout(case, payout_id)
    if p.status != P.ST_INSTRUCTED:
        raise ValidationError('صُرف بالفعل — التصحيح يكون بسند عكسي في SOFTECH.')
    p.status, p.cancel_reason = P.ST_CANCELLED, reason[:300]
    p.save(update_fields=['status', 'cancel_reason', 'updated_at'])
    _bump(case, 'status')
    _audit('replacement_case_updated', case, user, request=request, note=reason,
           new={'cancelled_payout': p.pk, 'amount': str(p.amount)})
    return case


@transaction.atomic
def confirm_payout(case_id, payout_id, *, user, version, reference='', request=None) -> RC:
    """The employee who handed the cash to the patient confirms it (after the voucher is linked)."""
    from .workflow import _audit, _bump, _lock
    case = _lock(case_id, version)
    authz.require(user, 'create', case=case)
    p = _payout(case, payout_id)
    if p.status != P.ST_PAID:
        raise ValidationError('التأكيد بعد ربط سند الصرف من الكاشير.')
    p.status, p.confirmed_by, p.confirmed_at = P.ST_CONFIRMED, user, timezone.now()
    p.reference = (reference or '')[:120]
    p.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'reference', 'updated_at'])
    _bump(case, 'status')
    _audit('replacement_case_updated', case, user, request=request,
           new={'confirmed_payout': p.pk, 'amount': str(p.amount), 'reference': p.reference})
    return case


def instruction(case, p) -> dict:
    """What the cashier types in SOFTECH for this payout (D14: an internal note only)."""
    ref = case.purchase_ref
    return {'payout': p.pk, 'amount': str(p.amount), 'supplier': case.supplier_personcode,
            'supplier_name': ref.party_name if ref else '', 'invoice': ref.docnumber if ref else '',
            'branch': ref.branchcode if ref else case.branchcode,
            'note': f'صرف نقدي من فاتورة رقم {ref.docnumber}' if ref else ''}


def match_voucher(case, v_ref, pay, amt, issue) -> None:
    """Daily check, live cash / mixed case, a voucher with no declared product receipt: link it to its
    instruction and verify it. Never re-decides an existing link."""
    key = v_ref.pk
    p = case.payouts.filter(voucher=v_ref).first()
    if p is None:
        open_ = list(case.payouts.filter(status=P.ST_INSTRUCTED, voucher__isnull=True,
                                         created_at__date__lte=pay.voucher_date).order_by('created_at'))
        p = next((o for o in open_ if abs(o.amount - amt) <= CENT), None)
        if p is None:
            if len(open_) == 1:
                issue('payout_amount_mismatch', X.SEV_HIGH, key=key, amount=amt - open_[0].amount,
                      detail=f'سند {pay.branchcode}/{pay.cheqsno} بمبلغ {amt} وتعليمات الصرف {open_[0].amount}')
            else:
                issue('cash_without_instruction', X.SEV_HIGH, key=key, amount=amt,
                      detail=f'سند صرف {pay.branchcode}/{pay.cheqsno} بمبلغ {amt} بدون فواتير منتجات '
                             f'ولا تعليمات صرف نقدي من الحالة')
            return
        p.voucher, p.status = v_ref, P.ST_PAID
        p.voucher_usercode, p.voucher_box = (pay.usercode or '').strip()[:8], (pay.bankcode or '').strip()[:3]
        p.paid_at = pay.trans_time or timezone.now()
        p.save(update_fields=['voucher', 'status', 'voucher_usercode', 'voucher_box', 'paid_at', 'updated_at'])
    elif abs(p.amount - amt) > CENT:
        issue('payout_amount_mismatch', X.SEV_HIGH, key=key, amount=amt - p.amount,
              detail=f'سند {pay.branchcode}/{pay.cheqsno} بمبلغ {amt} وتعليمات الصرف {p.amount}')
    creator = (getattr(case.created_by, 'softech_user_id', '') or '').strip() if case.created_by_id else ''
    if creator and creator == p.voucher_usercode and amt > C.get('APPROVAL_CASH_MANAGER_ABOVE'):
        issue('voucher_by_creator', X.SEV_HIGH, key=key, amount=amt,
              detail=f'سند الصرف النقدي {amt} من مستخدم SOFTECH {creator} وهو منشئ الحالة (فصل المهام)')


def ageing_issues(case, issue) -> None:
    now = timezone.now()
    for p in case.payouts.filter(status=P.ST_INSTRUCTED,
                                 created_at__lt=now - timedelta(days=C.get('PAYOUT_EXECUTE_DAYS'))):
        issue('payout_not_executed', X.SEV_WARNING, key=f'p{p.pk}', amount=p.amount,
              detail=f'تعليمات صرف {p.amount} منذ {(now - p.created_at).days} يوم ولم يظهر سند الكاشير')
    for p in case.payouts.filter(status=P.ST_PAID,
                                 paid_at__lt=now - timedelta(days=C.get('PAYOUT_CONFIRM_DAYS'))):
        issue('payout_not_confirmed', X.SEV_INFO, key=f'p{p.pk}', amount=p.amount,
              detail=f'صُرف {p.amount} ولم يؤكد الموظف التسليم')
