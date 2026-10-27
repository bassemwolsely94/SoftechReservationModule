"""
apps/procurement/urls.py

URL routing for the Procurement Intelligence Platform.
All endpoints mounted under /api/procurement/
"""
from django.urls import path
from . import views

urlpatterns = [
    # ── Dashboard ──────────────────────────────────────────────────────────────
    path('dashboard/',          views.procurement_dashboard,       name='procurement-dashboard'),
    path('overview/',           views.procurement_overview,        name='procurement-overview'),

    # ── Module 2: Supplier Performance ────────────────────────────────────────
    path('suppliers/',          views.SupplierPerformanceListView.as_view(), name='procurement-suppliers'),
    path('suppliers/<str:supplier_code>/',
                                views.SupplierPerformanceDetailView.as_view(), name='procurement-supplier-detail'),
    path('suppliers/<str:supplier_code>/history/',
                                views.supplier_purchase_history,   name='procurement-supplier-history'),

    # ── Module 3 + 4: Item Procurement + Mapping Table ────────────────────────
    path('items/<str:item_code>/analysis/',
                                views.item_procurement_analysis,   name='procurement-item-analysis'),
    path('mappings/',           views.SupplierItemMappingListView.as_view(), name='procurement-mappings'),

    # ── Module 5: Margin ───────────────────────────────────────────────────────
    path('margins/',            views.margin_analysis,             name='procurement-margins'),

    # ── Module 6: Returns ──────────────────────────────────────────────────────
    path('returns/',            views.return_analysis,             name='procurement-returns'),

    # ── Module 8: Price Control ───────────────────────────────────────────────
    path('price-control/',      views.price_control,               name='procurement-price-control'),

    # ── Module 9: Optimization ────────────────────────────────────────────────
    path('optimization/',       views.procurement_optimization,    name='procurement-optimization'),

    # ── Module 10: Buyer Performance ─────────────────────────────────────────
    path('buyers/',             views.BuyerPerformanceListView.as_view(), name='procurement-buyers'),

    # ── Module 11: Branch Procurement ────────────────────────────────────────
    path('branches/',           views.branch_procurement,          name='procurement-branches'),

    # ── Purchase Lines (drill-down) ───────────────────────────────────────────
    path('lines/',              views.PurchaseLineListView.as_view(),     name='procurement-lines'),

    # ── Engine Runs ───────────────────────────────────────────────────────────
    path('runs/',               views.EngineRunListView.as_view(),        name='procurement-runs'),
    path('trigger/',            views.trigger_engine,                     name='procurement-trigger'),

    # ── Snapshots ─────────────────────────────────────────────────────────────
    path('snapshots/',          views.SnapshotListView.as_view(),         name='procurement-snapshots'),

    # ── Alerts ────────────────────────────────────────────────────────────────
    path('alerts/',             views.AlertListView.as_view(),            name='procurement-alerts'),
    path('alerts/<int:pk>/resolve/', views.resolve_alert,                 name='procurement-alert-resolve'),

    # ── v2/v3: Purchase History (enhanced) ────────────────────────────────────
    path('history/',            views.PurchaseHistoryView.as_view(),      name='procurement-history'),
    path('history/summary/',    views.purchase_history_summary,           name='procurement-history-summary'),
    path('filter-options/',     views.procurement_filter_options,         name='procurement-filter-options'),

    # ── v2: Supplier Segmentation ─────────────────────────────────────────────
    path('segments/',           views.SupplierSegmentationListView.as_view(), name='procurement-segments'),
    path('segments/summary/',   views.supplier_segmentation_summary,      name='procurement-segments-summary'),
    path('segments/<int:pk>/update/', views.update_supplier_segmentation, name='procurement-segment-update'),

    # ── v2: Enhanced Supplier Performance ────────────────────────────────────
    path('suppliers-enhanced/', views.SupplierPerformanceEnhancedListView.as_view(), name='procurement-suppliers-enhanced'),

    # ── v2: FOC Analysis ──────────────────────────────────────────────────────
    path('foc/',                views.foc_analysis,                       name='procurement-foc'),

    # ── v2: Expiry Return Analysis ────────────────────────────────────────────
    path('expiry-returns/',     views.expiry_return_analysis,             name='procurement-expiry-returns'),

    # ── v2: Tax Burden Analysis ───────────────────────────────────────────────
    path('tax-burden/',         views.tax_burden_analysis,                name='procurement-tax-burden'),

    # ── v3: Admin-managed Supplier Categories + Classification Rules ──────────
    path('categories/',         views.SupplierCategoryListCreateView.as_view(),   name='procurement-categories'),
    path('categories/<int:pk>/', views.SupplierCategoryDetailView.as_view(),      name='procurement-category-detail'),
    path('classification-rules/', views.SupplierClassificationRuleListCreateView.as_view(), name='procurement-rules'),
    path('classification-rules/<int:pk>/', views.SupplierClassificationRuleDetailView.as_view(), name='procurement-rule-detail'),
    path('reclassify/',         views.reclassify_suppliers,               name='procurement-reclassify'),
    path('person-codes/',       views.softech_person_codes,               name='procurement-person-codes'),
]
