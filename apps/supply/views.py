"""
apps/supply/views.py — Phase 2 Availability Inbox API (supplier PUSH).

Endpoints (all reuse the shared pipeline — no parallel matching/OCR logic):
  POST   /api/supply/availability/                      create batch (paste/manual) + ingest
  GET    /api/supply/availability/                      list
  GET    /api/supply/availability/{id}/                 detail (+lines)
  POST   /api/supply/availability/check-duplicate/      fingerprint duplicate probe (§32)
  POST   /api/supply/availability/{id}/ocr/             screenshot → OCR → lines
  POST   /api/supply/availability/{id}/import-file/     Excel/CSV → lines
  POST   /api/supply/availability/{id}/add-line/        add one raw line
  GET    /api/supply/availability/{id}/lines/{lid}/matches/   top-N catalog matches
  PATCH  /api/supply/availability/{id}/lines/{lid}/     update / confirm a line (+learn)
  DELETE /api/supply/availability/{id}/lines/{lid}/delete/
  POST   /api/supply/availability/{id}/scope/           {branch_ids: [..]} ([] = all branches)
  POST   /api/supply/availability/{id}/lock/            finalize (no edits until unlocked)
  POST   /api/supply/availability/{id}/unlock/          {reason} — required, audited
  GET    /api/supply/availability/{id}/history/         full audit trail of the list
  GET    /api/supply/freshness/                         when sales rates / stock / items were synced
  POST   /api/supply/freshness/sync-stock/              refresh stock + sales from SOFTECH now
"""
import logging

from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import AvailabilityBatch, AvailabilityLine, SupplyCase, SupplyDecision
from .serializers import (
    AvailabilityBatchSerializer, AvailabilityBatchDetailSerializer,
    AvailabilityBatchCreateSerializer, AvailabilityLineSerializer,
    AvailabilityLineUpdateSerializer, SupplyCaseSerializer, SupplyDecisionSerializer,
)
from . import availability as av
from . import cases as case_svc
from . import execution as exe
from .permissions import CanOperateSupply
from core.errors import public_error

logger = logging.getLogger('elrezeiky.supply')


def _vendor_code(batch) -> str:
    """The batch supplier's SOFTECH personcode — scopes matching + alias learning (§29)."""
    if batch.supplier_id and batch.supplier:
        return batch.supplier.softech_personcode or ''
    return ''


LOCKED_MSG = 'القائمة مُقفلة (نهائية) — افتحها أولاً لتعديلها.'


def _locked(batch):
    """A 423 response when the list is finalized, else None. Every write path checks it —
    the frontend greying out buttons is never the guard (CLAUDE.md rule 9)."""
    if batch.is_locked:
        return Response({'detail': LOCKED_MSG, 'locked': True}, status=status.HTTP_423_LOCKED)
    return None


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _audit(request, batch, event: str, *, changes=None, extra=None, note='',
           action='supply_availability_edited'):
    """One audit row per decision on a list — who / what / when / why / before → after."""
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=_staff(request), obj=batch, changes=changes or None,
                 extra={'event': event, **(extra or {})}, note=note[:255], request=request)


def _line_state(line) -> dict:
    return {'item_id': line.item_id, 'item': line.item.name if line.item_id else '',
            'confirmed': line.is_confirmed,
            'qty': str(line.supplier_qty) if line.supplier_qty is not None else None,
            'price': str(line.price) if line.price is not None else None,
            'foc': str(line.foc_qty) if line.foc_qty is not None else None,
            'discount': str(line.discount_pct) if line.discount_pct is not None else None,
            'expiry': line.expiry, 'code': line.supplier_item_code}


def _diff(before: dict, after: dict) -> dict:
    return {k: [before.get(k), after.get(k)] for k in after if before.get(k) != after.get(k)}


class AvailabilityBatchViewSet(viewsets.ModelViewSet):
    # Server-side RBAC (purchasing/view for reads, purchasing/edit for writes).
    permission_classes = [IsAuthenticated, CanOperateSupply]

    def get_queryset(self):
        qs = AvailabilityBatch.objects.select_related('supplier', 'operator__user').annotate(
            line_count=Count('lines', distinct=True),
            matched_count=Count('lines', filter=Q(lines__item__isnull=False), distinct=True),
            confirmed_count=Count('lines', filter=Q(lines__is_confirmed=True), distinct=True),
        )
        supplier = self.request.query_params.get('supplier')
        status_q = self.request.query_params.get('status')
        if supplier:
            qs = qs.filter(supplier_id=supplier)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return AvailabilityBatchCreateSerializer
        if self.action == 'retrieve':
            return AvailabilityBatchDetailSerializer
        return AvailabilityBatchSerializer

    # ── Create (paste / manual) + ingest ──────────────────────────────────────
    def create(self, request, *args, **kwargs):
        ser = AvailabilityBatchCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        raw_content = data.get('raw_content', '')
        fingerprint = av.compute_fingerprint(raw_content)

        # Resolve the supplier (explicit FK wins, else resolve the raw name).
        supplier = data.get('supplier')
        supplier_name = data.get('supplier_name', '')
        resolution = None
        if supplier is None and not supplier_name and raw_content:
            # A pasted WhatsApp chat names its sender — use it as the supplier hint (§2).
            supplier_name = av.detect_sender(raw_content)
        if supplier is None and supplier_name:
            supplier, resolution = av.resolve_batch_supplier(supplier_name)

        # Duplicate-import WARNING (never blocks — §32).
        dup = av.find_duplicate_batch(fingerprint, supplier_id=(supplier.id if supplier else None))

        profile = getattr(request.user, 'staff_profile', None)
        batch = AvailabilityBatch.objects.create(
            supplier=supplier, supplier_name=supplier_name or (supplier.name if supplier else ''),
            source=data.get('source', AvailabilityBatch.SOURCE_WHATSAPP),
            raw_content=raw_content, raw_fingerprint=fingerprint,
            operator=profile, notes=data.get('notes', ''),
        )

        lines = []
        if raw_content:
            lines = av.ingest_batch(batch, raw_content, source='bulk',
                                    vendor_code=_vendor_code(batch))

        _audit(request, batch, 'created', extra={'lines': len(lines), 'source': batch.source,
                                                  'duplicate_of': dup.id if dup else None})
        out = AvailabilityBatchDetailSerializer(batch).data
        out['duplicate_of'] = dup.id if dup else None
        out['supplier_resolution'] = resolution
        return Response(out, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):   # not used (create overridden) — safety
        serializer.save()

    def update(self, request, *args, **kwargs):
        blocked = _locked(self.get_object())
        return blocked or super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        blocked = _locked(self.get_object())
        return blocked or super().destroy(request, *args, **kwargs)

    # ── Duplicate probe (before creating) ─────────────────────────────────────
    @action(detail=False, methods=['post'], url_path='check-duplicate')
    def check_duplicate(self, request):
        fp = av.compute_fingerprint(request.data.get('raw_content', ''))
        dup = av.find_duplicate_batch(fp, supplier_id=request.data.get('supplier'))
        return Response({'fingerprint': fp, 'duplicate_of': dup.id if dup else None,
                         'duplicate_at': dup.created_at if dup else None})

    # ── OCR a screenshot → lines ──────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='ocr')
    def ocr(self, request, pk=None):
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        if 'image' not in request.FILES:
            return Response({'detail': 'لم يتم رفع صورة'}, status=status.HTTP_400_BAD_REQUEST)

        from django.conf import settings as dj_settings
        from apps.vision.ocr import run_engines, pick_primary
        gemini_key = getattr(dj_settings, 'GEMINI_API_KEY', '') or ''
        engine_readings = run_engines(request.FILES['image'], api_key=gemini_key)
        engine, primary = pick_primary(engine_readings)
        if not primary:
            return Response({'detail': 'تعذّر استخراج نص من الصورة'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        vc = _vendor_code(batch)
        created = []
        for r in primary:
            raw = ((r.get('readings') or [''])[0] + ' ' + (r.get('strength') or '')).strip()
            if r.get('qty'):
                raw = f'{raw} {r["qty"]}'
            if raw:
                line = av.build_line(batch, raw, source='ocr', vendor_code=vc)
                if line is not None:
                    created.append(line)
        _audit(request, batch, 'ocr_import', extra={'lines': len(created), 'engine': engine})
        return Response({'engine': engine, 'created': len(created),
                         'lines': AvailabilityLineSerializer(created, many=True).data})

    # ── Import Excel / CSV → lines ────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='import-file')
    def import_file(self, request, pk=None):
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        f = request.FILES.get('file')
        if not f:
            return Response({'detail': 'لم يتم رفع ملف'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rows = _read_tabular(f)
        except Exception as exc:
            logger.warning('availability import-file parse failed: %s', exc)
            return Response({'detail': f'تعذّر قراءة الملف: {public_error(request, exc)}'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Column layout (apps/supply/file_layouts): a layout confirmed before for this supplier
        # + header row imports straight away; a new one is SUGGESTED for a person to confirm
        # once (mapping posted back) and then remembered.
        import json
        from . import file_layouts as fl
        vc = _vendor_code(batch)
        rows = [list(r) for r in rows if any(c not in (None, '') for c in r)]
        ncols = max((len(r) for r in rows), default=0)
        mapping_raw = request.data.get('mapping')
        layout_info = None
        if mapping_raw:
            try:
                mapping = fl.clean_mapping(json.loads(mapping_raw) if isinstance(mapping_raw, str)
                                           else mapping_raw, ncols)
                hr = request.data.get('header_row')
                header_row = int(hr) if str(hr).isdigit() else None
            except (ValueError, TypeError) as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            created = fl.import_rows(batch, rows, header_row=header_row, mapping=mapping, vendor_code=vc)
            if header_row is not None and str(request.data.get('remember', '1')) != '0':
                headers = rows[header_row]
                lay = fl.remember(batch, sig=fl.signature(headers), headers=[fl._txt(h) for h in headers],
                                  header_row=header_row, mapping=mapping, staff=_staff(request))
                layout_info = {'id': lay.id, 'remembered': False, 'saved': True} if lay else None
        else:
            header_row = fl.detect_header(rows)
            lay = fl.find_layout(batch, fl.signature(rows[header_row])) if header_row is not None else None
            if header_row is not None and lay is None:
                headers = rows[header_row]
                sig = fl.signature(headers)
                return Response({
                    'needs_mapping': True, 'header_row': header_row,
                    'columns': [{'index': i, 'header': fl._txt(headers[i]) if i < len(headers) else '',
                                 'samples': [fl._txt(r[i]) if i < len(r) else '' for r in rows[header_row + 1:header_row + 5]]}
                                for i in range(ncols)],
                    'suggested': fl.suggested_from_others(sig) or fl.suggest(headers),
                    'roles': fl.ROLE_LABELS,
                })
            if lay is not None:
                created = fl.import_rows(batch, rows, header_row=header_row, mapping=lay.mapping, vendor_code=vc)
                lay.use_count += 1
                lay.save(update_fields=['use_count', 'updated_at'])
                layout_info = {'id': lay.id, 'remembered': True}
            else:
                # no header row at all (a plain pasted list in a sheet) → one line per row, as text
                created = []
                for row in rows:
                    raw = ' '.join(str(c).strip() for c in row if c is not None and str(c).strip())
                    if raw:
                        line = av.build_line(batch, raw, source='file', vendor_code=vc)
                        if line is not None:          # notes / totals are not products
                            created.append(line)
        _audit(request, batch, 'file_import', extra={'lines': len(created), 'file': f.name[:120],
                                                     'layout': layout_info})
        return Response({'created': len(created), 'layout': layout_info,
                         'lines': AvailabilityLineSerializer(created, many=True).data})

    @action(detail=False, methods=['post'], url_path=r'layouts/(?P<lid>\d+)/forget')
    def forget_layout(self, request, lid=None):
        """Forget a supplier's remembered column layout — the next file asks again."""
        from .models import SupplierFileLayout
        n, _ = SupplierFileLayout.objects.filter(pk=lid).delete()
        logger.info('[supply] file layout %s forgotten by %s', lid, request.user.username)
        return Response({'deleted': bool(n)})

    # ── Review-grid analysis (Phase 6) ────────────────────────────────────────
    @action(detail=True, methods=['get'])
    def analysis(self, request, pk=None):
        """Per-line need / stock / internal cover / residual / effective cost / flags."""
        raw = request.query_params.get('branches')
        ids = [int(b) for b in raw.split(',') if b.strip().isdigit()] if raw is not None else None
        return Response(av.analyze_batch(self.get_object(), branch_ids=ids))

    @action(detail=True, methods=['post'], url_path='confirm-matches')
    def confirm_matches(self, request, pk=None):
        """Bulk confirm: {line_ids?: [...]} — omitted = all high-confidence auto-matches."""
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        done = av.confirm_matches(batch, line_ids=request.data.get('line_ids'),
                                  staff=getattr(request.user, 'staff_profile', None))
        if done:
            _audit(request, batch, 'bulk_confirm',
                   extra={'line_ids': [d.pk for d in done], 'count': len(done),
                          'mode': 'selected' if request.data.get('line_ids') is not None else 'obvious'})
        return Response({'confirmed': len(done),
                         'lines': AvailabilityLineSerializer(done, many=True).data})

    # ── Add one raw line ──────────────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='add-line')
    def add_line(self, request, pk=None):
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        raw = (request.data.get('raw_text') or '').strip()
        if not raw:
            return Response({'detail': 'النص فارغ'}, status=status.HTTP_400_BAD_REQUEST)
        line = av.build_line(batch, raw, source='manual', vendor_code=_vendor_code(batch))
        if line is None:
            return Response({'detail': 'هذا السطر لا يبدو صنفاً'}, status=status.HTTP_400_BAD_REQUEST)
        _audit(request, batch, 'line_added', extra={'line_id': line.pk, 'raw_text': raw[:200]})
        return Response(AvailabilityLineSerializer(line).data, status=status.HTTP_201_CREATED)

    # ── Top-N catalog matches for a line ──────────────────────────────────────
    @action(detail=True, methods=['get'], url_path=r'lines/(?P<lid>\d+)/matches')
    def line_matches(self, request, pk=None, lid=None):
        batch = self.get_object()
        try:
            line = batch.lines.get(pk=lid)
        except AvailabilityLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        from apps.shortage.matching import find_best_matches
        top_n = min(int(request.query_params.get('top', 8)), 20)
        name = (line.match_reason or {}).get('name_part') or line.raw_text
        vc = _vendor_code(batch)
        matches = find_best_matches(name, top_n=top_n, min_score=0.15, vendor_code=vc)
        # items this supplier actually carries (itemssuppliers mirror) are marked, and win a
        # near-tie (within 0.05) — the score itself is never changed
        from apps.catalog.supplier_links import carried_item_ids
        carried = carried_item_ids(vc, [m['item_id'] for m in matches])
        for m in matches:
            m['carried'] = m['item_id'] in carried
        matches.sort(key=lambda m: -(m['score'] + (0.05 if m['carried'] else 0)))
        return Response(matches)

    # ── Update / confirm a line (+ learn vendor-scoped alias) ─────────────────
    @action(detail=True, methods=['patch'], url_path=r'lines/(?P<lid>\d+)')
    def update_line(self, request, pk=None, lid=None):
        batch = self.get_object()
        try:
            line = batch.lines.get(pk=lid)
        except AvailabilityLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if (blocked := _locked(batch)):
            return blocked
        before = _line_state(line)

        ser = AvailabilityLineUpdateSerializer(line, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        line = ser.save()

        # Confirm + teach the corpus when an item is set and confirmation requested.
        if line.item_id and request.data.get('is_confirmed') and not line.confirmed_at:
            profile = getattr(request.user, 'staff_profile', None)
            av.confirm_line(line, line.item, staff=profile, vendor_code=_vendor_code(batch))
        changes = _diff(before, _line_state(line))
        if changes:
            _audit(request, batch, 'line_updated', changes=changes,
                   extra={'line_id': line.pk, 'raw_text': line.raw_text[:200]})
        data = AvailabilityLineSerializer(line).data
        data['rows'] = av.analyze_rows(batch, [line.pk])    # this line's review row only
        return Response(data)

    # ── Match a line to one or SEVERAL items (splits it into sibling lines) ────
    @action(detail=True, methods=['post'], url_path=r'lines/(?P<lid>\d+)/items')
    def line_items(self, request, pk=None, lid=None):
        """{item_ids: [..]} — the full list of items this supplier line offers. One id = a
        normal confirmed match; several = the line is split (one sibling per extra item, same
        text + economics); [] = un-match. Body is the whole list, so it is idempotent."""
        batch = self.get_object()
        try:
            line = batch.lines.get(pk=lid)
        except AvailabilityLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if (blocked := _locked(batch)):
            return blocked
        head = line.split_from or line
        before = [head.item_id] + list(head.siblings.order_by('id').values_list('item_id', flat=True))
        raw = request.data.get('item_ids')
        if not isinstance(raw, list) or not all(str(i).isdigit() for i in raw):
            return Response({'detail': 'item_ids يجب أن تكون قائمة أرقام'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            group = av.set_line_items(line, raw, staff=getattr(request.user, 'staff_profile', None),
                                      vendor_code=_vendor_code(batch))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        after = [g.item_id for g in group]
        if [b for b in before if b] != [a for a in after if a]:
            _audit(request, batch, 'line_items', changes={'items': [before, after]},
                   extra={'line_id': group[0].pk, 'raw_text': group[0].raw_text[:200]})
        # only this group's review rows — the screen swaps them in place (no full re-analysis)
        return Response({'group_id': group[0].pk,
                         'lines': AvailabilityLineSerializer(group, many=True).data,
                         'rows': av.analyze_rows(batch, [g.pk for g in group])})

    # ── Delete a line ─────────────────────────────────────────────────────────
    @action(detail=True, methods=['delete'], url_path=r'lines/(?P<lid>\d+)/delete')
    def delete_line(self, request, pk=None, lid=None):
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        line = batch.lines.select_related('item').filter(pk=lid).first()
        if line is not None:
            _audit(request, batch, 'line_deleted', changes={'line': [_line_state(line), None]},
                   extra={'line_id': line.pk, 'raw_text': line.raw_text[:200]})
            line.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Branch scope: which branches this offer serves ([] = all, the default) ──
    @action(detail=True, methods=['post'])
    def scope(self, request, pk=None):
        batch = self.get_object()
        if (blocked := _locked(batch)):
            return blocked
        raw = request.data.get('branch_ids')
        if not isinstance(raw, list) or not all(str(b).isdigit() for b in raw):
            return Response({'detail': 'branch_ids يجب أن تكون قائمة أرقام'}, status=status.HTTP_400_BAD_REQUEST)
        new = sorted({int(b) for b in raw})
        info = av.scope_info(batch, new)
        if len(info['branch_ids']) != len(new):
            return Response({'detail': 'فرع غير موجود.'}, status=status.HTTP_400_BAD_REQUEST)
        old = list(batch.branch_scope or [])
        if old != new:
            batch.branch_scope = new
            batch.save(update_fields=['branch_scope', 'updated_at'])
            _audit(request, batch, 'scope_changed', changes={'branch_scope': [old, new]})
        return Response(info)

    # ── Finalize / unlock (audited) ──────────────────────────────────────────
    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        from django.utils import timezone
        batch = self.get_object()
        if batch.is_locked:
            return Response({'detail': 'القائمة مقفلة بالفعل.'}, status=status.HTTP_409_CONFLICT)
        note = str(request.data.get('note') or '').strip()[:255]
        batch.locked_at, batch.locked_by, batch.lock_note = timezone.now(), _staff(request), note
        batch.save(update_fields=['locked_at', 'locked_by', 'lock_note', 'updated_at'])
        summary = batch.lines.aggregate(n=Count('id'), confirmed=Count('id', filter=Q(is_confirmed=True)))
        _audit(request, batch, 'locked', action='supply_availability_locked', note=note,
               extra={'lines': summary['n'], 'confirmed': summary['confirmed'],
                      'branch_scope': batch.branch_scope or []})
        return Response(AvailabilityBatchSerializer(self.get_queryset().get(pk=batch.pk)).data)

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        batch = self.get_object()
        if not batch.is_locked:
            return Response({'detail': 'القائمة غير مقفلة.'}, status=status.HTTP_409_CONFLICT)
        reason = str(request.data.get('reason') or '').strip()
        if len(reason) < 3:
            return Response({'detail': 'اكتب سبب فتح القائمة (يُحفظ في السجل).'},
                            status=status.HTTP_400_BAD_REQUEST)
        was = {'locked_at': batch.locked_at.isoformat(),
               'locked_by': getattr(batch.locked_by, 'full_name', '') if batch.locked_by_id else ''}
        batch.locked_at = batch.locked_by = None
        batch.lock_note = ''
        batch.save(update_fields=['locked_at', 'locked_by', 'lock_note', 'updated_at'])
        _audit(request, batch, 'unlocked', action='supply_availability_unlocked', note=reason,
               extra={'was': was})
        return Response(AvailabilityBatchSerializer(self.get_queryset().get(pk=batch.pk)).data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        from apps.audit.models import AuditLog
        batch = self.get_object()
        rows = (AuditLog.objects.filter(model_name='AvailabilityBatch', object_id=str(batch.pk))
                .order_by('-created_at')[:500])
        return Response([{
            'id': r.id, 'at': r.created_at, 'action': r.action, 'label': r.get_action_display(),
            'event': (r.extra or {}).get('event', ''), 'user': r.user_name or 'النظام',
            'changes': r.changes or {}, 'extra': r.extra or {}, 'note': r.note,
        } for r in rows])


# ── Tabular file reader (Excel via openpyxl, CSV via stdlib) ───────────────────

def _read_tabular(f) -> list:
    """Yield rows (lists of cell values) from an uploaded .xlsx/.xls or .csv file."""
    name = (f.name or '').lower()
    if name.endswith('.csv'):
        import csv, io
        text = f.read().decode('utf-8-sig', errors='replace')
        return [row for row in csv.reader(io.StringIO(text))]
    # Excel
    import openpyxl
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Supply cases: the daily follow-up queue.
#   GET  /api/supply/cases/?bucket=urgent|zero_stock|customer_waiting|availability_found|
#                              awaiting_decision|transfer_pending|ordered|
#                              partially_fulfilled|searching|overdue  [&branch=ID]
#   GET  /api/supply/cases/summary/            bucket counts (queue badges)
#   GET  /api/supply/cases/{id}/               case snapshot + allowed transitions
#   GET  /api/supply/cases/{id}/recommendation/  live re-computed recommendation
#   POST /api/supply/cases/{id}/transition/    {status, reason}
#   POST /api/supply/cases/{id}/evaluate/      re-evaluate now
#   POST /api/supply/cases/{id}/assign/        {staff_id}
#   POST /api/supply/cases/sweep/              run the daily sweep now
# ═══════════════════════════════════════════════════════════════════════════════

class SupplyCaseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, CanOperateSupply]
    serializer_class = SupplyCaseSerializer

    def get_queryset(self):
        if self.action in ('list', 'summary'):
            bucket = self.request.query_params.get('bucket') or None
            branch = self.request.query_params.get('branch') or None
            if self.request.query_params.get('include_closed') == '1':
                qs = SupplyCase.objects.select_related('item', 'branch', 'assigned_to__user')
                return qs.filter(branch_id=branch) if branch else qs
            return case_svc.open_queue(bucket=bucket, branch_id=branch)
        return SupplyCase.objects.select_related('item', 'branch', 'assigned_to__user')

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except ValueError as exc:            # unknown bucket
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        branch = request.query_params.get('branch') or None
        return Response(case_svc.queue_summary(branch_id=branch))

    @action(detail=True, methods=['get'])
    def recommendation(self, request, pk=None):
        from .engine import recommend
        case = self.get_object()
        offers = case_svc.matching_availability(case.item_id)
        rec = recommend(case.item_id, branch_id=case.branch_id, availability_lines=offers)
        return Response(rec)

    @action(detail=True, methods=['post'])
    def transition(self, request, pk=None):
        case = self.get_object()
        new_status = (request.data.get('status') or '').strip()
        reason = request.data.get('reason', '')
        try:
            case = case_svc.transition(case, new_status,
                                       staff=getattr(request.user, 'staff_profile', None),
                                       reason=reason, request=request)
        except case_svc.CaseTransitionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SupplyCaseSerializer(case).data)

    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        case = self.get_object()
        r = case_svc.evaluate_case(case.item_id, case.branch_id)
        fresh = r['case'] or case
        fresh.refresh_from_db()
        return Response({'event': r['event'], 'case': SupplyCaseSerializer(fresh).data})

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        from apps.users.models import StaffProfile
        case = self.get_object()
        staff_id = request.data.get('staff_id')
        assignee = None
        if staff_id:
            try:
                assignee = StaffProfile.objects.get(pk=staff_id, is_active=True)
            except (StaffProfile.DoesNotExist, ValueError, TypeError):
                return Response({'detail': 'الموظف غير موجود'}, status=status.HTTP_400_BAD_REQUEST)
        case = case_svc.assign(case, assignee,
                               staff=getattr(request.user, 'staff_profile', None), request=request)
        return Response(SupplyCaseSerializer(case).data)

    @action(detail=False, methods=['post'])
    def sweep(self, request):
        counts = case_svc.sweep_cases()
        return Response(counts)

    @action(detail=True, methods=['post'], url_path='approve-transfer')
    def approve_transfer(self, request, pk=None):
        """Approve the internal allocation → DRAFT TransferRequest(s) for the transfers team.
        Body: {idempotency_key, transfers?: [{from_branch_id, qty}], reason?}"""
        case = self.get_object()
        try:
            res = exe.approve_internal_transfer(
                case, idempotency_key=request.data.get('idempotency_key', ''),
                staff=getattr(request.user, 'staff_profile', None),
                transfers=request.data.get('transfers'),
                reason=request.data.get('reason', ''), request=request)
        except exe.ExecutionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        case.refresh_from_db()
        return Response({
            'replayed': res['replayed'],
            'decision': SupplyDecisionSerializer(res['decision']).data,
            'transfer_requests': [{'id': t.pk, 'request_number': t.request_number,
                                   'supplying_branch': t.supplying_branch_id,
                                   'status': t.status} for t in res['transfer_requests']],
            'case': SupplyCaseSerializer(case).data,
        }, status=status.HTTP_200_OK if res['replayed'] else status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Order list (WhatsApp / Excel) + decision log.
#   POST /api/supply/order-list/preview/   {lines, lang}             → text + need check
#   POST /api/supply/order-list/commit/    {lines, idempotency_key, supplier?, supplier_name?, lang}
#   POST /api/supply/order-list/excel/     {lines, supplier_name}    → .xlsx
#   GET  /api/supply/decisions/?case=&kind=&order_ref=
# Each line: {item_id | availability_line_id, qty, branch_id?, case_id?, reason?}
# ═══════════════════════════════════════════════════════════════════════════════

class OrderListViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, CanOperateSupply]

    @action(detail=False, methods=['post'])
    def preview(self, request):
        try:
            return Response(exe.preview_order(request.data.get('lines') or [],
                                              lang=request.data.get('lang', 'ar')))
        except exe.ExecutionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def commit(self, request):
        from apps.invoices.models import VendorProfile
        supplier = None
        if request.data.get('supplier'):
            supplier = VendorProfile.objects.filter(pk=request.data['supplier']).first()
        try:
            res = exe.commit_order(
                request.data.get('lines') or [],
                idempotency_key=request.data.get('idempotency_key', ''),
                supplier=supplier, supplier_name=request.data.get('supplier_name', ''),
                staff=getattr(request.user, 'staff_profile', None),
                lang=request.data.get('lang', 'ar'), request=request)
        except exe.ExecutionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({
            'order_ref': res['order_ref'], 'replayed': res['replayed'], 'text': res['text'],
            'decisions': SupplyDecisionSerializer(res['decisions'], many=True).data,
        }, status=status.HTTP_200_OK if res['replayed'] else status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def excel(self, request):
        from django.http import HttpResponse
        try:
            content = exe.export_order_excel(request.data.get('lines') or [],
                                             supplier_name=request.data.get('supplier_name', ''))
        except exe.ExecutionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        resp = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="supply_order.xlsx"'
        return resp


class SupplyDecisionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, CanOperateSupply]
    serializer_class = SupplyDecisionSerializer

    def get_queryset(self):
        qs = SupplyDecision.objects.select_related('item', 'created_by__user')
        p = self.request.query_params
        if p.get('case'):
            qs = qs.filter(case_id=p['case'])
        if p.get('kind'):
            qs = qs.filter(kind=p['kind'])
        if p.get('order_ref'):
            qs = qs.filter(order_ref=p['order_ref'])
        return qs.order_by('-created_at')


# ═══════════════════════════════════════════════════════════════════════════════
# Data freshness — the numbers on the supply screens are only as good as the last sync.
#   GET  /api/supply/freshness/              sales rates (demand run), stock, sales, items
#   POST /api/supply/freshness/sync-stock/   stock + sales now (the 5-minute lane, on demand)
# Engine runs and the items sync reuse their existing endpoints (+ their permissions):
#   POST /api/purchasing/trigger/  ·  POST /api/purchasing/sync-items/
# ═══════════════════════════════════════════════════════════════════════════════
from rest_framework.decorators import api_view, permission_classes  # noqa: E402

FRESH_LIMITS_MIN = {'stock': 30, 'sales': 30, 'items': 24 * 60, 'rates': 36 * 60}


def _age(dt):
    from django.utils import timezone
    return round((timezone.now() - dt).total_seconds() / 60) if dt else None


def _elapsed(start):
    from django.utils import timezone
    return int((timezone.now() - start).total_seconds()) if start else None


def _sync_progress(run):
    if run is None:
        return None
    pr = run.progress or {}
    pct = round(100 * pr['step'] / pr['steps']) if pr.get('steps') else None
    return {'kind': 'sync', 'label': 'مزامنة من SOFTECH', 'pct': pct,
            'message': pr.get('message') or 'جارٍ المزامنة…', 'elapsed_s': _elapsed(run.started_at)}


def _engine_progress(run):
    if run is None:
        return None
    pr = run.progress or {}
    return {'kind': 'engine', 'label': 'تشغيل محرك الاحتياج (معدلات البيع)',
            'pct': pr.get('pct'), 'message': pr.get('message') or 'جارٍ الحساب…',
            'elapsed_s': _elapsed(run.started_at)}


def _run_branches(run) -> list:
    if run is None:
        return []
    from apps.branches.models import Branch
    from apps.purchasing.models import ItemDemandMetrics
    ids = ItemDemandMetrics.objects.filter(run=run).values_list('branch_id', flat=True).distinct()
    return [{'id': b.id, 'name': b.name, 'code': b.softech_branch_id}
            for b in Branch.objects.filter(pk__in=list(ids)).order_by('softech_branch_id')]


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def freshness(request):
    from django.db.models import Max
    from apps.purchasing.access import can_run_engine, can_supply_write
    from apps.purchasing.models import DemandCalculationRun
    from apps.sync.models import SyncLog, SyncRun
    last = dict(SyncLog.objects.filter(table_name__in=['stkbal', 'stktrans', 'items', 'itembarcodes'])
                .values('table_name').annotate(at=Max('created_at')).values_list('table_name', 'at'))
    from .position import latest_demand_run
    run = latest_demand_run()
    active = DemandCalculationRun.objects.filter(status__in=('running', 'pending')).order_by('-started_at').first()
    from datetime import timedelta
    from django.utils import timezone
    live_sync = (SyncRun.objects.filter(status='running', started_at__gte=timezone.now() - timedelta(minutes=15))
                 .order_by('-started_at').first())
    syncing = live_sync is not None
    rates_at = (run.finished_at or run.started_at) if run else None
    out = {
        'rates': {'at': rates_at, 'age_min': _age(rates_at), 'run_id': run.pk if run else None,
                  'data_through': run.data_through_date if run else None},
        'stock': {'at': last.get('stkbal'), 'age_min': _age(last.get('stkbal'))},
        'sales': {'at': last.get('stktrans'), 'age_min': _age(last.get('stktrans'))},
        'items': {'at': last.get('items'), 'age_min': _age(last.get('items'))},
        # the branches the sales-rate engine covers — what a list can be scoped to
        'branches': _run_branches(run),
        'engine_running': bool(active), 'sync_running': syncing,
        # what the loading bar shows: pct when the job reports it, else steps, else
        # indeterminate (pct None) — plus the current phase message and elapsed time
        'progress': [p for p in (_sync_progress(live_sync), _engine_progress(active)) if p],
        'limits_min': FRESH_LIMITS_MIN,
        'can': {'sync_stock': can_supply_write(request.user),
                'run_engine': can_run_engine(request.user),
                'sync_items': getattr(_staff(request), 'role', '') in ('admin', 'pharmacist')},
    }
    for k, lim in FRESH_LIMITS_MIN.items():
        age = out[k]['age_min']
        out[k]['stale'] = age is None or age > lim
    return Response(out)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def freshness_sync_stock(request):
    """Run the fast sync lane (branches + stock + sales, read-only SELECTs on SOFTECH) now,
    in the background. Never stacks on a sync already running."""
    import threading
    from datetime import timedelta
    from django.db import connections
    from django.utils import timezone
    from apps.purchasing.access import can_supply_write
    from apps.sync.models import SyncRun
    if not can_supply_write(request.user):
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    if SyncRun.objects.filter(status='running', started_at__gte=timezone.now() - timedelta(minutes=15)).exists():
        return Response({'detail': 'توجد مزامنة جارية بالفعل.', 'running': True},
                        status=status.HTTP_202_ACCEPTED)

    def _worker():
        try:
            from apps.sync.tasks import run_fast_sync
            run_fast_sync()
        except Exception:
            logger.exception('[supply] on-demand stock sync failed')
        finally:
            connections.close_all()

    threading.Thread(target=_worker, name='supply-stock-sync', daemon=True).start()
    logger.info('[supply] stock+sales sync requested by %s', request.user.username)
    return Response({'detail': 'بدأ تحديث الأرصدة والمبيعات من SOFTECH.', 'running': True},
                    status=status.HTTP_202_ACCEPTED)


# ── Supplier-code coverage report (apps/supply/code_report.py) ─────────────────
#   GET /api/supply/reports/supplier-codes/?days=90            JSON
#   GET /api/supply/reports/supplier-codes/?days=90&format=xlsx  Excel
@api_view(['GET'])
@permission_classes([IsAuthenticated, CanOperateSupply])
def supplier_code_report(request):
    from django.http import HttpResponse
    from . import code_report
    try:
        days = max(1, min(730, int(request.query_params.get('days', 90))))
    except (TypeError, ValueError):
        days = 90
    rep = code_report.build(days)
    if request.query_params.get('format') == 'xlsx':
        resp = HttpResponse(code_report.to_excel(rep),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="supplier_codes_{days}d.xlsx"'
        return resp
    return Response(rep)
