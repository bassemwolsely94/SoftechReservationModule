from rest_framework.routers import SimpleRouter
from .views import AuditLogViewSet, AbuseFlagViewSet

router = SimpleRouter()     # no API-root index page under /api/audit/ (Z-4)
router.register(r'logs',  AuditLogViewSet,  basename='audit-log')
router.register(r'flags', AbuseFlagViewSet, basename='abuse-flag')

urlpatterns = router.urls
