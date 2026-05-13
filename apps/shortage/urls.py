from rest_framework.routers import DefaultRouter
from .views import ShortageListViewSet

router = DefaultRouter()
router.register('lists', ShortageListViewSet, basename='shortage')

urlpatterns = router.urls
