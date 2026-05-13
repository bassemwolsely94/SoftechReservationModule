"""
apps/stockcount/views.py

Stock-count sessions.  Key endpoints:
  POST /api/stockcount/sessions/                   → create session
  GET  /api/stockcount/sessions/{id}/              → detail + lines
  POST /api/stockcount/sessions/{id}/import-erp/  → pull items from Softech stktrans doc
  POST /api/stockcount/sessions/{id}/add-item/    → add item manually
  PATCH /api/stockcount/sessions/{id}/lines/{lid}/ → update counted_qty
  POST /api/stockcount/sessions/{id}/complete/    → mark complete
  GET  /api/stockcount/sessions/{id}/export/      → CSV summary
"""
import csv
import io
import datetime

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import StockCountSession, StockCountLine
from .serializers import (
    StockCountSessionListSerializer,
    StockCountSessionDetailSerializer,
    StockCountSessionCreateSerializer,
    StockCountLineSerializer,
    StockCountLineUpdateSerializer,
)


class StockCountSessionViewSet(viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StockCountSession.objects.select_related('branch', 'created_by')
        # annotate for list serializer
        qs = qs.annotate(
            total_lines=Count('lines'),
            discrepancy_count=Count('lines', filter=Q(lines__has_discrepancy=True)),
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
            return StockCountSessionCreateSerializer
        if self.action in ('retrieve', 'import_erp', 'add_item'):
            return StockCountSessionDetailSerializer
        return StockCountSessionListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    # ── Import items from Softech stktrans doc ────────────────────────────────

    @action(detail=True, methods=['post'], url_path='import-erp')
    def import_erp(self, request, pk=None):
        """
        POST body: { doc_code: '110', doc_number: '1234', branch_code: '1' }
        Fetches items from SOFTECH stktrans, creates StockCountLine per item,
        sets system_qty from Django ItemStock, erp_transqty from ERP.
        """
        session = self.get_object()
        if session.status != 'open':
            return Response({'detail': 'الجلسة مغلقة'}, status=status.HTTP_400_BAD_REQUEST)

        doc_code   = (request.data.get('doc_code') or '').strip()
        doc_number = (request.data.get('doc_number') or '').strip()
        branch_code = (request.data.get('branch_code') or '').strip()

        if not doc_code or not doc_number:
            return Response(
                {'detail': 'doc_code و doc_number مطلوبان'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -- Query Softech -------------------------------------------------------
        try:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
            cursor = conn.cursor()
            sql = (
                "SELECT st.itemcode, SUM(st.transqty) AS qty, "
                "  MAX(i.itemname) AS itemname "
                "FROM SOFTECHDB9.dbo.stktrans st "
                "JOIN SOFTECHDB9.dbo.items i ON i.itemcode = st.itemcode "
                f"WHERE st.doccode = '{doc_code}' "
                f"  AND st.docnumber = '{doc_number}' "
            )
            if branch_code:
                sql += f"  AND st.branchcode = '{branch_code}' "
            sql += "GROUP BY st.itemcode ORDER BY itemname"
            cursor.execute(sql)
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            return Response(
                {'detail': f'خطأ في الاتصال بـ SOFTECH: {e}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not rows:
            return Response({'detail': 'لم يتم العثور على سطور لهذا المستند'}, status=status.HTTP_404_NOT_FOUND)

        # -- Resolve items from Django catalog -----------------------------------
        from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES
        from django.db.models import Sum

        item_codes = [r[0] for r in rows]
        items_map  = {i.softech_id: i for i in Item.objects.filter(softech_id__in=item_codes)}

        # Aggregate system stock per item for this branch
        stock_map = {}
        stock_qs = (
            ItemStock.objects
            .filter(item__softech_id__in=item_codes, branch=session.branch)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item__softech_id')
            .annotate(qty=Sum('quantity_on_hand'))
        )
        for s in stock_qs:
            stock_map[s['item__softech_id']] = float(s['qty'] or 0)

        # -- Create lines --------------------------------------------------------
        created = 0
        skipped = 0
        for row in rows:
            itemcode, erp_qty, itemname = row[0], row[1], row[2]
            item = items_map.get(str(itemcode))
            exists = StockCountLine.objects.filter(session=session, item=item).exists()
            if exists and item:
                skipped += 1
                continue
            StockCountLine.objects.create(
                session      = session,
                item         = item,
                manual_item_name = itemname if not item else '',
                system_qty   = stock_map.get(str(itemcode), 0),
                erp_transqty = float(erp_qty or 0),
            )
            created += 1

        # Save doc reference
        session.erp_doc_code   = doc_code
        session.erp_doc_number = doc_number
        session.save(update_fields=['erp_doc_code', 'erp_doc_number'])

        ser = StockCountSessionDetailSerializer(
            self.get_queryset().get(pk=session.pk),
            context=self.get_serializer_context()
        )
        return Response({**ser.data, '_imported': created, '_skipped': skipped})

    # ── Add item manually ────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        """
        POST { item_id: 123 }  or  { manual_item_name: 'اسم الصنف' }
        Adds a line to the session with system_qty from live stock.
        """
        session = self.get_object()
        if session.status != 'open':
            return Response({'detail': 'الجلسة مغلقة'}, status=status.HTTP_400_BAD_REQUEST)

        item_id = request.data.get('item_id')
        manual  = (request.data.get('manual_item_name') or '').strip()

        from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES
        from django.db.models import Sum

        item = None
        system_qty = 0

        if item_id:
            try:
                item = Item.objects.get(pk=item_id)
            except Item.DoesNotExist:
                return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)
            # Check duplicate
            if StockCountLine.objects.filter(session=session, item=item).exists():
                return Response({'detail': 'هذا الصنف موجود بالفعل في الجلسة'}, status=status.HTTP_400_BAD_REQUEST)
            # Live stock
            agg = (
                ItemStock.objects
                .filter(item=item, branch=session.branch)
                .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
                .aggregate(qty=Sum('quantity_on_hand'))
            )
            system_qty = float(agg['qty'] or 0)
        elif not manual:
            return Response({'detail': 'يجب تحديد صنف أو إدخال اسم يدوي'}, status=status.HTTP_400_BAD_REQUEST)

        line = StockCountLine.objects.create(
            session=session, item=item, manual_item_name=manual,
            system_qty=system_qty,
        )
        return Response(StockCountLineSerializer(line).data, status=status.HTTP_201_CREATED)

    # ── Update a single line's counted_qty ───────────────────────────────────

    @action(detail=True, methods=['patch'], url_path=r'lines/(?P<lid>\d+)')
    def update_line(self, request, pk=None, lid=None):
        session = self.get_object()
        try:
            line = session.lines.get(pk=lid)
        except StockCountLine.DoesNotExist:
            return Response({'detail': 'السطر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        ser = StockCountLineUpdateSerializer(line, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(StockCountLineSerializer(line).data)

    # ── Complete session ─────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        session = self.get_object()
        if session.status != 'open':
            return Response({'detail': 'الجلسة ليست مفتوحة'}, status=status.HTTP_400_BAD_REQUEST)
        session.status       = 'completed'
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'completed_at'])
        return Response({'detail': 'تم إغلاق جلسة الجرد بنجاح'})

    # ── Export CSV ───────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        session = self.get_object()
        lines   = session.lines.select_related('item').order_by('item__name', 'manual_item_name')

        buf = io.StringIO()
        w   = csv.writer(buf)
        w.writerow([
            'كود الصنف', 'اسم الصنف', 'كمية النظام', 'كمية ERP', 'الكمية المعدودة', 'الفرق', 'ملاحظات'
        ])
        for l in lines:
            w.writerow([
                l.item.softech_id if l.item_id else '',
                l.item.name if l.item_id else l.manual_item_name,
                l.system_qty,
                l.erp_transqty or '',
                l.counted_qty if l.counted_qty is not None else '',
                l.difference if l.difference is not None else '',
                l.notes,
            ])

        response = HttpResponse(
            '﻿' + buf.getvalue(),   # BOM for Excel Arabic
            content_type='text/csv; charset=utf-8-sig',
        )
        fname = f'stock_count_{session.branch_id}_{session.count_date}.csv'
        response['Content-Disposition'] = f'attachment; filename="{fname}"'
        return response
