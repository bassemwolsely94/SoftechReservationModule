from rest_framework.routers import SimpleRouter
from .views import ShortageListViewSet

router = SimpleRouter()     # no API-root index page (Z-9c)
router.register('lists', ShortageListViewSet, basename='shortage')

urlpatterns = router.urls
