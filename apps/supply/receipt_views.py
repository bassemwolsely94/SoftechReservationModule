"""
apps/supply/receipt_views.py

P-31: /supply «شراء رغم تغطية عالية» — purchases of items the network already held ≥ 6 months of (or stock with no
sales) on the newest sent need sheet, from procurement.ReceiptCheck. A review list. Actions: «مرتجع مطلوب» or
«مقبول» (reason required); every decision is audited.
Supply view / edit rights are checked server-side (CanOperateSupply). Nothing here writes to SOFTECH — the
return itself is a doc 120 entered in SOFTECH, which then closes the row on the next check.

  GET  /api/supply/receipts/?status=open|return_requested|accepted|returned|all
  POST /api/supply/receipts/<id>/decide/   {action: return|accept|reopen, reason}
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .permissions import CanOperateSupply

ACCEPT_REASONS = ('عرض بونص', 'طلب هاتفي', 'توزيع على الفروع', 'بديل متفق عليه')


def _names(rows):
    from apps.catalog.models import Item
    from apps.shortage.supplier_sourcing import _supplier_names
    items = dict(Item.objects.filter(softech_id__in={r.item_code for r in rows}).values_list('softech_id', 'name'))
    sups = _supplier_names({c for r in rows for c in (r.supplier_code, r.sheet_supplier_code) if c})
    return items, sups


def _row(r, items, sups, today):
    return {
        'id': r.id, 'doc_date': r.doc_date.isoformat(), 'age_days': (today - r.doc_date).days,
        'branch_code': r.branch_code, 'doc_number': r.doc_number,
        'supplier_code': r.supplier_code, 'supplier_name': sups.get(r.supplier_code, ''),
        'item_code': r.item_code, 'item_name': items.get(r.item_code, ''),
        'qty': float(r.qty), 'value': float(r.value),
        'flag': r.flag, 'flag_label': r.get_flag_display(),
        'sheet_date': r.sheet.exported_at.date().isoformat() if r.sheet_id else None,
        'sheet_gap': float(r.sheet_gap) if r.sheet_gap is not None else None,
        'received_in_window': float(r.received_in_window) if r.received_in_window is not None else None,
        'sheet_cover': float(r.sheet_cover) if r.sheet_cover is not None else None,
        'sheet_supplier_code': r.sheet_supplier_code,
        'sheet_supplier_name': sups.get(r.sheet_supplier_code, '') if r.sheet_supplier_code else '',
        'status': r.status, 'status_label': r.get_status_display(), 'decision_reason': r.decision_reason,
        'decided_by': r.decided_by.full_name if r.decided_by_id else None,
        'returned_value': float(r.returned_value),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def receipt_checks(request):
    from apps.procurement.models import ReceiptCheck
    st = request.query_params.get('status') or 'open'
    qs = ReceiptCheck.objects.select_related('sheet', 'decided_by')
    if st != 'all':
        qs = qs.filter(status=st)
    rows = list(qs.order_by('-doc_date', 'item_code')[:2000])
    items, sups = _names(rows)
    today = timezone.localdate()
    from apps.procurement.receipt_check import cover_months, pilot_suppliers, window_days
    return Response({'rows': [_row(r, items, sups, today) for r in rows],
                     'pilot_suppliers': pilot_suppliers(), 'window_days': window_days(),
                     'cover_months': cover_months(),
                     'accept_reasons': list(ACCEPT_REASONS)})


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def receipt_check_decide(request, pk):
    from apps.audit.models import AuditLog
    from apps.procurement.models import ReceiptCheck
    row = ReceiptCheck.objects.filter(pk=pk).first()
    if row is None:
        return Response({'detail': 'غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    action = str(request.data.get('action') or '')
    reason = str(request.data.get('reason') or '').strip()[:200]
    new = {'return': 'return_requested', 'accept': 'accepted', 'reopen': 'open'}.get(action)
    if new is None:
        return Response({'detail': 'إجراء غير صالح.'}, status=status.HTTP_400_BAD_REQUEST)
    if row.status == 'returned':
        return Response({'detail': 'السطر أُرجع بالفعل.'}, status=status.HTTP_400_BAD_REQUEST)
    if new == 'accepted' and not reason:
        return Response({'detail': 'اذكر سبب القبول.'}, status=status.HTTP_400_BAD_REQUEST)
    before = {'status': row.status, 'reason': row.decision_reason}
    staff = getattr(request.user, 'staff_profile', None)
    row.status = new
    row.decision_reason = reason if new == 'accepted' else ''
    row.decided_by = staff
    row.decided_at = timezone.now()
    row.save(update_fields=['status', 'decision_reason', 'decided_by', 'decided_at', 'checked_at'])
    AuditLog.log('receipt_check_decided', user=staff, obj=row, old_data=before,
                 new_data={'status': row.status, 'reason': row.decision_reason, 'item': row.item_code,
                           'supplier': row.supplier_code, 'doc': row.doc_number})
    items, sups = _names([row])
    return Response(_row(row, items, sups, timezone.localdate()))
