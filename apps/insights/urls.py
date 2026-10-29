from rest_framework.routers import SimpleRouter
from .views import InsightRunViewSet, InsightRuleViewSet

router = SimpleRouter()     # no API-root index page (Z-9a)
router.register(r'reports', InsightRunViewSet, basename='insight-report')
router.register(r'rules',   InsightRuleViewSet, basename='insight-rule')

urlpatterns = router.urls
