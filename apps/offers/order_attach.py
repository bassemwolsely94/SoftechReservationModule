"""
apps/offers/order_attach.py — Phase-3 exec step 3.

Attach a deterministic offer plan onto a REAL POS order (PG side only): writes each
promo line's `cust_discp` + `applied_offer` + `discount_source='offer'`, recomputes
the line pricing, records `OfferApplication` audit rows, and — when the plan needs
sign-off (offer-mode magnitude or a margin breach) — raises an approval request
through the EXISTING `apps/approvals` engine (reuse, not a parallel flow).

Guardrails:
  • Gated behind settings.POS_OFFERS_EXECUTION_ENABLED (default False) — OFF ⇒ no-op.
  • Writes NOTHING to SOFTECH. The push still posts `cust_discp` exactly as today.
  • A pending/rejected offer approval BLOCKS the live push (server-enforced).
"""
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.pos_orders import pricing
from .attach import build_attach_plan, _d
from .models import Offer, OfferApplication, MarginConfig

OFFER_WORKFLOW_CODE = 'offer_override'


def execution_enabled():
    return bool(getattr(settings, 'POS_OFFERS_EXECUTION_ENABLED', False))


def resolve_order_customer(order):
    """Best-effort Customer for per-customer usage limits (by softech_pic)."""
    pic = getattr(order, 'softech_pic', '') or ''
    if not pic:
        return None
    from apps.customers.models import Customer
    return Customer.objects.filter(softech_pic=pic).first()


def _basket_from_order(order):
    basket = []
    for ln in order.lines.all().order_by('id'):
        basket.append({
            'softech_id': ln.softech_itemcode,
            'item': ln.item,
            'qty': ln.qty,
            'unit_price': ln.item_sale_price,
        })
    return basket


@transaction.atomic
def apply_offers_to_order(order, *, actor=None, commit=True):
    """
    Evaluate offers on the order and (if enabled + commit) write them onto the
    lines. Returns a summary dict. Never contacts SOFTECH.
    """
    if not execution_enabled():
        return {'enabled': False, 'attached': False, 'requires_approval': False,
                'detail': 'تنفيذ العروض غير مُفعّل (POS_OFFERS_EXECUTION_ENABLED=False).'}

    order_lines = list(order.lines.all().order_by('id'))
    basket = _basket_from_order(order)
    out = build_attach_plan(basket, branch_id=order.branch_id,
                            channel=order.channel, margin_cfg=MarginConfig.get_solo())
    plan = out['plan']

    # primary offer per line (highest-priority applied offer that touches it)
    offer_ids = [ap['offer_id'] for ap in plan['applied']]
    offers_by_id = Offer.objects.in_bulk(offer_ids)
    primary_by_line = {}
    for ap in sorted(plan['applied'], key=lambda a: -a['priority']):
        for ln in ap['lines']:
            primary_by_line.setdefault(ln['index'], ap['offer_id'])

    if not commit:
        return {'enabled': True, 'attached': False, 'requires_approval': plan['requires_approval'],
                'plan': plan, 'lines': out['lines']}

    # write cust_discp + provenance onto the real lines, recompute pricing
    attached_lines = 0
    for row in out['lines']:
        i = row['index']
        line = order_lines[i]
        offer_id = primary_by_line.get(i)
        if offer_id is None or row['cust_discp'] <= 0:
            continue
        line.cust_discp = row['cust_discp']
        line.discount_source = 'offer'
        line.applied_offer = offers_by_id.get(offer_id)
        c = pricing.compute_line(item_sale_price=line.item_sale_price,
                                 sale_tax_pct=line.sale_tax_pct, qty=line.qty,
                                 cust_discp=line.cust_discp, new_cost_price=line.new_cost_price)
        line.trans_price = c['trans_price']
        line.trans_price_total = c['trans_price_total']
        line.item_sale_tax = c['item_sale_tax']
        line.save(update_fields=['cust_discp', 'discount_source', 'applied_offer',
                                 'trans_price', 'trans_price_total', 'item_sale_tax'])
        attached_lines += 1

    # audit rows (pending — was_applied flips true at push in step 5)
    OfferApplication.objects.filter(pos_order=order).delete()
    for ap in plan['applied']:
        safe_lines = [{'index': l['index'], 'discount': float(l['discount'])} for l in ap['lines']]
        OfferApplication.objects.create(
            offer_id=ap['offer_id'], pos_order=order, branch=order.branch,
            discount_amount=_d(ap['discount']), was_applied=False,
            reason='attached (pending push)',
            detail={'authorization_source': ap.get('authorization_source'), 'lines': safe_lines},
        )

    approval = None
    if plan['requires_approval'] and actor is not None:
        approval = _raise_offer_approval(order, actor, plan)

    return {
        'enabled': True, 'attached': True, 'attached_lines': attached_lines,
        'requires_approval': plan['requires_approval'],
        'approval_request_id': getattr(approval, 'id', None),
        'plan': plan, 'lines': out['lines'],
    }


# ── approvals integration (reuse apps/approvals) ────────────────────────────────
def ensure_offer_workflow():
    """Get-or-create a single-step supervisor workflow for offer overrides."""
    from apps.approvals.models import ApprovalWorkflowDefinition, ApprovalStepDefinition
    wf, _ = ApprovalWorkflowDefinition.objects.get_or_create(
        code=OFFER_WORKFLOW_CODE,
        defaults={'category': 'operational', 'name': 'Offer override',
                  'name_ar': 'اعتماد عرض', 'is_active': True})
    if not wf.steps.exists():
        ApprovalStepDefinition.objects.create(
            workflow=wf, order=1, name='Supervisor approval',
            name_ar='اعتماد المشرف', approver_role='supervisor')
    return wf


def _raise_offer_approval(order, actor, plan):
    from apps.approvals.service import ApprovalService
    ensure_offer_workflow()
    reason = 'خصم عرض يتجاوز كارت الصنف' if any(
        a.get('authorization_source') == 'offer' for a in plan['applied']) else 'كسر حد الهامش'
    return ApprovalService.submit(
        workflow_code=OFFER_WORKFLOW_CODE, subject_object=order,
        title=f'اعتماد عرض — أمر {order.pk}', requested_by=actor, body=reason,
        context_data={'total_discount': str(plan['total_discount']), 'reason': reason})


def offer_approval_request(order):
    """The latest offer_override ApprovalRequest for this order, or None."""
    from django.contrib.contenttypes.models import ContentType
    from apps.approvals.models import ApprovalRequest
    ct = ContentType.objects.get_for_model(order.__class__)
    return (ApprovalRequest.objects
            .filter(content_type=ct, object_id=order.pk, workflow__code=OFFER_WORKFLOW_CODE)
            .order_by('-id').first())


def push_blocked_by_offer_approval(order):
    """
    Return a reason string if a LIVE push must be blocked pending offer approval,
    else None. No-op for orders with no offer-driven lines.
    """
    if not order.lines.filter(discount_source='offer').exists():
        return None
    req = offer_approval_request(order)
    if req is None:
        return None
    if req.status == 'approved':
        return None
    if req.status == 'rejected':
        return 'تم رفض اعتماد العرض — لا يمكن الإرسال.'
    return 'أمر يحتوي عرضًا بانتظار اعتماد المشرف — لا يمكن الإرسال قبل الاعتماد.'
