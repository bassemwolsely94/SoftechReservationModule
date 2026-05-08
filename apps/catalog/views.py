from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models
from .models import Category, Item, ItemStock
from .serializers import CategorySerializer, ItemSerializer, ItemStockSerializer, ItemSearchSerializer


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CategorySerializer
    queryset = Category.objects.all().order_by('name')


class ItemViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'requires_fridge', 'medicine_type']
    search_fields = ['name', 'name_scientific', 'barcode', 'softech_id']

    def get_queryset(self):
        qs = Item.objects.filter(is_active=True).prefetch_related(
            'stock_levels__branch', 'category'
        )
        in_stock = self.request.query_params.get('in_stock')
        if in_stock == 'true':
            from django.db.models import Sum
            qs = qs.annotate(
                total_qty=Sum('stock_levels__quantity_on_hand')
            ).filter(total_qty__gt=0)
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ItemSearchSerializer
        return ItemSerializer

    @action(detail=True, methods=['get'])
    def stock(self, request, pk=None):
        item = self.get_object()
        stocks = ItemStock.objects.filter(item=item).select_related('branch')
        return Response(ItemStockSerializer(stocks, many=True).data)

    @action(detail=False, methods=['get'], url_path='softech-search')
    def softech_search(self, request):
        """
        GET /api/items/softech-search/?q=panadol
        Searches items live from SOFTECH (falls back to PG catalog if SOFTECH unavailable).
        Returns name, code, barcode, public price, and current PG stock.
        """
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'detail': 'يجب إدخال حرفين على الأقل للبحث'}, status=status.HTTP_400_BAD_REQUEST)

        like_q = f'%{q}%'
        results = []

        try:
            from config.sybase import get_sybase_connection
            from apps.sync.sybase_queries import QUERY_ITEM_SEARCH
            conn = get_sybase_connection()
            cursor = conn.cursor()
            cursor.execute(QUERY_ITEM_SEARCH, [like_q, like_q, like_q])
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                results.append({
                    'softech_id':   str(row[0]).strip() if row[0] else '',
                    'name':         str(row[1]).strip() if row[1] else '',
                    'name_scientific': str(row[2]).strip() if row[2] else '',
                    'barcode':      str(row[3]).strip() if row[3] else '',
                    'unit_sale_price': float(row[6]) if row[6] is not None else 0.0,
                    'requires_fridge': bool(row[9]) if row[9] else False,
                    'medicine_type': str(row[10]).strip() if row[10] else '',
                    'source': 'softech',
                })
        except Exception:
            # SOFTECH unavailable — fall back to PG catalog
            qs = Item.objects.filter(is_active=True).filter(
                models.Q(name__icontains=q) |
                models.Q(softech_id__icontains=q) |
                models.Q(barcode__icontains=q)
            )[:30]
            results = [
                {
                    'softech_id':   item.softech_id,
                    'name':         item.name,
                    'name_scientific': item.name_scientific,
                    'barcode':      item.barcode,
                    'unit_sale_price': float(item.unit_sale_price),
                    'requires_fridge': item.requires_fridge,
                    'medicine_type': item.medicine_type,
                    'source': 'pg_catalog',
                }
                for item in qs
            ]

        return Response({'results': results, 'count': len(results)})
