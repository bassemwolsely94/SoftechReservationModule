# ── urls.py ───────────────────────────────────────────────────────────────────
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DemandViewSet, demand_dashboard, lost_value_reconciliation,
    purchase_suggestions, push_purchase_suggestions, capture_leaderboard,
    substitution_analytics, price_objections,
    public_item_lookup, public_branches, public_demand_interest, shelf_qr,
)

router = DefaultRouter()
router.register(r'', DemandViewSet, basename='demand')

urlpatterns = [
    path('dashboard/', demand_dashboard),
    path('lost-value-reconciliation/', lost_value_reconciliation),
    path('purchase-suggestions/', purchase_suggestions),
    path('purchase-suggestions/push/', push_purchase_suggestions),
    path('capture-leaderboard/', capture_leaderboard),
    path('substitution-analytics/', substitution_analytics),
    path('price-objections/', price_objections),
    path('shelf-qr/', shelf_qr),
    # ── Public (unauthenticated) self-service ──
    path('public/item/', public_item_lookup),
    path('public/branches/', public_branches),
    path('public/interest/', public_demand_interest),
    path('', include(router.urls)),
]
