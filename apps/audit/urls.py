from rest_framework.routers import DefaultRouter
from .views import AuditLogViewSet, AbuseFlagViewSet

router = DefaultRouter()
router.register(r'logs',  AuditLogViewSet,  basename='audit-log')
router.register(r'flags', AbuseFlagViewSet, basename='abuse-flag')

urlpatterns = router.urls
