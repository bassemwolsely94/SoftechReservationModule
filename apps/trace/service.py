"""
apps/trace/service.py

The one entry point the purchasing (supplier invoice lines) and sales (POS order
lines) hooks call:

    record(raw_scan, event, branch=, staff=, doc_type=, doc_ref=, source='scan')

Returns the PackEvent, or None while settings.TRACK_TRACE_ENABLED is False (the
default) — then nothing is parsed or stored and the caller behaves exactly as today.
Never affects totals, pricing, stock or any SOFTECH write (Rules 2, 3).
"""
from django.conf import settings
from django.db import transaction

from apps.catalog.gs1 import gtin_barcode_candidates, parse_gs1

STATUS_AFTER = {
    'receive': 'in_stock', 'transfer_in': 'in_stock', 'return_in': 'in_stock',
    'sell': 'sold', 'transfer_out': 'in_stock',
    'return_to_supplier': 'returned', 'destroy': 'destroyed',
}

# Doc types the dormant hooks pass — kept here so callers share one vocabulary.
DOC_INVOICE_LINE = 'invoice_line'          # invoices.InvoiceLine (purchasing receive)
DOC_POS_ORDER_LINE = 'pos_order_line'      # pos_orders.SoftechSalesOrderLine (sale)
DOC_EXPIRY_DISPOSAL = 'expiry_disposal'    # batches.ExpiryDisposalRecord (destroy)


def enabled():
    return bool(getattr(settings, 'TRACK_TRACE_ENABLED', False))


def match_item(gtin):
    """Item for a GTIN-14 via ItemBarcode or Item.barcode (EAN-13 = GTIN without the leading 0)."""
    from apps.catalog.models import Item, ItemBarcode
    codes = gtin_barcode_candidates(gtin)
    bc = ItemBarcode.objects.filter(barcode__in=codes, is_active=True).select_related('item').first()
    if bc:
        return bc.item
    return Item.objects.filter(barcode__in=codes).first()


def record(raw, event, branch=None, staff=None, doc_type='', doc_ref='', source='scan'):
    if not enabled():
        return None
    from .models import PackCode, PackEvent
    if event not in STATUS_AFTER:
        raise ValueError(f'unknown pack event {event!r}')
    parsed = parse_gs1(raw)
    with transaction.atomic():
        pack, created = PackCode.objects.select_for_update().get_or_create(
            gtin=parsed['gtin'], serial=parsed['serial'],
            defaults={'batch': parsed['batch'], 'expiry': parsed['expiry'], 'branch': branch,
                      'item': match_item(parsed['gtin'])})
        flag = ''
        if (not created and event == 'receive'
                and pack.events.filter(event='receive').exists()):
            flag = 'duplicate_receive'
        ev = PackEvent.objects.create(pack=pack, event=event, doc_type=doc_type, doc_ref=str(doc_ref or ''),
                                      branch=branch, staff=staff, source=source, raw=str(raw)[:200],
                                      flag=flag)
        if not flag:
            pack.status = STATUS_AFTER[event]
            if branch is not None:
                pack.branch = branch
            pack.save(update_fields=['status', 'branch'])
    return ev
