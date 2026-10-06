"""
apps/finance/recon_actions.py

Phase-C batch E — human reconciliation ACTIONS. These mutate ONLY the PostgreSQL
mirror (create/undo Allocation rows, advance candidate status) and write an
immutable ReconAuditEvent for every decision. They do NOT write to SOFTECH — that
is the gated Phase-G write adapter, which consumes origin='approved' allocations.

Guards (capacity + integrity) are enforced here, raising ReconActionError so the
API maps them to 4xx. Every allocation respects:
  • amount > 0
  • amount ≤ invoice UNLINKED (doc_value − Σ allocations)
  • amount ≤ payment UNALLOCATED (amount − Σ allocations)
  • party of payment == party of invoice
  • one Allocation per (payment, invoice)  [DB-enforced too]

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import (
    APInvoice, Payment, Allocation, MatchCandidate, ReconAuditEvent, ReconParty,
)
from .recon_engine import MANUAL_HOLD_PREFIX


class ReconActionError(Exception):
    """A guard/integrity violation — the API turns this into a 400/409."""


def _dec(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise ReconActionError('مبلغ غير صالح')


def _snapshot(invoice: APInvoice, payment: Payment) -> dict:
    return {
        'invoice': {'id': invoice.id, 'docnumber': invoice.docnumber,
                    'doc_value': str(invoice.doc_value),
                    'linked': str(invoice.linked_amount),
                    'unlinked': str(invoice.unlinked_amount)},
        'payment': {'id': payment.id, 'cheqsno': payment.cheqsno,
                    'amount': str(payment.amount),
                    'allocated': str(payment.allocated_amount),
                    'unallocated': str(payment.unallocated_amount)},
    }


def _validate_capacity(invoice: APInvoice, payment: Payment, amount: Decimal):
    if amount <= 0:
        raise ReconActionError('المبلغ يجب أن يكون أكبر من صفر')
    if payment.party_id != invoice.party_id:
        raise ReconActionError('الطرف مختلف بين السند والفاتورة')
    inv_room = invoice.unlinked_amount
    pay_room = payment.unallocated_amount
    if amount > inv_room:
        raise ReconActionError(f'المبلغ {amount} يتجاوز المتبقي على الفاتورة ({inv_room})')
    # a return netted into a payment voucher GIVES room back (signed effect)
    if payment.allocation_effect(amount, invoice.is_return) > pay_room:
        raise ReconActionError(f'المبلغ {amount} يتجاوز المتاح من السند ({pay_room})')


def _audit(action, *, candidate=None, allocation=None, party=None,
           before=None, after=None, user=None, detail=''):
    ReconAuditEvent.objects.create(
        action=action, candidate=candidate, allocation=allocation, party=party,
        before_state=before or {}, after_state=after or {},
        performed_by=user, detail=detail[:1000],
    )


def _refresh_payment_flag(payment: Payment):
    unalloc = not payment.allocations.exists()
    if payment.is_unallocated != unalloc:
        payment.is_unallocated = unalloc
        payment.save(update_fields=['is_unallocated'])


def _supersede_dependents(invoice: APInvoice, payment: Payment, keep_pk: int | None):
    """After capacity is consumed, mark now-impossible PROPOSED candidates."""
    if invoice.unlinked_amount <= 0:
        MatchCandidate.objects.filter(
            invoice=invoice, status=MatchCandidate.STATUS_PROPOSED,
        ).exclude(pk=keep_pk).update(status=MatchCandidate.STATUS_SUPERSEDED)
    if payment.unallocated_amount <= 0:
        MatchCandidate.objects.filter(
            payment=payment, status=MatchCandidate.STATUS_PROPOSED,
        ).exclude(pk=keep_pk).update(status=MatchCandidate.STATUS_SUPERSEDED)


# ── actions ───────────────────────────────────────────────────────────────────

@transaction.atomic
def approve_candidate(candidate: MatchCandidate, amount=None, user=None) -> Allocation:
    """Approve a proposed candidate → create an origin='approved' Allocation."""
    candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
    if candidate.status not in (MatchCandidate.STATUS_PROPOSED,):
        raise ReconActionError(f'لا يمكن اعتماد مرشح في حالة {candidate.get_status_display()}')
    invoice = APInvoice.objects.select_for_update().get(pk=candidate.invoice_id)
    payment = Payment.objects.select_for_update().get(pk=candidate.payment_id)

    amt = _dec(amount) if amount is not None else (candidate.proposed_amount or Decimal('0'))
    if amt <= 0:
        amt = min(invoice.unlinked_amount, payment.unallocated_amount)
    _validate_capacity(invoice, payment, amt)

    before = _snapshot(invoice, payment)
    existing = Allocation.objects.select_for_update().filter(payment=payment, invoice=invoice).first()
    if existing is not None:
        # one voucher holds ONE link per invoice: a further amount for the same pair TOPS UP
        # the link (2026-09-29: partial links written while fifo links held part of the
        # invoice) — never a second row, and never a change to a link entered in SOFTECH
        ours = ReconAuditEvent.objects.filter(action='allocation_written', allocation=existing).exists()
        if existing.origin == Allocation.ORIGIN_APPROVED or (existing.origin == Allocation.ORIGIN_WRITTEN and ours):
            existing.amount += amt
            existing.origin = Allocation.ORIGIN_APPROVED     # the writer raises the SOFTECH row
            existing.candidate = candidate
            existing.cumulative_paid = invoice.linked_amount + amt
            existing.save(update_fields=['amount', 'origin', 'candidate', 'cumulative_paid'])
            alloc = existing
        else:
            raise ReconActionError('هذا السند مربوط بهذه الفاتورة في SOFTECH مباشرة بمبلغ أقل — '
                                   'لا نعدّل الربط الأصلي؛ راجعه يدويًا')
    else:
        alloc = Allocation.objects.create(
            payment=payment, invoice=invoice, amount=amt,
            cumulative_paid=invoice.linked_amount + amt,
            origin=Allocation.ORIGIN_APPROVED, candidate=candidate,
            synced_at=timezone.now(),
        )
    candidate.status = MatchCandidate.STATUS_APPROVED
    candidate.decided_by = user
    candidate.decided_at = timezone.now()
    candidate.save(update_fields=['status', 'decided_by', 'decided_at'])

    _refresh_payment_flag(payment)
    _supersede_dependents(invoice, payment, keep_pk=candidate.pk)
    _audit('candidate_approved', candidate=candidate, allocation=alloc,
           party=invoice.party, before=before,
           after=_snapshot(invoice, payment), user=user,
           detail=f'اعتماد {amt} للفاتورة {invoice.docnumber} من سند {payment.cheqsno}')
    return alloc


def _bulk_scope(party_type=None, personcode=None, confidence_class=None,
                strategy=None, group_key=None, f=None):
    qs = MatchCandidate.objects.filter(status=MatchCandidate.STATUS_PROPOSED)
    if confidence_class:
        qs = qs.filter(confidence_class=confidence_class)
    if strategy:
        qs = qs.filter(strategy=strategy)
    if group_key:
        qs = qs.filter(group_key=group_key)
    if party_type:
        qs = qs.filter(party__party_type=party_type)
    if personcode:
        qs = qs.filter(party__softech_personcode=personcode)
    if f is not None:
        from . import recon_filters as RF
        qs = RF.apply(qs, f, 'candidate')
    return qs


def bulk_reject(user=None, note='', **scope) -> dict:
    """Reject every PROPOSED candidate in scope (typically one review group)."""
    if not any(scope.values()):
        raise ReconActionError('حدد نطاق الرفض (مجموعة أو استراتيجية أو ثقة)')
    n = 0
    for cand in list(_bulk_scope(**scope)):
        try:
            reject_candidate(cand, note=note, user=user)
            n += 1
        except ReconActionError:
            pass
    return {'rejected': n}


def bulk_approve(party_type=None, personcode=None, confidence_class='high',
                 user=None, limit=2000, strategy=None, group_key=None, f=None,
                 include_held=None) -> dict:
    """
    Approve every PROPOSED candidate in a scope (default: all HIGH-confidence),
    creating an approved Allocation for each. Idempotent + capacity-guarded per
    candidate (a candidate that can't be approved is skipped, not fatal). Processes
    at most `limit` per call (highest-confidence first) so the request stays bounded;
    the caller re-invokes to drain the rest. NO SOFTECH write — mirror only.

    A MASS approve never touches matches the auto-write policy HELD for review
    (decision_note «يحتاج مراجعة: …» — voucher>invoice, flagged voucher, date gap…):
    those are approved one by one or as a reviewed group (group_key), never by the
    «approve all high» button (2026-09-28: that button bypassed the holds).
    """
    if include_held is None:
        include_held = bool(group_key)
    qs = _bulk_scope(party_type, personcode, confidence_class or None, strategy,
                     group_key, f).select_related('invoice', 'payment')
    held = 0
    if not include_held:
        held = qs.filter(decision_note__startswith=HOLD_PREFIX).count()
        qs = qs.exclude(decision_note__startswith=HOLD_PREFIX)
    total = qs.count()
    approved = skipped = 0
    for cand in list(qs.order_by('-confidence_score', 'id')[:limit]):
        try:
            approve_candidate(cand, user=user)
            approved += 1
        except ReconActionError:
            skipped += 1
    return {'approved': approved, 'skipped': skipped, 'held_for_review': held,
            'matched_before': total, 'remaining': max(0, total - approved - skipped)}


HOLD_PREFIX = 'يحتاج مراجعة: '


def _slight_overage_named(inv, pay, net) -> bool:
    """A voucher that NAMES this invoice (inner serial / note), from the same branch, and
    exceeds it by ≤ 1% (or ≤ 1 EGP) is the invoice's payment with a rounding/fee excess —
    SOFTECH linked such vouchers to the named invoice 97.8% (≤1 EGP, n=45) / 100% (≤1%,
    n=4) vs 31.8% above 5% (backtest 2026-09-29). The excess stays on the voucher."""
    from .recon_engine import payment_ref_tokens
    value = inv.doc_value or Decimal('0')
    over = net - value
    if value <= 0 or pay.branchcode != inv.branchcode:
        return False
    if over > max(Decimal('1'), value / 100):
        return False
    return str(inv.docnumber).split('.')[0].lstrip('0') in payment_ref_tokens(pay)


def hold_reason(c: MatchCandidate, flagged_payments: set, returned_open: dict | None = None) -> str:
    """
    Deterministic 'needs deep revision' rules for the auto-write policy (doc 23 §15).
    Returns '' when the candidate may be approved + written automatically.
    """
    inv, pay = c.invoice, c.payment
    if c.confidence_class == MatchCandidate.CONF_CONFLICT:
        return 'تعارض: أكثر من فاتورة محتملة بنفس الدرجة'
    if (pay.cheqtype or '').strip() == '10' and not inv.is_return:
        return 'سند مقبوضات (استلام من المورد) لا يسدد فاتورة شراء'
    if pay.chain_role in ('reversed', 'reversal'):
        return f'سند ضمن سلسلة إلغاء: {pay.chain_note}'
    if c.strategy == 'net_returns':
        return 'مقاصة مرتجعات مع فواتير شراء — دقة تاريخية 79%، تُراجع دائمًا'
    if c.strategy == 'fifo_residual':
        # leftover money spread oldest-first: 5.6% exact in the backtest (doc 23 §14) —
        # it wrote 10,337 links before this rule (2026-09-29, e.g. a 397,080 voucher of a
        # supplier averaging 877 spread over 442 invoices) → never auto-approved
        return 'توزيع المتبقي بالأقدم — دقة تاريخية 5.6%، يُراجع دائمًا'
    if inv.is_return and not pay.is_receipt:
        return 'سند صرف مقابل مرتجع (لا يحدث إلا ضمن مقاصة) — راجع'
    if returned_open and returned_open.get(inv.id, 0) > 0:
        return f'الفاتورة عليها مرتجع لم يُخصم ({returned_open[inv.id]}) — راجع قبل السداد'
    if pay.id in flagged_payments:
        return 'السند عليه تنبيه (سند مكرر محتمل أو ربط متبادل)'
    if inv.docdate and pay.voucher_date:
        lag = (pay.voucher_date - inv.docdate).days
        if lag < -7:
            return f'السند قبل الفاتورة بـ {-lag} يوم'
        if lag > 365:
            return f'فارق زمني كبير ({lag} يوم)'
    amt = c.proposed_amount or Decimal('0')
    if amt > 0 and c.strategy != 'fifo_residual' and (inv.doc_value or 0) / amt >= 50:
        return f'مبلغ ضئيل جداً ({amt}) مقارنة بالفاتورة ({inv.doc_value})'
    if c.strategy == 'pairwise':
        # partial payment matched by reference is 92–93% same-branch, but only
        # 37–80% when the voucher is from ANOTHER branch or HQ (shadow, 2026-09-26)
        net = pay.net_amount or 0          # a payment is judged by what it NET paid (refunds bound)
        if (net + Decimal('0.01') < (inv.doc_value or 0)
                and pay.branchcode != inv.branchcode):
            return 'دفع جزئي من فرع مختلف (دقة تاريخية 37–80%)'
        if c.confidence_class == MatchCandidate.CONF_LOW:
            return 'إشارة ضعيفة: لا رقم فاتورة ولا مبلغ مطابق'
        if net > (inv.doc_value or 0) + Decimal('0.01') and not _slight_overage_named(inv, pay, net):
            return 'السند أكبر من الفاتورة (مرجع فقط — دقة تاريخية 23–34%)'
    return ''


def auto_approve(party_type='supplier', user=None, classes=('high', 'medium', 'low')) -> dict:
    """
    Auto-write policy (owner decision 2026-09-26): approve EVERY proposed match in
    `classes` unless hold_reason() finds a real discrepancy; held ones stay proposed
    with the reason in decision_note for the revision queue. Order: high → medium →
    low, specific strategies before fifo_residual, so capacity goes to the strongest
    evidence first. Mirror only — the gated writer records them in SOFTECH.
    """
    from django.conf import settings
    from .models import ReconException
    if not getattr(settings, 'AP_RECONCILE_AUTO_APPROVE', True):
        return {'approved': 0, 'held': 0, 'skipped_capacity': 0, 'not_in_policy': 0,
                'paused': True}
    flagged = set(ReconException.objects.filter(
        status='open', payment__isnull=False, party__party_type=party_type,
        exception_type__in=[ReconException.TYPE_DUPLICATE_PAYMENT,
                            ReconException.TYPE_MISALLOCATION,
                            ReconException.TYPE_SUSPECT_AMOUNT],
    ).values_list('payment_id', flat=True))
    from .recon_returns import open_returned_by_purchase
    returned_open = open_returned_by_purchase(party_type=party_type)
    # pairs linked by SOFTECH itself (not by our writer) — a further amount is a review item
    ours = set(ReconAuditEvent.objects.filter(action='allocation_written').values_list('allocation_id', flat=True))
    native_pairs = {(p, i) for aid, p, i in Allocation.objects.filter(
        origin=Allocation.ORIGIN_SOFTECH, invoice__party__party_type=party_type)
        .values_list('id', 'payment_id', 'invoice_id') if aid not in ours}
    rank = {'high': 0, 'medium': 1, 'low': 2, 'conflict': 3}
    qs = (MatchCandidate.objects.filter(status=MatchCandidate.STATUS_PROPOSED,
                                        party__party_type=party_type)
          .select_related('invoice', 'payment'))
    cands = sorted(qs, key=lambda c: (rank.get(c.confidence_class, 9),
                                      c.strategy == 'fifo_residual', -c.confidence_score,
                                      c.payment.voucher_date or datetime.date.min))
    stats = {'approved': 0, 'held': 0, 'skipped_capacity': 0, 'not_in_policy': 0}
    held_notes = []
    for c in cands:
        if c.confidence_class not in classes and c.confidence_class != 'conflict':
            stats['not_in_policy'] += 1
            continue
        if (c.proposed_amount or Decimal('0')) < Decimal('1'):
            # SOFTECH piaster rounding, not a payment decision — never queue it
            c.status = MatchCandidate.STATUS_SUPERSEDED
            c.decision_note = 'فرق كسور أقل من 1 ج.م — لا يحتاج مراجعة'
            held_notes.append(c)
            stats['dropped_rounding'] = stats.get('dropped_rounding', 0) + 1
            continue
        if (c.decision_note or '').startswith(MANUAL_HOLD_PREFIX):
            stats['held'] += 1             # a person sent it to review — never auto-approve
            continue
        reason = hold_reason(c, flagged, returned_open)
        if not reason and (c.payment_id, c.invoice_id) in native_pairs:
            reason = 'السند مربوط بهذه الفاتورة في SOFTECH مباشرة بمبلغ أقل — لا نعدّل الربط الأصلي'
        if reason:
            stats['held'] += 1
            c.decision_note = (HOLD_PREFIX + reason)[:1000]
            held_notes.append(c)
            continue
        try:
            approve_candidate(c, user=user)
            stats['approved'] += 1
        except ReconActionError:
            stats['skipped_capacity'] += 1
    MatchCandidate.objects.bulk_update(held_notes, ['decision_note', 'status'], batch_size=1000)

    # a held match is moot once its invoice or voucher is fully settled by other
    # approved/written/native links — retire it so the revision queue only holds
    # what genuinely needs a human
    moot = []
    for c in (MatchCandidate.objects.filter(status=MatchCandidate.STATUS_PROPOSED,
                                            party__party_type=party_type,
                                            decision_note__startswith=HOLD_PREFIX)
              .select_related('invoice', 'payment')):
        if c.invoice.unlinked_amount <= Decimal('0.01') or c.payment.unallocated_amount <= Decimal('0.01'):
            c.status = MatchCandidate.STATUS_SUPERSEDED
            moot.append(c)
    MatchCandidate.objects.bulk_update(moot, ['status'], batch_size=1000)
    stats['held'] -= len(moot)
    stats['retired_moot'] = len(moot)
    return stats


WRITTEN_REVIEW_PREFIX = 'مكتوب — يحتاج مراجعة: '
WRITTEN_MANUAL_PREFIX = WRITTEN_REVIEW_PREFIX + 'مراجعة يدوية'

SELECTION_ACTIONS = ('approve', 'reject', 'review')
SELECTION_LIMIT = 500


def _review_note(prefix: str, note: str) -> str:
    return (prefix + (f': {note.strip()}' if note and note.strip() else ''))[:1000]


def send_to_review(candidate: MatchCandidate, note='', user=None) -> str:
    """«Further revision» for one match, whatever its state — mirror only, never SOFTECH:
      proposed → held for manual review (survives re-runs, never auto-approved);
      approved → mirror allocation undone, then held (it was NOT in SOFTECH yet);
      rejected → reopened as a held proposal;
      written  → flagged «مكتوب — يحتاج مراجعة» (reversal stays a separate, deliberate act).
    Returns the resulting state."""
    with transaction.atomic():
        c = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
        before = c.status
        if c.status == MatchCandidate.STATUS_WRITTEN:
            c.decision_note = _review_note(WRITTEN_MANUAL_PREFIX, note)
            c.save(update_fields=['decision_note'])
        elif c.status in (MatchCandidate.STATUS_PROPOSED, MatchCandidate.STATUS_APPROVED,
                          MatchCandidate.STATUS_REJECTED):
            if c.status == MatchCandidate.STATUS_APPROVED:
                alloc = c.allocations.filter(origin=Allocation.ORIGIN_APPROVED).first()
                if alloc is None:
                    raise ReconActionError('لا يوجد تخصيص معتمد لهذا المقترح')
                undo_allocation(alloc, user=user)
                c.refresh_from_db()
            c.status = MatchCandidate.STATUS_PROPOSED
            c.decided_by, c.decided_at = user, timezone.now()
            c.decision_note = _review_note(MANUAL_HOLD_PREFIX, note)
            c.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
        else:
            raise ReconActionError(f'لا يمكن إرسال مرشح في حالة {c.get_status_display()} للمراجعة')
        _audit('candidate_sent_to_review', candidate=c, party=c.party, user=user,
               before={'status': before}, after={'status': c.status, 'note': c.decision_note},
               detail=c.decision_note)
    return c.status


def selection_action(ids, action: str, user=None, note='') -> dict:
    """Apply one mirror action to the rows a person ticked in the grid. Each row is
    independent: a row its guards refuse is reported, never fatal. Approving here is a
    DELIBERATE per-row human choice, so it may include matches held for review (the
    mass «approve all high» button never does). SOFTECH write/reverse are separate."""
    if action not in SELECTION_ACTIONS:
        raise ReconActionError('إجراء غير صالح')
    ids = list(dict.fromkeys(int(i) for i in ids))[:SELECTION_LIMIT]
    res = {'done': 0, 'failed': 0, 'errors': {}, 'held_included': 0}
    for c in MatchCandidate.objects.filter(pk__in=ids).order_by('-confidence_score', 'id'):
        try:
            if action == 'approve':
                if (c.decision_note or '').startswith(HOLD_PREFIX):
                    res['held_included'] += 1
                approve_candidate(c, user=user)
            elif action == 'reject':
                with transaction.atomic():
                    reject_candidate(c, note=note or 'رفض بعد المراجعة', user=user)
            else:
                send_to_review(c, note=note, user=user)
            res['done'] += 1
        except ReconActionError as e:
            res['failed'] += 1
            k = str(e)[:80]
            res['errors'][k] = res['errors'].get(k, 0) + 1
    return res


def flag_written_for_review(party_type: str = 'supplier') -> dict:
    """Allocations ALREADY written to SOFTECH that today's hold rules would have held
    (they were approved before a rule existed). Not proven wrong, so NOT reversed —
    tagged 'مكتوب — يحتاج مراجعة: <reason>' so a reviewer can confirm or revert them
    («↩ عكس من SOFTECH»). Sub-1-EGP rounding rows are ignored. Idempotent."""
    from .models import ReconException
    from .recon_returns import open_returned_by_purchase
    flagged = set(ReconException.objects.filter(
        status='open', payment__isnull=False, party__party_type=party_type,
        exception_type__in=[ReconException.TYPE_DUPLICATE_PAYMENT, ReconException.TYPE_MISALLOCATION,
                            ReconException.TYPE_SUSPECT_AMOUNT],
    ).values_list('payment_id', flat=True))
    returned_open = open_returned_by_purchase(party_type=party_type)
    # the voucher's own reference names ANOTHER invoice of exactly this amount (2026-09-29:
    # 5,529 links shifted by the old conflict bug)
    from .recon_engine import payment_ref_tokens
    inv_no = {}
    for i in APInvoice.objects.filter(party__party_type=party_type, is_return=False).only(
            'id', 'party_id', 'branchcode', 'docnumber', 'doc_value'):
        inv_no[(i.party_id, i.branchcode, str(i.docnumber).split('.')[0].lstrip('0'))] = i
    tagged, cleared, changed = 0, 0, []
    for c in (MatchCandidate.objects.filter(status=MatchCandidate.STATUS_WRITTEN,
                                            party__party_type=party_type)
              .select_related('invoice', 'payment')):
        reason = ''
        if (c.proposed_amount or Decimal('0')) >= Decimal('1'):
            reason = hold_reason(c, flagged, returned_open)
        if not reason and not c.invoice.is_return:
            own = str(c.invoice.docnumber).split('.')[0].lstrip('0')
            toks = {t.lstrip('0') for t in payment_ref_tokens(c.payment)}
            if own not in toks:
                for t in toks:
                    b = inv_no.get((c.invoice.party_id, c.invoice.branchcode, t))
                    if b is not None and b.id != c.invoice_id and abs((b.doc_value or 0) - (c.proposed_amount or 0)) <= Decimal('0.01'):
                        reason = f'السند يسمي الفاتورة {b.branchcode}/{t} بنفس المبلغ — الربط يخالف المرجع'
                        break
        note = (WRITTEN_REVIEW_PREFIX + reason)[:1000] if reason else ''
        was = (c.decision_note or '').startswith(WRITTEN_REVIEW_PREFIX)
        if (c.decision_note or '').startswith(WRITTEN_MANUAL_PREFIX):
            continue                       # a person flagged it — only a person clears it
        if note and c.decision_note != note:
            c.decision_note = note
            changed.append(c)
            tagged += 1
        elif not note and was:
            c.decision_note = ''
            changed.append(c)
            cleared += 1
    MatchCandidate.objects.bulk_update(changed, ['decision_note'], batch_size=1000)
    total = MatchCandidate.objects.filter(status=MatchCandidate.STATUS_WRITTEN, party__party_type=party_type,
                                          decision_note__startswith=WRITTEN_REVIEW_PREFIX).count()
    return {'tagged_now': tagged, 'cleared': cleared, 'written_needing_review': total}


@transaction.atomic
def reject_candidate(candidate: MatchCandidate, note='', user=None) -> MatchCandidate:
    candidate = MatchCandidate.objects.select_for_update().get(pk=candidate.pk)
    if candidate.status not in (MatchCandidate.STATUS_PROPOSED,):
        raise ReconActionError(f'لا يمكن رفض مرشح في حالة {candidate.get_status_display()}')
    candidate.status = MatchCandidate.STATUS_REJECTED
    candidate.decided_by = user
    candidate.decided_at = timezone.now()
    candidate.decision_note = note or ''
    candidate.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note'])
    _audit('candidate_rejected', candidate=candidate, party=candidate.party,
           user=user, detail=note)
    return candidate


@transaction.atomic
def manual_allocate(payment: Payment, invoice: APInvoice, amount, user=None) -> Allocation:
    """Human-created allocation for an arbitrary (payment, invoice) pair."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    invoice = APInvoice.objects.select_for_update().get(pk=invoice.pk)
    amt = _dec(amount)
    _validate_capacity(invoice, payment, amt)
    if Allocation.objects.filter(payment=payment, invoice=invoice).exists():
        raise ReconActionError('يوجد تخصيص مسبق لهذا السند وهذه الفاتورة')

    before = _snapshot(invoice, payment)
    alloc = Allocation.objects.create(
        payment=payment, invoice=invoice, amount=amt,
        cumulative_paid=invoice.linked_amount + amt,
        origin=Allocation.ORIGIN_APPROVED, synced_at=timezone.now(),
    )
    _refresh_payment_flag(payment)
    _supersede_dependents(invoice, payment, keep_pk=None)
    _audit('manual_allocated', allocation=alloc, party=invoice.party, before=before,
           after=_snapshot(invoice, payment), user=user,
           detail=f'تخصيص يدوي {amt} للفاتورة {invoice.docnumber} من سند {payment.cheqsno}')
    return alloc


@transaction.atomic
def undo_allocation(allocation: Allocation, user=None) -> None:
    """
    Remove a mirror allocation. NATIVE SOFTECH allocations (origin='softech') and
    already-written ones (origin='written') are NOT undoable here — reversing those
    is the gated Phase-G reversal, not a mirror delete.
    """
    allocation = Allocation.objects.select_for_update().get(pk=allocation.pk)
    if allocation.origin in (Allocation.ORIGIN_SOFTECH, Allocation.ORIGIN_WRITTEN):
        raise ReconActionError('لا يمكن التراجع عن تخصيص من SOFTECH أو مكتوب — يتطلب عكسًا مُتحكَّمًا (المرحلة G)')
    if ReconAuditEvent.objects.filter(action='allocation_written', allocation=allocation).exists():
        # an approved TOP-UP of a link already in SOFTECH: deleting the mirror row would hide
        # the SOFTECH link — it must be reversed from «مكتوبة» instead
        raise ReconActionError('هذا الربط مكتوب في SOFTECH (بانتظار زيادة المبلغ) — اعكسه من «مكتوبة» بدل التراجع')

    invoice = allocation.invoice
    payment = allocation.payment
    before = _snapshot(invoice, payment)
    cand = allocation.candidate
    allocation.delete()

    if cand and cand.status == MatchCandidate.STATUS_APPROVED:
        cand.status = MatchCandidate.STATUS_PROPOSED
        cand.decided_by = None
        cand.decided_at = None
        cand.save(update_fields=['status', 'decided_by', 'decided_at'])

    payment.refresh_from_db()
    _refresh_payment_flag(payment)
    _audit('allocation_undone', candidate=cand, party=invoice.party, before=before,
           after=_snapshot(invoice, payment), user=user,
           detail=f'تراجع عن تخصيص الفاتورة {invoice.docnumber} / سند {payment.cheqsno}')
