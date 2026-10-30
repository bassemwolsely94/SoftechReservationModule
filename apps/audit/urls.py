from django.urls import path
from rest_framework.routers import SimpleRouter
from .views import AuditLogViewSet, AbuseFlagViewSet
from .usage import screen_view, usage_report

router = SimpleRouter()     # no API-root index page under /api/audit/ (Z-4)
router.register(r'logs',  AuditLogViewSet,  basename='audit-log')
router.register(r'flags', AbuseFlagViewSet, basename='abuse-flag')

urlpatterns = [
    # P-57 screen-usage telemetry — own gates in apps/audit/usage.py
    path('screen-view/', screen_view),
    path('usage/', usage_report),
] + router.urls
