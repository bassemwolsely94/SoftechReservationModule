from rest_framework.routers import DefaultRouter
from .views import SystemSettingViewSet, DropdownOptionViewSet

router = DefaultRouter()
router.register('settings',  SystemSettingViewSet,  basename='config-settings')
router.register('dropdowns', DropdownOptionViewSet, basename='config-dropdowns')

urlpatterns = router.urls
