"""
apps/trace/views.py

POST /api/trace/parse/  {raw}  — admin-only diagnostic for testing 2D scanners: the
parsed GS1 fields + the matched item. Stores nothing; works whether or not
TRACK_TRACE_ENABLED is on.

POST /api/trace/scan/  {raw, event, doc_type, doc_ref}  — the dormant hook the supplier
invoice receiving grid (doc_type invoice_line) and the POS order line (pos_order_line)
call per scanned pack. 404 while TRACK_TRACE_ENABLED is False: the screens show no
scan field and nothing is stored. Never changes the invoice, the order or SOFTECH.
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.catalog.gs1 import GS1Error, parse_gs1
from core.permissions import deny_unless
from apps.users.permissions import IsAdminRole

from . import service
from .service import enabled, match_item


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminRole])
def parse_scan(request):
    try:
        p = parse_gs1(request.data.get('raw'))
    except GS1Error as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    item = match_item(p['gtin'])
    return Response({
        'gtin': p['gtin'], 'serial': p['serial'], 'batch': p['batch'],
        'expiry': p['expiry'].isoformat() if p['expiry'] else None,
        'item_id': item.pk if item else None,
        'item_name': (item.name if item else ''),
        'enabled': enabled(),
    })


_DOC_MODELS = {
    service.DOC_INVOICE_LINE: ('invoices', 'InvoiceLine'),
    service.DOC_POS_ORDER_LINE: ('pos_orders', 'SoftechSalesOrderLine'),
}
# The grant a scan needs: the same as writing that document line.
_DOC_MODULE = {service.DOC_INVOICE_LINE: 'invoices', service.DOC_POS_ORDER_LINE: 'pos'}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def scan(request):
    if not enabled():
        return Response({'detail': 'track-and-trace is not enabled'}, status=status.HTTP_404_NOT_FOUND)
    from django.apps import apps
    doc_type = request.data.get('doc_type') or ''
    doc_ref = str(request.data.get('doc_ref') or '')
    if doc_type not in _DOC_MODELS:
        return Response({'detail': 'unknown doc_type'}, status=status.HTTP_400_BAD_REQUEST)
    denied = deny_unless(request, _DOC_MODULE[doc_type], 'create', 'edit')
    if denied:
        return denied
    if not apps.get_model(*_DOC_MODELS[doc_type]).objects.filter(pk=doc_ref).exists():
        return Response({'detail': 'document line not found'}, status=status.HTTP_400_BAD_REQUEST)
    event = 'receive' if doc_type == service.DOC_INVOICE_LINE else 'sell'
    profile = getattr(request.user, 'staff_profile', None)
    try:
        ev = service.record(request.data.get('raw'), event, branch=getattr(profile, 'branch', None),
                            staff=profile, doc_type=doc_type, doc_ref=doc_ref)
    except GS1Error as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'pack_id': ev.pack_id, 'event': ev.event, 'flag': ev.flag,
                     'gtin': ev.pack.gtin, 'serial': ev.pack.serial}, status=status.HTTP_201_CREATED)
