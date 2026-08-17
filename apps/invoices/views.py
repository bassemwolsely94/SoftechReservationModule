"""
apps/invoices/views.py

Supplier invoice management with OCR extraction and fuzzy item matching.

OCR runs in a background thread so the create/run-ocr endpoints respond
immediately (status → 'processing') while extraction happens asynchronously.
The client polls GET /invoices/{id}/ until status changes to 'review'.
"""
import csv
import io
import logging
import threading

from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SupplierInvoice, InvoiceLine, VendorProfile, VendorItemMapping
from .serializers import (
    SupplierInvoiceListSerializer, SupplierInvoiceDetailSerializer,
    SupplierInvoiceCreateSerializer,
    InvoiceLineSerializer, InvoiceLineWriteSerializer,
    VendorProfileSerializer,
)
from .anomalies import check_invoice_anomalies

logger = logging.getLogger('elrezeiky.invoices')


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = SupplierInvoice.objects.select_related('branch', 'created_by', 'vendor').annotate(
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
        import json
        from .ocr import (extract_text, parse_lines, normalize_expiry,
                          extract_structured, parse_structured)
        from apps.shortage.matching import find_best_matches, _normalize
        from apps.catalog.models import Item

        invoice.status = 'processing'
        invoice.save(update_fields=['status'])

        try:
            # ── 1. Preferred: structured JSON (header + lines + confidence) ──
            structured = None
            try:
                structured = extract_structured(invoice.source_image.path)
            except Exception as e:
                logger.warning('structured OCR failed (%s) — falling back to text', e)

            if structured and structured.get('lines'):
                header, candidates = parse_structured(structured)
                invoice.raw_ocr_text = json.dumps(structured, ensure_ascii=False)[:20000]
                self._apply_ocr_header(invoice, header)
            else:
                raw_text   = extract_text(invoice.source_image.path)
                invoice.raw_ocr_text = raw_text
                candidates = parse_lines(raw_text)

            invoice.status = 'review'
            invoice.save()

            # Resolve the supplier → SOFTECH personcode and link a VendorProfile
            # BEFORE item matching, so vendor-scoped mappings (steps 1 & 2 below)
            # apply. Offline resolution (learned + curated top-10); never fatal.
            if not (invoice.vendor_id and invoice.vendor and invoice.vendor.softech_personcode):
                try:
                    from . import suppliers
                    res = suppliers.link_invoice_vendor(invoice)
                    if res:
                        logger.info('invoice %s supplier %r → personcode %s (%s)',
                                    invoice.pk, invoice.supplier_name, res['personcode'], res['source'])
                except Exception as e:
                    logger.warning('supplier resolution failed for invoice %s: %s', invoice.pk, e)

            vendor = invoice.vendor

            # ── Tier 0: SOFTECH itemssuppliers recall (authoritative code→item) ─
            # One read for the whole invoice: supplier's printed codes → catalog
            # itemcode, via itemssuppliers.suppitemcode. Read-only, never fatal.
            supplier_code_map = {}
            if vendor and vendor.softech_personcode and vendor.is_main:
                codes = [(c.get('vendor_item_code') or '').strip() for c in candidates]
                codes = [c for c in codes if c]
                if codes:
                    try:
                        from . import supplier_items
                        conn = supplier_items.open_conn()
                        try:
                            supplier_code_map = supplier_items.resolve_codes(
                                conn, vendor.softech_personcode, codes)
                        finally:
                            conn.close()
                    except Exception as e:
                        logger.warning('itemssuppliers recall failed for invoice %s: %s', invoice.pk, e)

            for idx, cand in enumerate(candidates):
                name_raw = cand['manual_name'] or cand['raw_text']
                code     = (cand.get('vendor_item_code') or '').strip()
                item_obj = None
                score    = None

                # ── 0. SOFTECH itemssuppliers: supplier code → catalog item ─
                if code and code in supplier_code_map:
                    item_obj = Item.objects.filter(softech_id=supplier_code_map[code]).first()
                    if item_obj:
                        score = 1.0

                # ── 1. Learned supplier item code (our PG mirror) ──────────
                if item_obj is None and code:
                    code_qs = VendorItemMapping.objects.filter(vendor_item_code=code)
                    if vendor:
                        code_qs = code_qs.filter(vendor=vendor)
                    m = code_qs.select_related('item').order_by('-use_count').first()
                    if m:
                        item_obj, score = m.item, 1.0

                # ── 2. Learned name mapping ────────────────────────────────
                if item_obj is None and name_raw:
                    norm = _normalize(name_raw)
                    name_qs = VendorItemMapping.objects.filter(raw_name_normalized=norm)
                    if vendor:
                        name_qs = name_qs.filter(vendor=vendor)
                    m = name_qs.select_related('item').order_by('-use_count').first()
                    if m:
                        item_obj, score = m.item, 1.0

                # ── 3. Learned corpus + fuzzy fallback ─────────────────────
                #   Catalog names are mostly English; supplier lines are often
                #   Arabic. Match the printed Arabic name first, and ONLY when
                #   that's weak fall back to the model's English generic guess —
                #   so a good Arabic hit is never overridden by a higher-scoring
                #   but wrong English one (the n-best idea, gated for safety).
                match_review = False
                if item_obj is None and name_raw:
                    vcode  = (vendor.softech_personcode or '') if vendor else ''
                    m      = find_best_matches(name_raw, top_n=1, min_score=0.5, vendor_code=vcode)
                    ar     = m[0] if m else None
                    best   = ar
                    gen_en = (cand.get('generic_name_en') or '').strip()
                    en     = None
                    if gen_en:
                        m2 = find_best_matches(gen_en, top_n=1, min_score=0.5, vendor_code=vcode)
                        en = m2[0] if m2 else None
                        # English only RESCUES a weak Arabic hit (never overrides a good one)
                        if (best is None or best['score'] < 0.60) and en and \
                           (best is None or en['score'] > best['score']):
                            best = en
                    # Disagreement flag: Arabic and English both matched, but to
                    # DIFFERENT items → uncertain, mark for human verification.
                    if ar and en and ar['item_id'] != en['item_id']:
                        match_review = True
                    if best:
                        try:
                            item_obj = Item.objects.get(pk=best['item_id'])
                            score    = best['score']
                        except Item.DoesNotExist:
                            pass

                InvoiceLine.objects.create(
                    invoice                = invoice,
                    raw_text               = cand['raw_text'],
                    manual_name            = name_raw,
                    manufacturer           = cand.get('manufacturer', ''),
                    vendor_item_code       = code,
                    batch_number           = cand.get('batch_number', ''),
                    # Normalize expiry at ingest so every line stores a parseable
                    # 'YYYY-MM-DD' (keeps the raw printed text when unparseable).
                    expiry_date            = normalize_expiry(cand.get('expiry_date', '')) or cand.get('expiry_date', ''),
                    quantity               = cand['quantity'],
                    public_price           = cand.get('public_price', 0),
                    discount_pct           = cand.get('discount_pct', 0),
                    extra_discount_pct     = cand.get('extra_discount_pct', 0),
                    unit_price             = cand.get('unit_price', 0),
                    vat_pct                = cand.get('vat_pct', 0),
                    distributor_margin_amt = cand.get('distributor_margin_amt', 0),
                    pharmacist_margin_amt  = cand.get('pharmacist_margin_amt', 0),
                    item                   = item_obj,
                    match_score            = score,
                    match_review           = match_review,
                    ocr_confidence         = cand.get('ocr_confidence'),
                    order                  = idx,
                )
        except Exception as e:
            invoice.status = 'review'
            invoice.notes  += f'\n[OCR error: {e}]'
            invoice.save(update_fields=['status', 'notes'])

    @staticmethod
    def _apply_ocr_header(invoice, header):
        """Fill blank invoice header fields from the OCR'd header (never overwrite
        what a user already entered)."""
        from datetime import datetime
        if header.get('supplier_name') and not invoice.supplier_name:
            invoice.supplier_name = header['supplier_name'][:200]
        if header.get('invoice_number') and not invoice.invoice_number:
            invoice.invoice_number = header['invoice_number'][:50]
        if header.get('currency') and not invoice.currency:
            invoice.currency = header['currency'][:10]
        if header.get('invoice_date') and not invoice.invoice_date:
            try:
                invoice.invoice_date = datetime.strptime(header['invoice_date'][:10], '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass
        if header.get('declared_total'):
            invoice.declared_total = header['declared_total']

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
        # A human confirming (or re-picking) the item resolves any match-review flag.
        if line.match_review and (line.is_confirmed or 'item' in request.data):
            line.match_review = False
            line.save(update_fields=['match_review'])
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

    # ── Learn vendor mapping ──────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path=r'lines/(?P<lid>\d+)/learn')
    def learn_mapping(self, request, pk=None, lid=None):
        """
        Save / increment a VendorItemMapping for a confirmed line.
        Called after the user confirms a line to improve future matching.
        """
        invoice = self.get_object()
        try:
            line = invoice.lines.select_related('item').get(pk=lid)
        except InvoiceLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if not line.item_id:
            return Response({'detail': 'لا يوجد صنف مطابق للتعلم'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.shortage.matching import _normalize
        norm    = _normalize(line.manual_name or line.raw_text or '')
        profile = getattr(request.user, 'staff_profile', None)
        code    = (line.vendor_item_code or '').strip()

        mapping, created = VendorItemMapping.objects.get_or_create(
            vendor              = invoice.vendor,
            raw_name_normalized = norm,
            defaults={
                'item':             line.item,
                'vendor_item_code': code,
                'use_count':        1,
                'created_by':       profile,
            }
        )
        if not created:
            # Update item if the user picked a different one
            mapping.item      = line.item
            mapping.use_count += 1
            if code:
                mapping.vendor_item_code = code   # learn/refresh the supplier code too
            mapping.save(update_fields=['item', 'vendor_item_code', 'use_count', 'updated_at'])

        # Also feed the shared cross-module corpus (vendor-scoped by SOFTECH code),
        # so the same name resolves in shortage lists and other invoices too.
        vcode = (invoice.vendor.softech_personcode or '') if invoice.vendor_id and invoice.vendor else ''
        try:
            from apps.shortage.matching import learn_alias
            learn_alias(line.manual_name or line.raw_text or '', line.item,
                        source='invoice', vendor_code=vcode)
        except Exception as e:
            logger.warning('learn_alias failed for invoice line %s: %s', line.pk, e)

        # Inject the confirmed code → item into SOFTECH itemssuppliers so the NEXT
        # invoice from this supplier resolves this code instantly (tier 0 above).
        # Gated by INVOICE_SUPPLIER_ITEM_WRITE_ENABLED; never fatal to the confirm.
        # A CHANGE to an existing mapping is refused until the data-entry user
        # approves the warning (request `approve_link_change`=true) — then applied
        # and reported back so the user is notified of the discrepancy they signed off.
        injected = None
        approve_change = bool(request.data.get('approve_link_change'))
        vendor_is_main = bool(invoice.vendor_id and invoice.vendor and invoice.vendor.is_main)
        if code and vcode and vendor_is_main:   # only inject for official/main suppliers
            try:
                from . import supplier_items
                if supplier_items.write_enabled():
                    conn = supplier_items.open_conn()
                    try:
                        injected = supplier_items.inject_mapping(
                            conn, vcode, line.item.softech_id, code,
                            commit=True, approved=approve_change)
                    finally:
                        conn.close()
                    if injected.get('action') == 'needs_approval':
                        logger.info('itemssuppliers change needs approval %s/%s=%s: %s',
                                    vcode, line.item.softech_id, code, injected['discrepancies'])
                    else:
                        logger.info('itemssuppliers inject %s/%s=%s → %s',
                                    vcode, line.item.softech_id, code, injected)
                        if injected.get('discrepancies') and injected.get('committed'):
                            # AUDIT: the user approved a mapping change — record who/what.
                            actor = getattr(profile, 'display_name', None) or getattr(request.user, 'username', '?')
                            logger.warning('AUDIT vendor-code change approved by %s: vendor %s '
                                           'item %s code %s — %s', actor, vcode,
                                           line.item.softech_id, code, injected['discrepancies'])
            except Exception as e:
                logger.warning('itemssuppliers inject failed for line %s: %s', line.pk, e)

        return Response({
            'detail':  'تم حفظ الربط للتعلم المستقبلي',
            'created': created,
            'softech_link': injected,
            'mapping': {
                'raw_name_normalized': norm,
                'item_id':             line.item_id,
                'item_name':           line.item.name,
                'use_count':           mapping.use_count,
            }
        })

    # ── Anomaly check ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def anomalies(self, request, pk=None):
        """Return list of anomalies detected on the invoice lines."""
        invoice = self.get_object()
        result  = check_invoice_anomalies(invoice)
        return Response({
            'count':     len(result),
            'anomalies': result,
        })

    # ── Excel export ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='export-excel')
    def export_excel(self, request, pk=None):
        invoice = self.get_object()
        from .export import export_invoice_excel
        xlsx_bytes = export_invoice_excel(invoice)
        supplier   = (invoice.supplier_name or 'فاتورة').replace(' ', '_')
        inv_num    = f'_{invoice.invoice_number}' if invoice.invoice_number else ''
        filename   = f'invoice_{supplier}{inv_num}.xlsx'
        response   = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # ── CSV export ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='export-csv')
    def export_csv(self, request, pk=None):
        invoice  = self.get_object()
        from .export import export_invoice_csv
        csv_bytes = export_invoice_csv(invoice)
        supplier  = (invoice.supplier_name or 'فاتورة').replace(' ', '_')
        filename  = f'invoice_{supplier}.csv'
        response  = HttpResponse(csv_bytes, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

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

    # ── SOFTECH writeback (Track B) ───────────────────────────────────────────

    _PUSH_ROLES = {'admin', 'purchasing', 'supervisor'}

    def _can_push(self, request):
        profile = getattr(request.user, 'staff_profile', None)
        return bool(profile and getattr(profile, 'role', None) in self._PUSH_ROLES)

    @action(detail=True, methods=['post'], url_path='push-preview')
    def push_preview(self, request, pk=None):
        """Dry-run: build the exact SOFTECH plan (header + line column→value maps + SQL)
        WITHOUT writing anything. Safe for any authenticated user to inspect."""
        from . import writer
        invoice = self.get_object()
        try:
            result = writer.push_final(invoice, dry_run=True)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=['post', 'get'])
    def validate(self, request, pk=None):
        """Run the SofTech save-time validations (credit limit, item allowed, price caps,
        expiry required, …) and return {ok, errors[], warnings[]}. Read-only."""
        from . import validations
        invoice = self.get_object()
        return Response(validations.validate_invoice(invoice, live=True))

    @action(detail=True, methods=['post'])
    def push(self, request, pk=None):
        """Write the invoice into SOFTECH as a FINAL purchase document (doccode 10/120).
        Gated by INVOICE_WRITER_ENABLED — while off this returns the dry-run plan.
        Requires a privileged role and a confirmed invoice. Validation errors refuse the
        push; warnings refuse unless force=true is sent."""
        from . import writer
        invoice = self.get_object()
        if not self._can_push(request):
            return Response({'detail': 'غير مصرح بترحيل الفواتير إلى ERP'},
                            status=status.HTTP_403_FORBIDDEN)
        if invoice.status not in ('confirmed', 'queued', 'push_failed'):
            return Response({'detail': 'يجب تأكيد الفاتورة قبل الترحيل'},
                            status=status.HTTP_400_BAD_REQUEST)
        force = str(request.data.get('force', '')).lower() in ('1', 'true', 'yes')
        try:
            result = writer.push_final(invoice, dry_run=False, force=force)
        except writer.WriterDisabled as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'فشل الترحيل: {e}'}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    @action(detail=True, methods=['post'], url_path='create-return')
    def create_return(self, request, pk=None):
        """Create a return-to-supplier (doccode 120) DRAFT from a finalized purchase,
        cloning its matched lines and linking return_of_docnumber to the original
        SOFTECH docnumber. The draft opens in 'review' so quantities can be trimmed
        (partial return) before confirm + push."""
        original = self.get_object()
        if original.doc_kind != 'purchase' or original.status != 'finalized' or not original.softech_docnumber:
            return Response({'detail': 'يمكن إنشاء مرتجع فقط من فاتورة شراء مُرحّلة إلى ERP'},
                            status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(request.user, 'staff_profile', None)
        ret = SupplierInvoice.objects.create(
            branch=original.branch, vendor=original.vendor, doc_kind='return',
            return_of_docnumber=original.softech_docnumber,
            supplier_name=original.supplier_name, invoice_number=original.invoice_number,
            invoice_date=original.invoice_date, currency=original.currency,
            status='review', created_by=profile,
            notes=f'مرتجع للفاتورة {original.id} (مستند SOFTECH #{original.softech_docnumber})',
        )
        for l in original.lines.filter(item__isnull=False):
            InvoiceLine.objects.create(
                invoice=ret, item=l.item, manual_name=l.manual_name, manufacturer=l.manufacturer,
                vendor_item_code=l.vendor_item_code, batch_number=l.batch_number, expiry_date=l.expiry_date,
                quantity=l.quantity, public_price=l.public_price, unit_price=l.unit_price,
                discount_pct=l.discount_pct, extra_discount_pct=l.extra_discount_pct, vat_pct=l.vat_pct,
                match_score=1.0, is_confirmed=True, order=l.order,
            )
        return Response({'id': ret.id, 'detail': 'تم إنشاء مسودة مرتجع — عدّل الكميات ثم أكّد ورحّل'},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reconcile(self, request, pk=None):
        """Read-only: verify a finalized invoice's document still exists in SOFTECH
        (detect deletion; flag if a return references it). Any authenticated user."""
        from . import writer
        invoice = self.get_object()
        try:
            result = writer.reconcile(invoice)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'تعذّر التحقق: {e}'}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    @action(detail=True, methods=['post'])
    def probe(self, request, pk=None):
        """Rollback probe — execute the REAL inserts on the branch DB then ALWAYS roll
        back (zero residue). For TEST-INSTANCE validation only; admin-only."""
        from . import writer
        invoice = self.get_object()
        profile = getattr(request.user, 'staff_profile', None)
        if not (profile and getattr(profile, 'role', None) == 'admin'):
            return Response({'detail': 'مسموح للمدير فقط'}, status=status.HTTP_403_FORBIDDEN)
        try:
            result = writer.probe_invoice(invoice, confirm=True)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'فشل الاختبار: {e}'}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    # ── Update invoice header ─────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='update-header')
    def update_header(self, request, pk=None):
        invoice = self.get_object()
        fields  = ['supplier_name', 'invoice_number', 'invoice_date', 'currency',
                   'global_discount_pct', 'global_discount_amt', 'notes', 'vendor']
        for field in fields:
            if field in request.data:
                setattr(invoice, field, request.data[field])
        invoice.save()
        return Response(SupplierInvoiceDetailSerializer(
            self.get_queryset().get(pk=invoice.pk),
            context=self.get_serializer_context()
        ).data)


# ── Vendor Profile ViewSet ────────────────────────────────────────────────────

class VendorProfileViewSet(viewsets.ModelViewSet):
    queryset           = VendorProfile.objects.all().order_by('name')
    serializer_class   = VendorProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        q  = self.request.query_params.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        if self.request.query_params.get('main') in ('1', 'true'):
            qs = qs.filter(is_main=True)
        return qs

    @action(detail=False, methods=['get'])
    def main(self, request):
        """The official/main distributors (is_main) — drives the supplier-PO picker
        and the matrix columns. [{personcode, name}]."""
        rows = (VendorProfile.objects.filter(is_main=True)
                .exclude(softech_personcode='').order_by('name')
                .values('softech_personcode', 'name'))
        return Response([{'personcode': r['softech_personcode'], 'name': r['name']} for r in rows])
