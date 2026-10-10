from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (AvailabilityBatchViewSet, OrderListViewSet, SupplyCaseViewSet,
                    SupplyDecisionViewSet, freshness, freshness_sync_stock,
                    supplier_code_report, supplier_comparison, supplier_network)

router = DefaultRouter()
router.register(r'availability', AvailabilityBatchViewSet, basename='availability-batch')
router.register(r'cases', SupplyCaseViewSet, basename='supply-case')
router.register(r'order-list', OrderListViewSet, basename='supply-order-list')
router.register(r'decisions', SupplyDecisionViewSet, basename='supply-decision')

urlpatterns = [
    path('freshness/', freshness, name='supply-freshness'),
    path('freshness/sync-stock/', freshness_sync_stock, name='supply-freshness-sync-stock'),
    path('reports/supplier-codes/', supplier_code_report, name='supply-supplier-code-report'),
    path('comparison/', supplier_comparison, name='supply-comparison'),
    path('comparison/network/<int:item_id>/', supplier_network, name='supply-supplier-network'),
] + router.urls
