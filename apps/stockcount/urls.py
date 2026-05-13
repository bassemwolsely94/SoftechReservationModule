from rest_framework.routers import DefaultRouter
from .views import StockCountSessionViewSet

router = DefaultRouter()
router.register('sessions', StockCountSessionViewSet, basename='stockcount')

urlpatterns = router.urls
