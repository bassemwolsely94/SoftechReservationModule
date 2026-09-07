from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    StockBatchViewSet,
    purchase_expiry_candidates,
    export_purchase_expiry,
    purchase_expiry_request_markdown,
    purchase_expiry_supplier_scorecard,
    purchase_expiry_prone_items,
    purchase_expiry_rebalance_suggest,
    PurchaseExpiryRunListView,
    trigger_purchase_expiry_sync,
    spawn_expiry_count_session,
    stock_expiry_summary_view,
    stock_expiry_report_view,
    stock_expiry_stores_view,
    StockExpirySyncRunListView,
    stock_expiry_sync_trigger,
    export_stock_expiry,
    spawn_stock_expiry_count,
    expiry_disposal,
    expiry_disposal_status,
    export_disposal,
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
    path('purchase-expiry/request-markdown/', purchase_expiry_request_markdown,
         name='purchase-expiry-request-markdown'),
    path('purchase-expiry/supplier-scorecard/', purchase_expiry_supplier_scorecard,
         name='purchase-expiry-supplier-scorecard'),
    path('purchase-expiry/expiry-prone/', purchase_expiry_prone_items,
         name='purchase-expiry-prone-items'),
    path('purchase-expiry/rebalance-suggest/', purchase_expiry_rebalance_suggest,
         name='purchase-expiry-rebalance-suggest'),
    path('purchase-expiry/runs/', PurchaseExpiryRunListView.as_view(),
         name='purchase-expiry-runs'),
    path('purchase-expiry/sync/', trigger_purchase_expiry_sync,
         name='purchase-expiry-sync'),
    path('purchase-expiry/spawn-count/', spawn_expiry_count_session,
         name='purchase-expiry-spawn-count'),
    # ── Live stock-expiry (stkbalexpiry mirror, all nodes) ────────────────────
    path('stock-expiry/summary/', stock_expiry_summary_view, name='stock-expiry-summary'),
    path('stock-expiry/report/',  stock_expiry_report_view,  name='stock-expiry-report'),
    path('stock-expiry/stores/',  stock_expiry_stores_view,  name='stock-expiry-stores'),
    path('stock-expiry/runs/',    StockExpirySyncRunListView.as_view(), name='stock-expiry-runs'),
    path('stock-expiry/sync/',    stock_expiry_sync_trigger, name='stock-expiry-sync'),
    path('stock-expiry/export/',  export_stock_expiry,       name='stock-expiry-export'),
    path('stock-expiry/spawn-count/', spawn_stock_expiry_count, name='stock-expiry-spawn-count'),
    # Disposal / return workflow (expired backlog)
    path('stock-expiry/disposal/', expiry_disposal, name='stock-expiry-disposal'),
    path('stock-expiry/disposal/export/', export_disposal, name='stock-expiry-disposal-export'),
    path('stock-expiry/disposal/<int:pk>/status/', expiry_disposal_status, name='stock-expiry-disposal-status'),
] + router.urls
