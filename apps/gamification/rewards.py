"""
apps/gamification/rewards.py — reward catalog: wallet, redeem, approve, fulfil.

  wallet(staff)              balance = lifetime net points − points held by
                             pending / approved / fulfilled redemptions.
  catalog_for(staff)         every active reward + whether this person can take it now.
  request_reward(...)        validates, holds the points, takes stock, and submits an
                             ApprovalRequest (workflow `gamification_reward`) — the
                             existing /approvals inbox decides. All under a row lock on
                             the player, so two clicks can never spend the same points.
  on_approval_outcome(...)   apps.approvals hook: approved → approved (refused if the
                             requester approved their own request); rejected → refund.
  cancel / fulfil            requester (pending) or manager; manager marks delivery.
  reconcile()                requests closed elsewhere (expired / cancelled in the
                             approvals inbox) → cancelled + refunded.

Redemptions never touch PointEvent, so XP, level and rankings are unaffected.
"""
import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import PlayerProfile, PointEvent, Redemption, Reward

logger = logging.getLogger(__name__)

WORKFLOW_CODE = 'gamification_reward'


class RewardError(Exception):
    """A request that cannot be honoured — message is bilingual for the UI."""


def _month_start():
    return timezone.localdate().replace(day=1)


def wallet(staff):
    earned = PointEvent.objects.filter(staff=staff).aggregate(n=Sum('points'))['n'] or 0
    rows = dict(Redemption.objects.filter(staff=staff, status__in=Redemption.HOLDING)
                .values('status').annotate(n=Sum('cost')).values_list('status', 'n'))
    held = rows.get(Redemption.STATUS_PENDING, 0)
    spent = rows.get(Redemption.STATUS_APPROVED, 0) + rows.get(Redemption.STATUS_FULFILLED, 0)
    return {'earned_net': earned, 'held': held, 'spent': spent,
            'balance': earned - held - spent}


def _level_number(staff):
    p = PlayerProfile.objects.filter(staff=staff).select_related('level').first()
    return p.level.number if p and p.level else 1


def _block_reason(staff, reward, balance, level, used_this_month):
    """None when the reward can be requested now, else (ar, en)."""
    if not reward.is_active:
        return ('المكافأة غير متاحة حالياً', 'This reward is not available')
    if reward.roles and staff.role not in reward.roles:
        return ('غير متاحة لدورك', 'Not available for your role')
    if level < reward.min_level:
        return (f'تحتاج المستوى {reward.min_level}', f'Requires level {reward.min_level}')
    if reward.stock is not None and reward.stock <= 0:
        return ('نفدت الكمية', 'Out of stock')
    if reward.limit_per_month and used_this_month >= reward.limit_per_month:
        return ('وصلت للحد الشهري لهذه المكافأة', 'Monthly limit reached for this reward')
    if balance < reward.cost:
        return (f'رصيدك لا يكفي — ينقصك {reward.cost - balance:,} نقطة',
                f'Not enough points — {reward.cost - balance:,} short')
    return None


def _count_month(staff):
    from django.db.models import Count
    return dict(Redemption.objects.filter(
        staff=staff, status__in=Redemption.HOLDING, created_at__date__gte=_month_start())
        .values('reward_id').annotate(n=Count('id')).values_list('reward_id', 'n'))


def reward_json(r):
    return {'id': r.id, 'name_ar': r.name_ar, 'name_en': r.name_en, 'desc_ar': r.desc_ar,
            'desc_en': r.desc_en, 'icon': r.icon, 'category': r.category, 'cost': r.cost,
            'stock': r.stock, 'limit_per_month': r.limit_per_month, 'min_level': r.min_level,
            'roles': r.roles, 'requires_approval': r.requires_approval,
            'is_active': r.is_active, 'sort': r.sort}


def catalog_for(staff, include_inactive=False):
    w = wallet(staff)
    level = _level_number(staff)
    used = _count_month(staff)
    qs = Reward.objects.all() if include_inactive else Reward.objects.filter(is_active=True)
    out = []
    for r in qs:
        why = _block_reason(staff, r, w['balance'], level, used.get(r.id, 0))
        out.append({**reward_json(r), 'can_request': why is None,
                    'blocked_ar': why[0] if why else '', 'blocked_en': why[1] if why else ''})
    return {'wallet': w, 'level': level, 'rewards': out}


def redemption_json(x):
    ap = x.approval_request
    return {'id': x.id, 'staff_id': x.staff_id,
            'staff_name': x.staff.full_name if x.staff_id else '',
            'branch': x.staff.branch.name if x.staff_id and x.staff.branch_id else '',
            'reward': {'id': x.reward_id, 'name_ar': x.reward.name_ar,
                       'name_en': x.reward.name_en, 'icon': x.reward.icon},
            'cost': x.cost, 'status': x.status, 'status_label': x.get_status_display(),
            'note': x.note, 'decision_note': x.decision_note,
            'fulfillment_note': x.fulfillment_note,
            'approval_request_id': ap.id if ap else None,
            'approval_status': ap.status if ap else None,
            'created_at': x.created_at, 'decided_at': x.decided_at,
            'fulfilled_at': x.fulfilled_at,
            'fulfilled_by': x.fulfilled_by.full_name if x.fulfilled_by_id else ''}


def ensure_workflow():
    """Create the approval workflow if the seed command has not been run yet."""
    from apps.approvals.models import ApprovalStepDefinition, ApprovalWorkflowDefinition
    if ApprovalWorkflowDefinition.objects.filter(code=WORKFLOW_CODE).exists():
        return
    from apps.approvals.management.commands.seed_approval_workflows import WORKFLOWS
    data = next(w for w in WORKFLOWS if w['code'] == WORKFLOW_CODE)
    wf = ApprovalWorkflowDefinition.objects.create(
        **{k: v for k, v in data.items() if k != 'steps'})
    for step in data['steps']:
        ApprovalStepDefinition.objects.create(workflow=wf, **step)


def _restock(reward_id):
    r = Reward.objects.select_for_update().get(pk=reward_id)
    if r.stock is not None:
        r.stock += 1
        r.save(update_fields=['stock', 'updated_at'])


@transaction.atomic
def request_reward(staff, reward_id, note=''):
    # Lock the player row: concurrent requests by the same person are serialised.
    PlayerProfile.objects.get_or_create(staff=staff)
    PlayerProfile.objects.select_for_update().get(staff=staff)
    reward = Reward.objects.select_for_update().filter(pk=reward_id).first()
    if reward is None:
        raise RewardError('مكافأة غير موجودة — unknown reward')
    w = wallet(staff)
    why = _block_reason(staff, reward, w['balance'], _level_number(staff),
                        _count_month(staff).get(reward.id, 0))
    if why:
        raise RewardError(f'{why[0]} — {why[1]}')
    if reward.stock is not None:
        reward.stock -= 1
        reward.save(update_fields=['stock', 'updated_at'])
    x = Redemption.objects.create(staff=staff, reward=reward, cost=reward.cost,
                                  note=(note or '')[:300])
    if not reward.requires_approval:
        x.status, x.decided_at = Redemption.STATUS_APPROVED, timezone.now()
        x.decision_note = 'لا تحتاج موافقة — No approval needed'
        x.save(update_fields=['status', 'decided_at', 'decision_note', 'updated_at'])
        return x
    ensure_workflow()
    from apps.approvals.service import ApprovalService
    ar = ApprovalService.submit(
        workflow_code=WORKFLOW_CODE, subject_object=x,
        title=f'🎁 مكافأة: {reward.name_ar} — {staff.full_name}',
        body=(f'{reward.cost:,} نقطة من رصيد {w["balance"]:,}'
              + (f' — ملاحظة: {x.note}' if x.note else '')),
        requested_by=staff,
        context_data={'reward_id': reward.id, 'cost': reward.cost, 'balance': w['balance'],
                      'redemption_id': x.id},
    )
    x.approval_request = ar
    x.save(update_fields=['approval_request', 'updated_at'])
    # A workflow whose only step auto-skipped can already be terminal.
    ar.refresh_from_db()
    if ar.status in ('approved', 'rejected'):
        on_approval_outcome(ar, ar.status)
    return x


def on_approval_outcome(approval_request, outcome):
    """apps.approvals hook — also covers decisions taken from the /approvals inbox."""
    from apps.approvals.models import ApprovalDecision
    with transaction.atomic():
        x = Redemption.objects.select_for_update().filter(
            approval_request=approval_request).first()
        if x is None or x.status != Redemption.STATUS_PENDING:
            return
        last = ApprovalDecision.objects.filter(request=approval_request).order_by('-id').first()
        x.decided_at = timezone.now()
        x.decision_note = (last.notes if last and last.notes else '')[:300]
        self_approved = ApprovalDecision.objects.filter(
            request=approval_request, decision=ApprovalDecision.DECISION_APPROVED,
            decided_by_id=x.staff_id).exists()
        if outcome == 'approved' and not self_approved:
            x.status = Redemption.STATUS_APPROVED
        else:
            x.status = Redemption.STATUS_REJECTED
            if self_approved:
                x.decision_note = 'لا يجوز اعتماد طلبك بنفسك — self-approval refused'
            _restock(x.reward_id)
        x.save(update_fields=['status', 'decided_at', 'decision_note', 'updated_at'])
    if x.status == Redemption.STATUS_REJECTED and self_approved:
        _notify(x, f'❌ طلب المكافأة «{x.reward.name_ar}» لم يُعتمد',
                'لا يمكن اعتماد طلبك بنفسك — أعيدت النقاط إلى رصيدك.')


def _notify(x, title, body):
    try:
        from apps.notifications.models import Notification
        Notification.objects.create(recipient=x.staff, notification_type='gamification_reward',
                                    title=title, body=body,
                                    dedup_key=f'gam_reward_{x.id}_{x.status}')
    except Exception as exc:
        logger.warning('reward notify failed: %s', exc)


@transaction.atomic
def cancel(x, by, reason=''):
    x = Redemption.objects.select_for_update().get(pk=x.pk)
    is_owner = by.id == x.staff_id
    if is_owner and x.status != Redemption.STATUS_PENDING:
        raise RewardError('يمكنك إلغاء الطلب قبل اعتماده فقط — you can cancel only before approval')
    if Redemption.STATUS_CANCELLED not in Redemption.TRANSITIONS[x.status]:
        raise RewardError('لا يمكن إلغاء هذا الطلب — cannot cancel this request')
    ar = x.approval_request
    if ar is not None and not ar.is_terminal:
        if not (is_owner or by.role == 'admin'):
            # The approvals engine lets only the requester or an admin cancel an open
            # request; other managers decide it (reject) from the /approvals inbox.
            raise RewardError('ارفض الطلب من صندوق الموافقات — reject it from the approvals inbox')
        from apps.approvals.service import ApprovalService
        ApprovalService.cancel(request=ar, cancelled_by=by, reason=reason or 'إلغاء طلب مكافأة')
    x.status = Redemption.STATUS_CANCELLED
    x.decided_at = x.decided_at or timezone.now()
    x.decision_note = (reason or x.decision_note)[:300]
    x.save(update_fields=['status', 'decided_at', 'decision_note', 'updated_at'])
    _restock(x.reward_id)
    if not is_owner:
        _notify(x, f'🚫 أُلغي طلب المكافأة «{x.reward.name_ar}»',
                f'أعيدت {x.cost:,} نقطة إلى رصيدك. {reason}'.strip())
    return x


@transaction.atomic
def fulfil(x, by, note=''):
    x = Redemption.objects.select_for_update().get(pk=x.pk)
    if x.status != Redemption.STATUS_APPROVED:
        raise RewardError('الطلب غير معتمد بعد — the request is not approved')
    if by.id == x.staff_id:
        raise RewardError('لا يمكنك تسليم مكافأتك لنفسك — you cannot fulfil your own reward')
    x.status = Redemption.STATUS_FULFILLED
    x.fulfilled_at, x.fulfilled_by = timezone.now(), by
    x.fulfillment_note = (note or '')[:300]
    x.save(update_fields=['status', 'fulfilled_at', 'fulfilled_by', 'fulfillment_note',
                          'updated_at'])
    _notify(x, f'🎁 تم تسليم مكافأتك «{x.reward.name_ar}»',
            x.fulfillment_note or 'استمتع بها — Enjoy!')
    return x


def reconcile():
    """Pending redemptions whose approval was closed elsewhere (expired, or cancelled
    from the approvals inbox) → cancelled and refunded. Returns how many."""
    n = 0
    for x in Redemption.objects.filter(
            status=Redemption.STATUS_PENDING,
            approval_request__status__in=('cancelled', 'expired')).select_related('approval_request'):
        with transaction.atomic():
            y = Redemption.objects.select_for_update().get(pk=x.pk)
            if y.status != Redemption.STATUS_PENDING:
                continue
            y.status = Redemption.STATUS_CANCELLED
            y.decided_at = timezone.now()
            y.decision_note = f'أُغلق طلب الموافقة ({x.approval_request.status}) — النقاط أعيدت'
            y.save(update_fields=['status', 'decided_at', 'decision_note', 'updated_at'])
            _restock(y.reward_id)
            n += 1
    return n
