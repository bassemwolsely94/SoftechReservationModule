"""
apps/commerce/views.py — Phase 2 API for the Commerce Document engine.

The whole surface is gated by settings.COMMERCE_DOCS_ENABLED (503 when off) so it
stays invisible until switched on.  Retail invoices / quotations use hand-typed
lines with inclusive VAT; allocation documents also accept per-branch cells.
"""
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes as perm_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.insurance.permissions import CommerceModuleAccess

from .models import (
    DocumentType, Recipient, RecipientLocation,
    CommerceDocument, DocumentLine, AllocationCell, next_document_number,
)
from .serializers import (
    DocumentTypeSerializer, RecipientSerializer, RecipientLocationSerializer,
    CommerceDocumentSerializer, CommerceDocumentListSerializer, DocumentLineSerializer,
)


def _enabled():
    return bool(getattr(settings, 'COMMERCE_DOCS_ENABLED', False))


class _FlagGate:
    """Mixin: 503 the whole viewset when the feature flag is off, and gate access
    on the 'commerce' RBAC module."""
    permission_classes = [CommerceModuleAccess]

    def initial(self, request, *args, **kwargs):
        if not _enabled():
            self.permission_denied  # noqa - fall through to explicit response below
        return super().initial(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not _enabled():
            from django.http import JsonResponse
            return JsonResponse({'error': 'وحدة المستندات التجارية غير مُفعَّلة.', 'enabled': False},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return super().dispatch(request, *args, **kwargs)


@api_view(['GET'])
@perm_classes([IsAuthenticated])
def commerce_status(request):
    """Lightweight flag probe for the frontend nav."""
    return Response({'enabled': _enabled(),
                     'types': DocumentTypeSerializer(
                         DocumentType.objects.filter(is_active=True), many=True).data
                     if _enabled() else []})


class DocumentTypeViewSet(_FlagGate, viewsets.ReadOnlyModelViewSet):
    queryset = DocumentType.objects.filter(is_active=True)
    serializer_class = DocumentTypeSerializer


class RecipientViewSet(_FlagGate, viewsets.ModelViewSet):
    queryset = Recipient.objects.prefetch_related('locations').all()
    serializer_class = RecipientSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        kind = self.request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    @action(detail=True, methods=['post', 'delete'], url_path='locations(?:/(?P<loc_id>[0-9]+))?')
    def locations(self, request, pk=None, loc_id=None):
        recipient = self.get_object()
        if request.method == 'DELETE':
            RecipientLocation.objects.filter(pk=loc_id, recipient=recipient).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        ser = RecipientLocationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        loc = ser.save(recipient=recipient)
        return Response(RecipientLocationSerializer(loc).data, status=status.HTTP_201_CREATED)


class CommerceDocumentViewSet(_FlagGate, viewsets.ModelViewSet):
    queryset = (CommerceDocument.objects
                .select_related('doc_type', 'recipient')
                .prefetch_related('lines').all())

    def get_serializer_class(self):
        return CommerceDocumentListSerializer if self.action == 'list' else CommerceDocumentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tc = self.request.query_params.get('type_code')
        if tc:
            qs = qs.filter(doc_type__code=tc)
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        return qs

    def perform_create(self, serializer):
        dt = serializer.validated_data['doc_type']
        staff = getattr(self.request.user, 'staff_profile', None)
        doc_date = serializer.validated_data.get('doc_date') or timezone.now().date()
        serializer.save(
            number=next_document_number(dt, on_date=doc_date),
            vat_rate=serializer.validated_data.get('vat_rate') or dt.default_vat_rate,
            created_by=staff,
        )

    # ── Line management ───────────────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='lines')
    def add_line(self, request, pk=None):
        doc = self.get_object()
        ser = DocumentLineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ln = ser.save(document=doc)
        doc.recompute_totals()
        return Response(DocumentLineSerializer(ln).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'], url_path='lines/(?P<line_id>[0-9]+)')
    def edit_line(self, request, pk=None, line_id=None):
        doc = self.get_object()
        try:
            ln = doc.lines.get(pk=line_id)
        except DocumentLine.DoesNotExist:
            return Response({'error': 'البند غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if request.method == 'DELETE':
            ln.delete()
            doc.recompute_totals()
            return Response(status=status.HTTP_204_NO_CONTENT)
        ser = DocumentLineSerializer(ln, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        doc.recompute_totals()
        return Response(DocumentLineSerializer(ln).data)

    # ── Allocation cells (Option A grid) ──────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='lines/(?P<line_id>[0-9]+)/cells')
    def set_cell(self, request, pk=None, line_id=None):
        """Set one line's quantity at one branch; recomputes the line's total qty."""
        doc = self.get_object()
        try:
            ln = doc.lines.get(pk=line_id)
        except DocumentLine.DoesNotExist:
            return Response({'error': 'البند غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        loc_id = request.data.get('location')
        try:
            loc = RecipientLocation.objects.get(pk=loc_id, recipient=doc.recipient)
        except RecipientLocation.DoesNotExist:
            return Response({'error': 'الفرع غير موجود لهذه الجهة'}, status=status.HTTP_400_BAD_REQUEST)
        qty = request.data.get('quantity', 0)
        AllocationCell.objects.update_or_create(
            line=ln, location=loc, defaults={'quantity': qty})
        ln.sync_quantity_from_cells()
        doc.recompute_totals()
        return Response({'line': ln.id, 'location': loc.id, 'quantity': float(qty),
                         'line_quantity': float(ln.quantity), 'doc_total': float(doc.total)})

    @action(detail=True, methods=['get'], url_path='grid')
    def grid(self, request, pk=None):
        """Return the allocation matrix: branches (cols) × lines (rows) with cell qty."""
        doc = self.get_object()
        locs = list(doc.recipient.locations.filter(is_active=True)) if doc.recipient else []
        rows = []
        for ln in doc.lines.all():
            cells = {c.location_id: float(c.quantity) for c in ln.cells.all()}
            rows.append({'line_id': ln.id, 'item_name': ln.item_name,
                         'unit_price': float(ln.unit_price),
                         'cells': {l.id: cells.get(l.id, 0) for l in locs},
                         'total_qty': float(ln.quantity), 'line_total': float(ln.line_total)})
        return Response({
            'locations': [{'id': l.id, 'name': l.name} for l in locs],
            'rows': rows, 'total': float(doc.total),
        })

    @action(detail=True, methods=['get'], url_path='export')
    def export(self, request, pk=None):
        doc = self.get_object()
        from .export import generate_invoice_excel
        return generate_invoice_excel(doc)
