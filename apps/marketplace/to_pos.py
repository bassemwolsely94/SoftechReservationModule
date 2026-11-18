"""
apps/marketplace/to_pos.py — turn an accepted ExternalOrder into a DRAFT POS order (doc 38 §5.1).

Every platform order is a credit (آجل) sale to the platform's own SOFTECH customer, classed «عميل دائم»
(owner 2026-11-18): channel='permanent', cust_branch_code = channel.softech_personcode. A «عميل دائم» sale
normally defaults to cash; pos_orders/platform_accounts.py makes a platform account's sale 100% آجل. This module only creates a draft SoftechSalesOrder; staff
push it through the existing POS flow. It never calls the SOFTECH writer. Totals are computed at push by
pos_orders/pricing.py — nothing is reimplemented here. Line prices are the item's normal POS prices
(Item.pack_price / pack_price_tax / sale_tax_pct), never the platform price.
"""
import uuid

from apps.audit.models import AuditLog
from apps.marketplace.models import ExternalOrder
from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine

POS_CHANNEL = 'permanent'   # «عميل دائم» — the class of every platform account in SOFTECH (owner 2026-11-18)


def convert(order, user):
    channel = order.channel
    personcode = (channel.softech_personcode or '').strip()
    if not personcode:
        raise ValueError('حساب المنصة في SOFTECH غير محدد')

    token = uuid.uuid5(uuid.NAMESPACE_URL, f'marketplace:{channel.code}:{order.external_id}')
    existing = SoftechSalesOrder.objects.filter(client_token=token).first()
    if existing:
        return _link_existing(order, existing, personcode, user)

    lines = list(order.lines.select_related('item'))
    if any(l.item is None for l in lines):
        raise ValueError('في الطلب صنف غير مربوط بصنف في النظام — لا يمكن إنشاء مسودة نقطة البيع')

    branch = order.branch
    bc = branch.softech_branch_id or ''
    draft = SoftechSalesOrder.objects.create(
        status=SoftechSalesOrder.STATUS_DRAFT, doc_kind='sale', channel=POS_CHANNEL, client_token=token,
        branch=branch, softech_branchcode=bc, store_code=bc if len(bc) <= 3 else bc[:3],
        cust_branch_code=personcode, customer_name=f'{channel.name} — {order.external_id}'[:255],
        notes=f'طلب {channel.name} رقم {order.external_id}', created_by=user,
        seller_usercode=((getattr(user, 'softech_user_id', '') or '').strip())[:5])
    for l in lines:
        item = l.item
        SoftechSalesOrderLine.objects.create(
            order=draft, item=item, softech_itemcode=item.softech_id, item_name=item.name[:120], qty=l.qty,
            item_sale_price=item.pack_price or 0, item_sale_price_tax=item.pack_price_tax or 0,
            sale_tax_pct=item.sale_tax_pct or 0, cust_discp=0)
    order.pos_order = draft
    order.save(update_fields=['pos_order', 'updated_at'])
    AuditLog.log('marketplace_pos_draft_created', user=user, obj=order,
                 new_data={'pos_order_id': draft.pk},
                 extra={'channel': channel.code, 'external_id': order.external_id})
    return draft


def _link_existing(order, existing, personcode, user):
    """A draft with this order's token already exists (e.g. an earlier accept that lost its link): reuse it
    only when it is plainly this order's draft; anything else is refused instead of silently linked."""
    if order.pos_order_id == existing.pk:
        return existing
    linked_to = ExternalOrder.objects.filter(pos_order=existing).exclude(pk=order.pk).exists()
    if (existing.branch_id != order.branch_id or existing.channel != POS_CHANNEL
            or (existing.cust_branch_code or '').strip() != personcode
            or existing.status == SoftechSalesOrder.STATUS_CANCELLED or linked_to):
        raise ValueError('يوجد طلب نقطة بيع بنفس رقم الطلب لا يطابق هذا الطلب — راجع نقطة البيع')
    order.pos_order = existing
    order.save(update_fields=['pos_order', 'updated_at'])
    AuditLog.log('marketplace_pos_draft_linked', user=user, obj=order,
                 new_data={'pos_order_id': existing.pk, 'status': existing.status},
                 extra={'channel': order.channel.code, 'external_id': order.external_id})
    return existing
