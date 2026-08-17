from rest_framework.routers import DefaultRouter
from .views import InsightRunViewSet, InsightRuleViewSet

router = DefaultRouter()
router.register(r'reports', InsightRunViewSet, basename='insight-report')
router.register(r'rules',   InsightRuleViewSet, basename='insight-rule')

urlpatterns = router.urls
