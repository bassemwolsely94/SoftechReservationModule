from rest_framework.routers import DefaultRouter
from .views import StockBatchViewSet

router = DefaultRouter()
router.register(r'', StockBatchViewSet, basename='stockbatch')

urlpatterns = router.urls
