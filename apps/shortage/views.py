"""
apps/shortage/views.py

Shortage list management with fuzzy item matching.
"""
import csv
import io

from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ShortageList, ShortageItem
from .matching import find_best_matches, _normalize
from .serializers import (
    ShortageListSerializer, ShortageListDetailSerializer,
    ShortageListCreateSerializer,
    ShortageItemSerializer, ShortageItemWriteSerializer, ShortageItemUpdateSerializer,
)


class ShortageListViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ShortageList.objects.select_related('branch', 'created_by').annotate(
            item_count=Count('items'),
            matched_count=Count('items', filter=Q(items__item__isnull=False)),
        )
        branch = self.request.query_params.get('branch')
        status_q = self.request.query_params.get('status')
        if branch:
            qs = qs.filter(branch_id=branch)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return ShortageListCreateSerializer
        if self.action == 'retrieve':
            return ShortageListDetailSerializer
        return ShortageListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    # ── Add item ──────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        shortage_list = self.get_object()
        ser = ShortageItemWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw_name = ser.validated_data.get('raw_name', '').strip()

        # ── Duplicate prevention: same normalized name in this list ───────────
        norm = _normalize(raw_name)
        if norm:
            existing_names = list(
                shortage_list.items.values_list('raw_name', flat=True)
            )
            if any(_normalize(n) == norm for n in existing_names):
                return Response(
                    {'detail': f'الصنف "{raw_name}" موجود بالفعل في هذه القائمة'},
                    status=status.HTTP_409_CONFLICT,
                )

        item = ser.save(shortage_list=shortage_list)

        # Auto-run matching if no item was manually specified
        if not item.item_id:
            matches = find_best_matches(item.raw_name, top_n=1, min_score=0.6)
            if matches:
                from apps.catalog.models import Item
                best = matches[0]
                try:
                    item.item        = Item.objects.get(pk=best['item_id'])
                    item.match_score = best['score']
                    item.save(update_fields=['item', 'match_score'])
                except Item.DoesNotExist:
                    pass
        return Response(ShortageItemSerializer(item).data, status=status.HTTP_201_CREATED)

    # ── Bulk import items (paste/OCR text) ────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request, pk=None):
        """
        POST { lines: ['paracetamol 10', 'أموكسيسيلين 5', ...] }
        Each line is: "item_name [qty] [unit]"
        Creates ShortageItems with auto-matching.
        Duplicate lines (same normalized name already in this list) are skipped.
        """
        shortage_list = self.get_object()
        lines = request.data.get('lines', [])
        if not lines:
            return Response({'detail': 'لا توجد سطور'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.catalog.models import Item as CatalogItem

        # Build a set of normalized names already in this list
        existing_norms = {
            _normalize(n)
            for n in shortage_list.items.values_list('raw_name', flat=True)
        }

        created  = []
        skipped  = []

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue

            # Parse: last token may be qty (number)
            parts    = raw.split()
            qty      = 1.0
            unit     = ''
            raw_name = raw

            if len(parts) >= 2:
                try:
                    qty      = float(parts[-1])
                    raw_name = ' '.join(parts[:-1])
                except ValueError:
                    pass

            # ── Duplicate check (within existing DB rows + current batch) ──────
            norm = _normalize(raw_name)
            if norm in existing_norms:
                skipped.append(raw_name)
                continue
            existing_norms.add(norm)   # prevent intra-batch duplication

            # Auto-match
            matches  = find_best_matches(raw_name, top_n=1, min_score=0.55)
            item_obj = None
            score    = None
            if matches:
                best = matches[0]
                try:
                    item_obj = CatalogItem.objects.get(pk=best['item_id'])
                    score    = best['score']
                except CatalogItem.DoesNotExist:
                    pass

            si = ShortageItem.objects.create(
                shortage_list   = shortage_list,
                raw_name        = raw_name,
                quantity_needed = qty,
                unit            = unit,
                item            = item_obj,
                match_score     = score,
            )
            created.append(ShortageItemSerializer(si).data)

        return Response({
            'created':      len(created),
            'skipped':      len(skipped),
            'skipped_names': skipped,
            'items':        created,
        })

    # ── Match / re-match a single item ────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path=r'items/(?P<iid>\d+)/matches')
    def item_matches(self, request, pk=None, iid=None):
        """Return top fuzzy matches for a shortage item."""
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        matches = find_best_matches(si.raw_name, top_n=8, min_score=0.2)
        return Response(matches)

    # ── Confirm/update a single item line ────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path=r'items/(?P<iid>\d+)')
    def update_item(self, request, pk=None, iid=None):
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        ser = ShortageItemUpdateSerializer(si, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        si = ser.save()
        # Confirm when item is set
        if si.item_id and not si.is_confirmed:
            si.is_confirmed = True
            si.save(update_fields=['is_confirmed'])
        return Response(ShortageItemSerializer(si).data)

    # ── Delete a single item line ─────────────────────────────────────────────

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<iid>\d+)/delete')
    def delete_item(self, request, pk=None, iid=None):
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        si.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Change status ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        sl = self.get_object()
        if sl.status != 'open':
            return Response({'detail': 'القائمة ليست مفتوحة'}, status=status.HTTP_400_BAD_REQUEST)
        sl.status = 'submitted'
        sl.save(update_fields=['status'])
        return Response({'detail': 'تم إرسال القائمة'})

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        sl = self.get_object()
        sl.status = 'resolved'
        sl.save(update_fields=['status'])
        return Response({'detail': 'تم حل القائمة'})

    # ── Export CSV ────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        sl    = self.get_object()
        items = sl.items.select_related('item').order_by('raw_name')
        buf   = io.StringIO()
        w     = csv.writer(buf)
        w.writerow(['الاسم كما أُدخل', 'الصنف المطابق', 'كود Softech', 'الكمية', 'الوحدة', 'نسبة التطابق', 'مُأكَّد', 'ملاحظات'])
        for si in items:
            w.writerow([
                si.raw_name,
                si.item.name if si.item_id else '',
                si.item.softech_id if si.item_id else '',
                si.quantity_needed,
                si.unit,
                f'{si.match_score:.0%}' if si.match_score else '',
                'نعم' if si.is_confirmed else 'لا',
                si.notes,
            ])
        response = HttpResponse(
            '﻿' + buf.getvalue(),
            content_type='text/csv; charset=utf-8-sig',
        )
        response['Content-Disposition'] = f'attachment; filename="shortage_{sl.id}.csv"'
        return response
