"""
apps/invoices/views.py

Supplier invoice management with OCR extraction and fuzzy item matching.

OCR runs in a background thread so the create/run-ocr endpoints respond
immediately (status → 'processing') while extraction happens asynchronously.
The client polls GET /invoices/{id}/ until status changes to 'review'.
"""
import threading

from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SupplierInvoice, InvoiceLine
from .serializers import (
    SupplierInvoiceListSerializer, SupplierInvoiceDetailSerializer,
    SupplierInvoiceCreateSerializer,
    InvoiceLineSerializer, InvoiceLineWriteSerializer,
)


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = SupplierInvoice.objects.select_related('branch', 'created_by').annotate(
            line_count=Count('lines'),
            confirmed_count=Count('lines', filter=Q(lines__is_confirmed=True)),
        )
        branch   = self.request.query_params.get('branch')
        status_q = self.request.query_params.get('status')
        supplier = self.request.query_params.get('supplier')
        if branch:
            qs = qs.filter(branch_id=branch)
        if status_q:
            qs = qs.filter(status=status_q)
        if supplier:
            qs = qs.filter(supplier_name__icontains=supplier)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return SupplierInvoiceCreateSerializer
        if self.action == 'retrieve':
            return SupplierInvoiceDetailSerializer
        return SupplierInvoiceListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        invoice = serializer.save(created_by=profile)
        # If image uploaded, kick off OCR in the background
        if invoice.source_image:
            self._run_ocr_async(invoice)

    # ── OCR pipeline ──────────────────────────────────────────────────────────

    def _run_ocr_async(self, invoice: SupplierInvoice):
        """
        Spin up a daemon thread to run OCR so the HTTP response returns
        immediately with status='processing'.  The thread updates the invoice
        to status='review' once done (or appends an error note on failure).
        """
        t = threading.Thread(
            target=self._run_ocr,
            args=(invoice,),
            daemon=True,
            name=f'ocr-invoice-{invoice.pk}',
        )
        t.start()

    def _run_ocr(self, invoice: SupplierInvoice):
        from .ocr import extract_text, parse_lines
        from apps.shortage.matching import find_best_matches
        from apps.catalog.models import Item

        invoice.status = 'processing'
        invoice.save(update_fields=['status'])

        try:
            raw_text = extract_text(invoice.source_image.path)
            invoice.raw_ocr_text = raw_text
            invoice.status       = 'review'
            invoice.save(update_fields=['raw_ocr_text', 'status'])

            candidates = parse_lines(raw_text)
            for idx, cand in enumerate(candidates):
                # Fuzzy match
                matches  = find_best_matches(cand['manual_name'], top_n=1, min_score=0.5)
                item_obj = None
                score    = None
                if matches:
                    best = matches[0]
                    try:
                        item_obj = Item.objects.get(pk=best['item_id'])
                        score    = best['score']
                    except Item.DoesNotExist:
                        pass
                InvoiceLine.objects.create(
                    invoice     = invoice,
                    raw_text    = cand['raw_text'],
                    manual_name = cand['manual_name'],
                    quantity    = cand['quantity'],
                    unit_price  = cand['unit_price'],
                    item        = item_obj,
                    match_score = score,
                    order       = idx,
                )
        except Exception as e:
            invoice.status = 'review'
            invoice.notes  += f'\n[OCR error: {e}]'
            invoice.save(update_fields=['status', 'notes'])

    # ── Re-run OCR ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='run-ocr')
    def run_ocr(self, request, pk=None):
        """
        Re-extract text and rebuild lines from the uploaded image.
        Returns immediately with status='processing'; poll GET /invoices/{id}/
        until status transitions to 'review'.
        """
        invoice = self.get_object()
        if not invoice.source_image:
            return Response({'detail': 'لا توجد صورة مرفوعة'}, status=status.HTTP_400_BAD_REQUEST)
        # Clear existing lines and mark as processing before the thread starts
        invoice.lines.all().delete()
        invoice.status = 'processing'
        invoice.save(update_fields=['status'])
        self._run_ocr_async(invoice)
        return Response({
            'detail': 'جارٍ استخراج النص — راجع الفاتورة بعد لحظات',
            'status': 'processing',
        })

    # ── Add line manually ─────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-line')
    def add_line(self, request, pk=None):
        invoice = self.get_object()
        ser = InvoiceLineWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        line = ser.save(
            invoice=invoice,
            order=invoice.lines.count(),
        )
        return Response(InvoiceLineSerializer(line).data, status=status.HTTP_201_CREATED)

    # ── Update a line ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path=r'lines/(?P<lid>\d+)')
    def update_line(self, request, pk=None, lid=None):
        invoice = self.get_object()
        try:
            line = invoice.lines.get(pk=lid)
        except InvoiceLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        ser = InvoiceLineWriteSerializer(line, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        line = ser.save()
        return Response(InvoiceLineSerializer(line).data)

    # ── Delete a line ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['delete'], url_path=r'lines/(?P<lid>\d+)/delete')
    def delete_line(self, request, pk=None, lid=None):
        invoice = self.get_object()
        try:
            invoice.lines.get(pk=lid).delete()
        except InvoiceLine.DoesNotExist:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Match suggestions for a line ──────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path=r'lines/(?P<lid>\d+)/matches')
    def line_matches(self, request, pk=None, lid=None):
        invoice = self.get_object()
        try:
            line = invoice.lines.get(pk=lid)
        except InvoiceLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        from apps.shortage.matching import find_best_matches
        matches = find_best_matches(line.manual_name or line.raw_text, top_n=8, min_score=0.2)
        return Response(matches)

    # ── Confirm invoice ───────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        invoice = self.get_object()
        invoice.status = 'confirmed'
        invoice.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'تم تأكيد الفاتورة'})

    # ── Reject invoice ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        invoice = self.get_object()
        invoice.status = 'rejected'
        invoice.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'تم رفض الفاتورة'})

    # ── Update invoice header ─────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='update-header')
    def update_header(self, request, pk=None):
        invoice = self.get_object()
        fields  = ['supplier_name', 'invoice_number', 'invoice_date', 'currency',
                   'global_discount_pct', 'global_discount_amt', 'notes']
        for field in fields:
            if field in request.data:
                setattr(invoice, field, request.data[field])
        invoice.save()
        return Response(SupplierInvoiceDetailSerializer(
            self.get_queryset().get(pk=invoice.pk),
            context=self.get_serializer_context()
        ).data)
