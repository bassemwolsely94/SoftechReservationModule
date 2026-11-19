from django.urls import path
from rest_framework.routers import SimpleRouter
from .hq_exceptions_views import hq_exceptions
from .views import InsightRunViewSet, InsightRuleViewSet

router = SimpleRouter()     # no API-root index page (Z-9a)
router.register(r'reports', InsightRunViewSet, basename='insight-report')
router.register(r'rules',   InsightRuleViewSet, basename='insight-rule')

urlpatterns = [
    path('exceptions/', hq_exceptions, name='insight-hq-exceptions'),   # C32 weekly HQ exception digest
] + router.urls
