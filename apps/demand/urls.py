# ── urls.py ───────────────────────────────────────────────────────────────────
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DemandViewSet, demand_dashboard

router = DefaultRouter()
router.register(r'', DemandViewSet, basename='demand')

urlpatterns = [
    path('dashboard/', demand_dashboard),
    path('', include(router.urls)),
]
