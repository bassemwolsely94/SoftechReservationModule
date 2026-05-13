from rest_framework.routers import DefaultRouter
from .views import VoucherViewSet

router = DefaultRouter()
router.register('vouchers', VoucherViewSet, basename='vouchers')

urlpatterns = router.urls
