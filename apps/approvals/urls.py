from rest_framework.routers import DefaultRouter
from .views import ApprovalWorkflowViewSet, ApprovalRequestViewSet

router = DefaultRouter()
router.register(r'workflows', ApprovalWorkflowViewSet, basename='approval-workflow')
router.register(r'requests',  ApprovalRequestViewSet,  basename='approval-request')

urlpatterns = router.urls
