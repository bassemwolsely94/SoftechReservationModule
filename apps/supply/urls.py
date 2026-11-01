from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (AvailabilityBatchViewSet, OrderListViewSet, SupplyCaseViewSet,
                    SupplyDecisionViewSet, freshness, freshness_refresh_purchases, freshness_sync_stock,
                    purchase_price_item, purchase_prices, supplier_code_report, supplier_comparison,
                    supplier_network)

from .receipt_views import receipt_check_decide, receipt_checks   # P-31

router = SimpleRouter()     # no API-root index page (Z-7a)
router.register(r'availability', AvailabilityBatchViewSet, basename='availability-batch')
router.register(r'cases', SupplyCaseViewSet, basename='supply-case')
router.register(r'order-list', OrderListViewSet, basename='supply-order-list')
router.register(r'decisions', SupplyDecisionViewSet, basename='supply-decision')

urlpatterns = [
    path('receipts/', receipt_checks, name='supply-receipt-checks'),
    path('receipts/<int:pk>/decide/', receipt_check_decide, name='supply-receipt-check-decide'),
    path('freshness/', freshness, name='supply-freshness'),
    path('freshness/sync-stock/', freshness_sync_stock, name='supply-freshness-sync-stock'),
    path('freshness/refresh-purchases/', freshness_refresh_purchases, name='supply-freshness-refresh-purchases'),
    path('purchase-prices/', purchase_prices, name='supply-purchase-prices'),
    path('purchase-prices/item/<str:code>/', purchase_price_item, name='supply-purchase-price-item'),
    path('reports/supplier-codes/', supplier_code_report, name='supply-supplier-code-report'),
    path('comparison/', supplier_comparison, name='supply-comparison'),
    path('comparison/network/<int:item_id>/', supplier_network, name='supply-supplier-network'),
] + router.urls
