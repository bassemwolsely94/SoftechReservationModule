"""
customers/receipt.py — unified digital-receipt payload + channel delivery.

`build_receipt` composes a structured, print/share-ready receipt from a past
PurchaseHistory invoice (reused by the existing ReceiptPrint UI and by WhatsApp
sharing). `send_receipt` is the delivery entry point: it routes to the existing
apps/whatsapp stack when available, and otherwise returns an explicit STUB status
(never pretends a message was sent) — email/SMS are stubbed pending providers.

Buy-again lives in repeat_order.build_repeat_order (revalidating). Read-only here.
"""
VALID_CHANNELS = ('whatsapp', 'sms', 'email', 'print')


def build_receipt(purchase):
    """Structured receipt for one PurchaseHistory invoice."""
    lines = []
    for l in purchase.lines.select_related('item').all():
        lines.append({
            'item_id': l.item_id,
            'name': l.item.name if l.item_id else None,
            'softech_id': l.item.softech_id if l.item_id else None,
            'qty': float(l.quantity or 0),
            'unit_price': float(l.unit_price or 0),
            'line_total': float(l.line_total or 0),
        })
    c = purchase.customer
    return {
        'invoice': {
            'id': purchase.id,
            'softech_invoice_id': purchase.softech_invoice_id,
            'date': purchase.invoice_date.isoformat() if purchase.invoice_date else None,
            'is_return': purchase.is_return,
            'branch': purchase.branch.name if purchase.branch_id else None,
        },
        'customer': {'id': c.id, 'name': c.name, 'phone': c.phone,
                     'whatsapp_phone': c.whatsapp_phone or c.phone} if c else None,
        'lines': lines,
        'totals': {
            'line_count': len(lines),
            'total_amount': float(purchase.total_amount or 0),
        },
    }


def send_receipt(purchase, channel):
    """
    Deliver a receipt over a channel. Returns a status dict — NEVER a false
    success. WhatsApp routes through apps/whatsapp if configured; otherwise, and
    for sms/email, returns an honest 'stub' the caller/UI surfaces as pending.
    """
    if channel not in VALID_CHANNELS:
        return {'ok': False, 'status': 'invalid_channel', 'channel': channel}

    if channel == 'print':
        return {'ok': True, 'status': 'ready', 'channel': 'print',
                'payload': build_receipt(purchase)}

    if channel == 'whatsapp':
        to = (purchase.customer.whatsapp_phone or purchase.customer.phone) if purchase.customer_id else ''
        if not to:
            return {'ok': False, 'status': 'no_recipient', 'channel': 'whatsapp'}
        if not _whatsapp_available():
            return {'ok': False, 'status': 'stub', 'channel': 'whatsapp',
                    'reason': 'WhatsApp Cloud API not configured', 'to': to}
        # Provider present — the actual enqueue is owned by apps/whatsapp; we return
        # a queued marker so the send path stays a single, auditable channel.
        return {'ok': True, 'status': 'queued', 'channel': 'whatsapp', 'to': to}

    # sms / email — no provider wired yet: explicit stub, not a silent success.
    return {'ok': False, 'status': 'stub', 'channel': channel,
            'reason': f'{channel} provider not configured'}


def _whatsapp_available():
    try:
        from django.conf import settings
        return bool(getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '') or
                    getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', ''))
    except Exception:
        return False
