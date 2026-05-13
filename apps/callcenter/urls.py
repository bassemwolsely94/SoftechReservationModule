# apps/callcenter/urls.py
from rest_framework.routers import DefaultRouter
from .views import CallLogViewSet, AddressUpdateViewSet

router = DefaultRouter()
router.register(r'calls',           CallLogViewSet,       basename='calllog')
router.register(r'address-updates', AddressUpdateViewSet, basename='address-update')

urlpatterns = router.urls
