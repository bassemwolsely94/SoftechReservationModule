from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
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
