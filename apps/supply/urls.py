from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (AvailabilityBatchViewSet, OrderListViewSet, SupplyCaseViewSet,
                    SupplyDecisionViewSet, freshness, freshness_refresh_purchases, freshness_sync_stock,
                    purchase_price_item, purchase_prices, supplier_code_report, supplier_comparison,
                    supplier_network)

from .receipt_views import receipt_check_decide, receipt_checks   # P-31
from .missing_bonus_views import missing_bonus, missing_bonus_export   # C18
from .out_here_views import out_here, out_here_export              # C06
from .dearer_views import bought_dearer, bought_dearer_export      # C17

router = SimpleRouter()     # no API-root index page (Z-7a)
router.register(r'availability', AvailabilityBatchViewSet, basename='availability-batch')
router.register(r'cases', SupplyCaseViewSet, basename='supply-case')
router.register(r'order-list', OrderListViewSet, basename='supply-order-list')
router.register(r'decisions', SupplyDecisionViewSet, basename='supply-decision')

urlpatterns = [
    path('receipts/', receipt_checks, name='supply-receipt-checks'),
    path('missing-bonus/', missing_bonus, name='supply-missing-bonus'),
    path('missing-bonus/export/', missing_bonus_export, name='supply-missing-bonus-export'),
    path('out-here/', out_here, name='supply-out-here'),
    path('out-here/export/', out_here_export, name='supply-out-here-export'),
    path('receipts/<int:pk>/decide/', receipt_check_decide, name='supply-receipt-check-decide'),
    path('freshness/', freshness, name='supply-freshness'),
    path('freshness/sync-stock/', freshness_sync_stock, name='supply-freshness-sync-stock'),
    path('freshness/refresh-purchases/', freshness_refresh_purchases, name='supply-freshness-refresh-purchases'),
    path('purchase-prices/', purchase_prices, name='supply-purchase-prices'),
    path('purchase-prices/item/<str:code>/', purchase_price_item, name='supply-purchase-price-item'),
    path('bought-dearer/', bought_dearer, name='supply-bought-dearer'),
    path('bought-dearer/export/', bought_dearer_export, name='supply-bought-dearer-export'),
    path('reports/supplier-codes/', supplier_code_report, name='supply-supplier-code-report'),
    path('comparison/', supplier_comparison, name='supply-comparison'),
    path('comparison/network/<int:item_id>/', supplier_network, name='supply-supplier-network'),
] + router.urls
