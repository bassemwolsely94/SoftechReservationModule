# apps/callcenter/urls.py
from rest_framework.routers import DefaultRouter
from .views import CallLogViewSet, AddressUpdateViewSet, CustomerCaseViewSet

router = DefaultRouter()
router.register(r'calls',           CallLogViewSet,       basename='calllog')
router.register(r'address-updates', AddressUpdateViewSet, basename='address-update')
router.register(r'cases',           CustomerCaseViewSet,  basename='customercase')

urlpatterns = router.urls
