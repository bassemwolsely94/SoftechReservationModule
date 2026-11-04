"""
apps/usage_print/services.py — the sheet workflow: open (and re-check) a sheet, confirm / exclude a
line, print. Backend owns every rule; the page only shows the result.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog

from .models import UsageSheet, UsageSheetLine as L
from .suggest import suggest_for


class NotReady(Exception):
    """Print refused: a line is still waiting for confirmation."""


def _pos_order(inv):
    from apps.pos_orders.models import SoftechSalesOrder
    return (SoftechSalesOrder.objects
            .filter(softech_branchcode=inv.branch.softech_branch_id,
                    softech_final_docnumber=int(inv.docnumber))
            .filter(softech_docdate=inv.docdate)
            .order_by('-id').first())


@transaction.atomic
def open_sheet(inv, profile):
    """The sheet for this invoice, created on first open. On every open the snapshot is re-checked
    against the current invoice: unchanged items keep their confirmation, new or re-quantified items
    go back to pending, removed items are dropped (invoice_changed tells the page)."""
    sheet, created = UsageSheet.objects.select_for_update().get_or_create(
        softech_invoice_id=inv.invoice_id,
        defaults={'branch': inv.branch, 'docnumber': inv.docnumber, 'docdate': inv.docdate,
                  'source': inv.source, 'created_by': profile})
    sheet.purchase = inv.purchase or sheet.purchase
    sheet.customer = inv.customer
    sheet.patient_name = inv.patient_name
    if inv.source == UsageSheet.SOURCE_MIRROR:
        sheet.source = inv.source
    if sheet.pos_order_id is None:
        sheet.pos_order = _pos_order(inv)

    existing = {ln.itemcode: ln for ln in sheet.lines.all()}
    changed = False
    for order, (code, row) in enumerate(inv.lines.items()):
        ln = existing.pop(code, None)
        if ln is None:
            text, src = suggest_for(row['item'], inv.customer, exclude_sheet=sheet)
            L.objects.create(sheet=sheet, item=row['item'], itemcode=code, item_name=row['name'],
                             quantity=row['qty'], suggested_text=text, suggestion_source=src, text=text,
                             sort_order=order)
            changed = changed or not created
            continue
        updates = {'sort_order': order, 'item_name': row['name']}
        if ln.quantity != row['qty']:
            updates.update(quantity=row['qty'], status=L.STATUS_PENDING, confirmed_by=None, confirmed_at=None)
            changed = True
        for k, v in updates.items():
            setattr(ln, k, v)
        ln.save()
    if existing:
        L.objects.filter(pk__in=[ln.pk for ln in existing.values()]).delete()
        changed = True
    sheet.invoice_changed = changed
    sheet.save()
    return sheet


def set_line(line, action, text, profile, request=None):
    """confirm (needs text) · exclude · reset. Any text change un-confirms the line."""
    text = (text or '').strip()[:300]
    before = {'status': line.status, 'text': line.text}
    if action == 'confirm':
        if not text:
            raise ValueError('اكتب طريقة الاستخدام قبل التأكيد.')
        line.text, line.status = text, L.STATUS_CONFIRMED
        line.confirmed_by, line.confirmed_at = profile, timezone.now()
        audit = 'usage_line_confirmed'
    elif action == 'exclude':
        line.status = L.STATUS_EXCLUDED
        line.confirmed_by, line.confirmed_at = profile, timezone.now()
        audit = 'usage_line_excluded'
    elif action == 'reset':
        if text:
            line.text = text
        line.status, line.confirmed_by, line.confirmed_at = L.STATUS_PENDING, None, None
        audit = None
    else:
        raise ValueError('إجراء غير معروف.')
    line.save()
    if audit:
        AuditLog.log(audit, user=profile, obj=line.sheet, request=request,
                     old_data=before, new_data={'status': line.status, 'text': line.text},
                     extra={'invoice': line.sheet.softech_invoice_id, 'itemcode': line.itemcode,
                            'suggested': line.suggested_text, 'source': line.suggestion_source})
    return line


@transaction.atomic
def mark_printed(sheet, layout, profile, request=None):
    sheet = UsageSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.lines.filter(status=L.STATUS_PENDING).exists():
        raise NotReady('أكّد كل الأصناف أو اختار «لا يطبع» قبل الطباعة.')
    if not sheet.lines.filter(status=L.STATUS_CONFIRMED).exists():
        raise NotReady('لا يوجد صنف مؤكد للطباعة.')
    sheet.print_count += 1
    sheet.last_printed_at, sheet.last_printed_by, sheet.last_layout = timezone.now(), profile, layout
    sheet.save(update_fields=['print_count', 'last_printed_at', 'last_printed_by', 'last_layout', 'updated_at'])
    AuditLog.log('usage_sheet_printed', user=profile, obj=sheet, request=request,
                 extra={'invoice': sheet.softech_invoice_id, 'layout': layout, 'print_count': sheet.print_count,
                        'lines': list(sheet.lines.filter(status=L.STATUS_CONFIRMED)
                                      .values_list('itemcode', 'text'))})
    return sheet
