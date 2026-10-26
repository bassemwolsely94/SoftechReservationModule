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

from core.permissions import MatrixPermission

from .models import (SupplierInvoice, InvoiceLine, VendorProfile, VendorItemMapping,
                     InvoiceBatch, PurchaseOrder)
from .serializers import (
    SupplierInvoiceListSerializer, SupplierInvoiceDetailSerializer,
    SupplierInvoiceCreateSerializer,
    InvoiceLineSerializer, InvoiceLineWriteSerializer,
    VendorProfileSerializer,
    InvoiceBatchListSerializer, InvoiceBatchDetailSerializer, InvoiceBatchCreateSerializer,
    PurchaseOrderSerializer,
)
from .anomalies import check_invoice_anomalies
from apps.catalog.wildcard import wq
from core.errors import public_error

logger = logging.getLogger('elrezeiky.invoices')


def _audit_invoice_push(request, invoice, result, force):
    """Who pushed this invoice into SOFTECH (Batch 2, P-16) — only when it really wrote."""
    if isinstance(result, dict) and result.get('wrote_to_softech'):
        from core.softech_audit import audit_softech_write
        audit_softech_write('softech_invoice_pushed', actor=request.user, obj=invoice,
                            after={'docnumber': result.get('docnumber'), 'mode': result.get('mode')},
                            force=bool(force))


def _bank_invoice_sample(invoice, candidates, engine='gemini'):
    """Bank a supplier-invoice OCR image + its line-item names into the in-house corpus
    (module purchasing_invoice) so it feeds the same accuracy/training pipeline. Best-effort."""
    try:
        from apps.vision.models import record_sample
        readings = [{'readings': [c.get('raw_text') or c.get('manual_name') or ''],
                     'strength': '', 'qty': c.get('quantity') or c.get('qty')}
                    for c in (candidates or [])
                    if (c.get('raw_text') or c.get('manual_name'))]
        if not readings:
            return
        record_sample(module='purchasing_invoice', media_type='image', engine=engine,
                      image=invoice.source_image, raw_readings=readings,
                      branch=getattr(invoice, 'branch', None), source_ref=str(invoice.pk))
    except Exception:
        pass


def _link_invoice_corpus(invoice_pk, raw_name, item):
    """Label the invoice's banked OCR sample with a human confirmation (best-effort)."""
    if not item:
        return
    try:
        from apps.vision.models import OcrSample, add_confirmation
        s = (OcrSample.objects.filter(module='purchasing_invoice', source_ref=str(invoice_pk or ''))
             .order_by('-created_at').first())
        if s:
            add_confirmation(s.id, reading=raw_name, item=item)
    except Exception:
        pass


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module = 'invoices'
    rbac_actions = {
        # reads and read-only checks (POST only to send parameters)
        'push_preview': ('view',), 'duplicate_check': ('view',), 'reconcile_financials': ('view',),
        'po_match': ('view',), 'validate': ('view',), 'probe': ('view',),
        'export_excel': ('export',), 'export_csv': ('export',),
        # editing the invoice before it is confirmed (run-ocr = paid OCR + replaces the lines)
        'run_ocr': ('edit',), 'add_line': ('edit',), 'update_line': ('edit',), 'recompute_line': ('edit',),
        'learn_mapping': ('edit',), 'update_header': ('edit',), 'reconcile': ('edit',),
        'delete_line': ('edit', 'delete'),
        # decisions — confirm is the only precondition of the SOFTECH push
        'confirm': ('approve',), 'confirm_green': ('approve',), 'reject': ('approve',),
        'create_return': ('approve',),
        # the SOFTECH write itself (also keeps its own _PUSH_ROLES check)
        'push': ('finalize',), 'push_batch': ('finalize',),
    }
    rbac_delete = ('delete', 'approve')
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = SupplierInvoice.objects.select_related('branch', 'created_by', 'vendor').annotate(
            line_count=Count('lines'),
            confirmed_count=Count('lines', filter=Q(lines__is_confirmed=True)),
            attention_count=Count('lines', filter=Q(lines__match_review=True)
                                   | Q(lines__needs_pick=True) | Q(lines__item__isnull=True)),
        )
        branch   = self.request.query_params.get('branch')
        status_q = self.request.query_params.get('status')
        supplier = self.request.query_params.get('supplier')
        attention = self.request.query_params.get('attention')
        if branch:
            qs = qs.filter(branch_id=branch)
        if status_q:
            qs = qs.filter(status=status_q)
        if supplier:
            qs = qs.filter(wq(supplier, 'supplier_name'))
        # fast-lane: '1' = only invoices needing review (flags / unmatched / pick /
        # review lines); 'clean' = none of those, for bulk confirming.
        if attention in ('1', 'true'):
            qs = qs.filter(Q(attention_count__gt=0) | ~Q(ocr_flags=[]))
        elif attention == 'clean':
            qs = qs.filter(attention_count=0, ocr_flags=[])
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

    def _run_ocr_async(self, invoice: SupplierInvoice, engine=None):
        """
        Spin up a daemon thread to run OCR so the HTTP response returns
        immediately with status='processing'.  The thread updates the invoice
        to status='review' once done (or appends an error note on failure).
        """
        t = threading.Thread(
            target=self._run_ocr,
            args=(invoice,),
            kwargs={'engine': engine},
            daemon=True,
            name=f'ocr-invoice-{invoice.pk}',
        )
        t.start()

    def _run_ocr(self, invoice: SupplierInvoice, engine=None):
        import json
        from .ocr import (extract_text, parse_lines,
                          extract_structured, parse_structured, vendor_prompt_hints)

        invoice.status = 'processing'
        invoice.save(update_fields=['status'])

        # Per-distributor extraction hints when the supplier is known at upload.
        hints = ''
        if invoice.vendor_id and invoice.vendor and invoice.vendor.ocr_profile:
            try:
                hints = vendor_prompt_hints(invoice.vendor.ocr_profile)
            except Exception as e:
                logger.warning('vendor_prompt_hints failed for invoice %s: %s', invoice.pk, e)

        try:
            # ── 1. Preferred: structured JSON (header + lines + confidence) ──
            structured = None
            try:
                structured = extract_structured(invoice.source_image.path, hints,
                                                engine=engine, vendor=invoice.vendor)
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

            # bank the invoice OCR into the in-house corpus (best-effort)
            _bank_invoice_sample(invoice, candidates)

            # Supplier resolution + 4-tier item matching + line creation — the
            # single shared implementation (reused by bundle ingestion).
            from . import pipeline
            pipeline.build_lines(invoice, candidates)

            # Thorough SOFTECH duplicate scan (we're already in a background thread),
            # cached on the invoice so the list flags re-entries before anyone opens it.
            try:
                from . import writer
                writer.scan_invoice_duplicates(invoice)
            except Exception as e:
                logger.warning('dup scan failed for invoice %s: %s', invoice.pk, e)
        except Exception as e:
            invoice.status = 'review'
            invoice.notes  += f'\n[OCR error: {e}]'
            invoice.save(update_fields=['status', 'notes'])

    @staticmethod
    def _apply_ocr_header(invoice, header):
        """Fill blank invoice header fields from the OCR'd header (never overwrite
        what a user already entered). Delegates to the shared pipeline."""
        from . import pipeline
        pipeline.apply_ocr_header(invoice, header)

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
        engine = (request.data.get('engine') or request.query_params.get('engine') or '').strip() or None
        invoice.lines.all().delete()
        invoice.status = 'processing'
        invoice.save(update_fields=['status'])
        self._run_ocr_async(invoice, engine=engine)
        return Response({
            'detail': 'جارٍ استخراج النص — راجع الفاتورة بعد لحظات',
            'status': 'processing',
        })

    @action(detail=False, methods=['get'], url_path='ocr-engines')
    def ocr_engines(self, request):
        """Which OCR engines are available (for the re-read picker)."""
        from . import engines
        return Response({'available': engines.available_engines(),
                         'default': engines.resolve_engine()})

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
        # the machine's suggestion before this edit — replaced → remembered as rejected for
        # this spelling (vendor-scoped), so it ranks lower next time (shortage/learning)
        suggested_id = line.item_id if not line.is_confirmed else None
        ser = InvoiceLineWriteSerializer(line, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        line = ser.save()
        if suggested_id and 'item' in request.data and line.item_id != suggested_id:
            try:
                from apps.shortage.learning import record_rejection
                vcode = (invoice.vendor.softech_personcode or '') if invoice.vendor_id and invoice.vendor else ''
                record_rejection(line.manual_name or line.raw_text or '', suggested_id,
                                 vendor_code=vcode, source='invoice')
            except Exception as e:
                logger.warning('record_rejection failed for invoice line %s: %s', line.pk, e)
        # A human confirming (or re-picking) the item resolves the review/pick flags.
        clear = []
        if line.match_review and (line.is_confirmed or 'item' in request.data):
            line.match_review = False; clear.append('match_review')
        if line.needs_pick and 'item' in request.data:
            line.needs_pick = False; clear.append('needs_pick')
        if clear:
            line.save(update_fields=clear)
        return Response(InvoiceLineSerializer(line).data)

    # ── SofTech-column grid (load) + per-cell recompute (keystroke) ─────────────

    @action(detail=True, methods=['get'])
    def grid(self, request, pk=None):
        """The editable SofTech-mirror grid: every line as its recomputed column row
        (backend-authoritative), with FOC preview and new/old price check."""
        from . import grid as grid_mod
        invoice = self.get_object()
        # live warehouse stock (رصيد حالي) for the target branch/store — best-effort,
        # skippable via ?stock=0 (avoids the SOFTECH round-trip while editing).
        stock_map = {}
        if request.query_params.get('stock') not in ('0', 'false'):
            try:
                from . import writer
                stock_map = writer.read_stock_for_invoice(invoice)
            except Exception:
                stock_map = {}
        lines = list(invoice.lines.select_related('item').all())
        fold = grid_mod.invoice_folds_margin(invoice, lines)
        rows = [grid_mod.grid_row(l, stock_map, fold_margin=fold) for l in lines]
        return Response({
            'invoice_id': invoice.id,
            'doc_kind':   invoice.doc_kind,
            'rows':       rows,
            'columns':    grid_mod.sc.FIELD_TO_SOFTECH,
            'fold_margin': fold,   # distributor margin folds into the posted cost?
            # the bottom totals SofTech shows (Method 1 — VAT outside cost; distributor
            # margin added when folded), so the operator can eyeball them vs the paper.
            'tax_summary': grid_mod.tax_summary(lines, fold_margin=fold),
            'declared_total': float(invoice.declared_total) if invoice.declared_total is not None else None,
        })

    @action(detail=True, methods=['post'], url_path='recompute-line')
    def recompute_line(self, request, pk=None):
        """Stateless per-row recompute for a grid edit — body {cells, changed, tax_rate?}.
        Returns the consistent row + FOC + the stktrans money fields. No DB write."""
        from . import grid as grid_mod
        self.get_object()   # permission / existence check
        return Response(grid_mod.recompute_cells(request.data or {}))

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
        # never learn a batch number as the supplier's item code (it changes every delivery)
        from .ocr import separate_code_and_batch
        if code and separate_code_and_batch(code, line.batch_number)[2]:
            code = ''

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
        _link_invoice_corpus(invoice.pk, line.manual_name or line.raw_text or '', line.item)

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
                            commit=True, approved=approve_change, actor=request.user)
                    finally:
                        conn.close()
                    if injected.get('committed'):
                        from apps.catalog.supplier_links import link_code
                        link_code(vcode, line.item.softech_id, code)     # mirror stays current
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

    @action(detail=True, methods=['post'], url_path='confirm-green')
    def confirm_green(self, request, pk=None):
        """Bulk-confirm every 'green' line — matched to an item, priced, qty>0, no
        review flag, and match score ≥ 0.85 — so the operator only hand-checks the few
        flagged lines. Learns each confirmed mapping (PG VendorItemMapping + corpus) so
        the next invoice resolves them instantly. Returns how many were confirmed +
        how many still need review."""
        from . import grid as grid_mod
        from .models import VendorItemMapping
        from apps.shortage.matching import _normalize
        invoice = self.get_object()
        profile = getattr(request.user, 'staff_profile', None)
        vcode = (invoice.vendor.softech_personcode or '') if invoice.vendor_id and invoice.vendor else ''
        confirmed, still_review = 0, 0
        for line in invoice.lines.select_related('item').all():
            cells = grid_mod.line_cells(line)
            row = grid_mod.sc.recompute(cells, changed='unit_cost' if float(line.unit_price or 0) > 0 else None)
            needs = grid_mod._needs_review(line, row)[0]
            priced = float(line.unit_price or 0) > 0 or float(line.public_price or 0) > 0
            score_ok = (line.match_score is None) or (float(line.match_score) >= 0.85)
            green = (line.item_id and not line.is_confirmed and not needs and priced
                     and float(line.quantity or 0) > 0 and score_ok)
            if not green:
                if line.item_id and not line.is_confirmed and needs:
                    still_review += 1
                continue
            line.is_confirmed = True
            line.save(update_fields=['is_confirmed'])
            confirmed += 1
            # learn the mapping (fast PG side only; SOFTECH itemssuppliers injection
            # stays on explicit confirm/push to avoid a burst of writes here).
            try:
                norm = _normalize(line.manual_name or line.raw_text or '')
                code = (line.vendor_item_code or '').strip()
                from .ocr import separate_code_and_batch
                if code and separate_code_and_batch(code, line.batch_number)[2]:
                    code = ''
                m, created = VendorItemMapping.objects.get_or_create(
                    vendor=invoice.vendor, raw_name_normalized=norm,
                    defaults={'item': line.item, 'vendor_item_code': code,
                              'use_count': 1, 'created_by': profile})
                if not created:
                    m.item = line.item; m.use_count += 1
                    if code:
                        m.vendor_item_code = code
                    m.save(update_fields=['item', 'vendor_item_code', 'use_count', 'updated_at'])
                from apps.shortage.matching import learn_alias
                learn_alias(line.manual_name or line.raw_text or '', line.item,
                            source='invoice', vendor_code=vcode)
                _link_invoice_corpus(invoice.pk, line.manual_name or line.raw_text or '', line.item)
            except Exception as e:
                logger.warning('bulk learn failed for line %s: %s', line.pk, e)
        return Response({'confirmed': confirmed, 'still_review': still_review,
                         'detail': f'تم تأكيد {confirmed} سطراً جاهزاً' +
                                   (f'؛ {still_review} بحاجة لمراجعة' if still_review else '')})

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
        # learning loop: remember vendor→item mappings so future invoices from
        # this distributor match instantly (best-effort, never blocks confirm).
        learned = 0
        try:
            from . import pipeline
            learned = pipeline.learn_invoice_mappings(
                invoice, getattr(request.user, 'staff_profile', None))
        except Exception as e:
            logger.warning('auto-learn on confirm failed for invoice %s: %s', invoice.pk, e)
        return Response({'detail': 'تم تأكيد الفاتورة', 'learned_mappings': learned})

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
        from . import writer, suppliers
        invoice = self.get_object()
        suppliers.ensure_invoice_vendor(invoice)
        try:
            result = writer.push_final(invoice, dry_run=True)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # surface a duplicate warning on the post button (our module + SOFTECH)
        try:
            result['duplicates'] = writer.check_duplicates(invoice)
        except Exception as e:
            result['duplicates'] = {'is_duplicate': False, 'error': str(e)[:200]}
        return Response(result)

    @action(detail=True, methods=['get', 'post'], url_path='duplicate-check')
    def duplicate_check(self, request, pk=None):
        """Thorough multi-factor duplicate check (our module + SOFTECH). Returns the
        full result (with scored candidates) AND refreshes the cached list summary."""
        from . import writer
        from django.utils import timezone
        invoice = self.get_object()
        result = writer.check_duplicates(invoice)
        try:
            best = max((c['score'] for c in result.get('candidates', [])), default=0.0)
            invoice.dup_check = {
                'is_duplicate': bool(result.get('is_duplicate')),
                'likely_duplicate': bool(result.get('likely_duplicate')),
                'best_score': round(best, 3),
                'softech_docnumber': (result.get('softech_match') or {}).get('docnumber'),
                'candidates': len(result.get('candidates', [])),
                'checked_softech': bool(result.get('checked_softech')),
            }
            invoice.dup_checked_at = timezone.now()
            invoice.save(update_fields=['dup_check', 'dup_checked_at'])
        except Exception:
            pass
        return Response(result)

    @action(detail=True, methods=['get', 'post'], url_path='reconcile-financials')
    def reconcile_financials(self, request, pk=None):
        """Three-way total reconciliation: OCR-declared vs our reconstructed Σ-lines
        vs SOFTECH-posted. SOFTECH is a human-entered reference, not ground truth."""
        from . import writer
        return Response(writer.reconcile_three_way(self.get_object()))

    @action(detail=True, methods=['get', 'post'], url_path='po-match')
    def po_match(self, request, pk=None):
        """Advisory goods-received check: compare this invoice to its linked PO (or
        a ?po=<id> given now). Variance only — never affects posting. Can also link
        a PO via POST {po: id}."""
        from . import po as po_mod
        from .models import PurchaseOrder
        invoice = self.get_object()
        po_id = request.data.get('po') or request.query_params.get('po')
        if po_id:
            try:
                invoice.po = PurchaseOrder.objects.get(pk=po_id)
                invoice.save(update_fields=['po', 'updated_at'])
            except PurchaseOrder.DoesNotExist:
                return Response({'detail': 'أمر الشراء غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if not invoice.po_id:
            return Response({'detail': 'لا يوجد أمر شراء مرتبط', 'linked': False}, status=status.HTTP_200_OK)
        return Response(po_mod.match_invoice_to_po(invoice, invoice.po))

    @action(detail=True, methods=['post', 'get'])
    def validate(self, request, pk=None):
        """Run the SofTech save-time validations (credit limit, item allowed, price caps,
        expiry required, …) and return {ok, errors[], warnings[]}. Read-only."""
        from . import validations, suppliers
        invoice = self.get_object()
        suppliers.ensure_invoice_vendor(invoice)
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
        from . import suppliers
        suppliers.ensure_invoice_vendor(invoice)
        # Fast duplicate guard (our module): same vendor + printed number already
        # posted here. SOFTECH double-posting is prevented by the writer's own
        # idempotent dn2 guard. force=true overrides.
        if not force and invoice.vendor_id and (invoice.invoice_number or '').strip():
            if (SupplierInvoice.objects
                    .filter(vendor_id=invoice.vendor_id, invoice_number=invoice.invoice_number)
                    .exclude(pk=invoice.pk)
                    .filter(status__in=['queued', 'pushing', 'finalized']).exists()):
                return Response({'detail': 'فاتورة بنفس المورد ورقم الفاتورة مُرحَّلة بالفعل من هذا النظام — أكِّد للمتابعة.',
                                 'duplicate': True}, status=status.HTTP_409_CONFLICT)
        try:
            result = writer.push_final(invoice, dry_run=False, force=force)
            _audit_invoice_push(request, invoice, result, force)
        except writer.WriterDisabled as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'فشل الترحيل: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    @action(detail=False, methods=['post'], url_path='push-batch')
    def push_batch(self, request):
        """Post several confirmed invoices to SOFTECH in one call — revise each in the
        grid, then push the group together. Each invoice keeps its own dup-guard
        (supplier + doccode + docnumber2) and `client_token` idempotency, so a retry
        NEVER double-posts; one invoice failing does not block the others. Gated by
        INVOICE_WRITER_ENABLED; requires a privileged role."""
        from . import writer
        if not self._can_push(request):
            return Response({'detail': 'غير مصرح بترحيل الفواتير إلى ERP'},
                            status=status.HTTP_403_FORBIDDEN)
        ids = request.data.get('invoice_ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'لم يتم تحديد فواتير'}, status=status.HTTP_400_BAD_REQUEST)
        force = str(request.data.get('force', '')).lower() in ('1', 'true', 'yes')
        found = {inv.pk: inv for inv in SupplierInvoice.objects.filter(pk__in=ids)}

        def _slim(r):
            return {k: r[k] for k in ('mode', 'docnumber', 'status', 'dry_run', 'detail',
                                      'blocked', 'validation', 'committed', 'wrote_to_softech')
                    if isinstance(r, dict) and k in r}

        results = []
        for iid in ids:                              # preserve the caller's order
            inv = found.get(iid)
            if inv is None:
                results.append({'id': iid, 'ok': False, 'error': 'الفاتورة غير موجودة'}); continue
            if inv.status not in ('confirmed', 'queued', 'push_failed'):
                results.append({'id': iid, 'ok': False, 'skipped': True, 'status': inv.status,
                                'error': 'يجب تأكيد الفاتورة قبل الترحيل'}); continue
            try:
                r = writer.push_final(inv, dry_run=False, force=force)
                _audit_invoice_push(request, inv, r, force)
                results.append({'id': iid, 'ok': bool(r.get('ok', True)),
                                'supplier': inv.supplier_name, **_slim(r)})
            except writer.WriterDisabled as e:
                results.append({'id': iid, 'ok': False, 'disabled': True, 'error': str(e)})
            except ValueError as e:
                results.append({'id': iid, 'ok': False, 'error': str(e)})
            except Exception as e:
                results.append({'id': iid, 'ok': False, 'error': public_error(request, e)})
        ok = sum(1 for r in results if r.get('ok'))
        return Response({'total': len(ids), 'succeeded': ok, 'failed': len(ids) - ok,
                         'results': results})

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
            return Response({'detail': f'تعذّر التحقق: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
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
            return Response({'detail': f'فشل الاختبار: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    # ── Update invoice header ─────────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path='update-header')
    def update_header(self, request, pk=None):
        from . import suppliers
        invoice = self.get_object()
        fields  = ['supplier_name', 'invoice_number', 'invoice_date', 'currency',
                   'global_discount_pct', 'global_discount_amt', 'notes']
        old_name = invoice.supplier_name
        for field in fields:
            if field in request.data:
                setattr(invoice, field, request.data[field])
        if 'vendor' in request.data:
            vid = request.data.get('vendor') or None
            if vid and not VendorProfile.objects.filter(pk=vid).exists():
                return Response({'detail': 'المورد غير موجود'}, status=status.HTTP_400_BAD_REQUEST)
            invoice.vendor_id = vid
        invoice.save()
        # A corrected supplier name re-links an unlinked (or name-only) vendor.
        if invoice.supplier_name != old_name and not (invoice.vendor and invoice.vendor.softech_personcode):
            suppliers.ensure_invoice_vendor(invoice)
        return Response(SupplierInvoiceDetailSerializer(
            self.get_queryset().get(pk=invoice.pk),
            context=self.get_serializer_context()
        ).data)


    # ── Link the invoice to a SOFTECH supplier by hand ────────────────────────

    @action(detail=True, methods=['post'], url_path='link-vendor')
    def link_vendor(self, request, pk=None):
        """Attach a SOFTECH-coded supplier when auto-resolution missed it (E7
        supplier_unlinked). Body: {vendor: <VendorProfile id>} or {personcode, name}.
        The invoice's supplier name is learned as an alias, so the next invoice
        from this supplier links itself."""
        from . import suppliers
        invoice = self.get_object()
        if invoice.status in ('pushing', 'finalized'):
            return Response({'detail': 'لا يمكن تغيير مورد فاتورة مُرحّلة'},
                            status=status.HTTP_400_BAD_REQUEST)
        vid = request.data.get('vendor')
        pc  = str(request.data.get('personcode') or '').strip()
        if vid:
            vp = VendorProfile.objects.filter(pk=vid).first()
            if not vp or not vp.softech_personcode:
                return Response({'detail': 'المورد المختار ليس له كود SOFTECH'},
                                status=status.HTTP_400_BAD_REQUEST)
            suppliers.learn_alias(vp, invoice.supplier_name or '')
        elif pc:
            if not pc.isdigit() or len(pc) > 8:
                return Response({'detail': 'كود المورد غير صالح'}, status=status.HTTP_400_BAD_REQUEST)
            name = str(request.data.get('name') or '').strip()[:200]
            if not name and pc in suppliers.TOP_SUPPLIERS:
                name = suppliers.TOP_SUPPLIERS[pc][0]
            vp = suppliers.get_or_create_vendor(pc, name, alias=invoice.supplier_name or '')
        else:
            return Response({'detail': 'اختر المورد'}, status=status.HTTP_400_BAD_REQUEST)
        invoice.vendor = vp
        invoice.save(update_fields=['vendor', 'updated_at'])
        return Response(SupplierInvoiceDetailSerializer(
            self.get_queryset().get(pk=invoice.pk),
            context=self.get_serializer_context()
        ).data)


# ── Vendor Profile ViewSet ────────────────────────────────────────────────────

class VendorProfileViewSet(viewsets.ModelViewSet):
    queryset           = VendorProfile.objects.all().order_by('name')
    serializer_class   = VendorProfileSerializer
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module        = 'invoices'
    # vendor lookups are read by other screens (e.g. the shortage page)
    rbac_actions       = {'list': (), 'retrieve': (), 'main': ()}

    def get_queryset(self):
        qs = super().get_queryset()
        q  = self.request.query_params.get('q')
        if q:
            qs = qs.filter(wq(q, 'name'))
        if self.request.query_params.get('main') in ('1', 'true'):
            qs = qs.filter(is_main=True)
        return qs

    @action(detail=False, methods=['get'])
    def linkable(self, request):
        """Suppliers an invoice can be linked to: coded VendorProfiles + curated
        top distributors not yet profiled. [{vendor_id, personcode, name, is_main}]."""
        from .suppliers import linkable_suppliers
        return Response(linkable_suppliers())

    @action(detail=False, methods=['get'])
    def main(self, request):
        """The official/main distributors (is_main) — drives the supplier-PO picker
        and the matrix columns. [{personcode, name}]."""
        rows = (VendorProfile.objects.filter(is_main=True)
                .exclude(softech_personcode='').order_by('name')
                .values('softech_personcode', 'name'))
        return Response([{'personcode': r['softech_personcode'], 'name': r['name']} for r in rows])


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """Purchase orders for the advisory goods-received check (separate workflow,
    never gates posting). Low-traffic CRUD + nested lines."""
    serializer_class   = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module = 'invoices'

    def get_queryset(self):
        qs = PurchaseOrder.objects.select_related('branch', 'vendor').prefetch_related('lines')
        branch = self.request.query_params.get('branch')
        vendor = self.request.query_params.get('vendor')
        status_q = self.request.query_params.get('status')
        if branch:
            qs = qs.filter(branch_id=branch)
        if vendor:
            qs = qs.filter(vendor_id=vendor)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=getattr(self.request.user, 'staff_profile', None))


class InvoiceBatchViewSet(viewsets.ModelViewSet):
    """
    Multi-invoice PDF bundles: upload one distributor PDF → it is rendered, split
    into the separate invoices it contains, and each becomes a SupplierInvoice in
    the normal review queue. The split is advisory and fully auditable
    (split_summary); the operator reviews/confirms every invoice before posting.
    """
    permission_classes = [IsAuthenticated, MatrixPermission]
    rbac_module = 'invoices'
    rbac_actions = {'reprocess': ('edit',)}
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = InvoiceBatch.objects.select_related('branch', 'vendor', 'created_by').annotate(
            invoice_count=Count('invoices'),
        )
        branch   = self.request.query_params.get('branch')
        status_q = self.request.query_params.get('status')
        if branch:
            qs = qs.filter(branch_id=branch)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceBatchCreateSerializer
        if self.action == 'retrieve':
            return InvoiceBatchDetailSerializer
        return InvoiceBatchListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        batch = serializer.save(created_by=profile)
        if batch.source_file:
            from . import ingest
            ingest.start_async(batch)

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """Re-render, re-split and re-fan-out. Removes previously fanned-out
        invoices that are still in review (never ones already queued/posted)."""
        batch = self.get_object()
        locked = batch.invoices.filter(status__in=['queued', 'pushing', 'finalized']).exists()
        if locked:
            return Response({'detail': 'لا يمكن إعادة التقسيم — بعض الفواتير قيد الترحيل أو مُرحَّلة.'},
                            status=status.HTTP_400_BAD_REQUEST)
        batch.invoices.all().delete()
        batch.status = 'processing'
        batch.error = ''
        batch.save(update_fields=['status', 'error'])
        from . import ingest
        ingest.start_async(batch)
        return Response({'detail': 'جارٍ إعادة التقسيم والمعالجة', 'status': 'processing'})
