from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    StockBatchViewSet,
    purchase_expiry_candidates,
    export_purchase_expiry,
    purchase_expiry_supplier_scorecard,
    purchase_expiry_rebalance_suggest,
    PurchaseExpiryRunListView,
    trigger_purchase_expiry_sync,
    spawn_expiry_count_session,
)

router = DefaultRouter()
router.register(r'', StockBatchViewSet, basename='stockbatch')

# Explicit paths MUST precede the router — the router's detail regex
# (^(?P<pk>[^/.]+)/$) would otherwise capture a single-segment path.
urlpatterns = [
    path('purchase-expiry/candidates/', purchase_expiry_candidates,
         name='purchase-expiry-candidates'),
    path('purchase-expiry/export/', export_purchase_expiry,
         name='purchase-expiry-export'),
    path('purchase-expiry/supplier-scorecard/', purchase_expiry_supplier_scorecard,
         name='purchase-expiry-supplier-scorecard'),
    path('purchase-expiry/rebalance-suggest/', purchase_expiry_rebalance_suggest,
         name='purchase-expiry-rebalance-suggest'),
    path('purchase-expiry/runs/', PurchaseExpiryRunListView.as_view(),
         name='purchase-expiry-runs'),
    path('purchase-expiry/sync/', trigger_purchase_expiry_sync,
         name='purchase-expiry-sync'),
    path('purchase-expiry/spawn-count/', spawn_expiry_count_session,
         name='purchase-expiry-spawn-count'),
] + router.urls
