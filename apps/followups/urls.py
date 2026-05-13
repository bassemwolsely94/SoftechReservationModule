from rest_framework.routers import DefaultRouter
from .views import ChronicMedicationProfileViewSet, FollowUpTaskViewSet

router = DefaultRouter()
router.register(r'chronic', ChronicMedicationProfileViewSet, basename='chronic')
router.register(r'tasks',   FollowUpTaskViewSet,             basename='followup')

urlpatterns = router.urls
