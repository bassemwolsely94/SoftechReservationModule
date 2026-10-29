from rest_framework.routers import SimpleRouter
from .views import ApprovalWorkflowViewSet, ApprovalRequestViewSet

router = SimpleRouter()     # no API-root index page under /api/approvals/ (Z-6)
router.register(r'workflows', ApprovalWorkflowViewSet, basename='approval-workflow')
router.register(r'requests',  ApprovalRequestViewSet,  basename='approval-request')

urlpatterns = router.urls
