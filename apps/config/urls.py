from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import SystemSettingViewSet, DropdownOptionViewSet, pharmacy_profile, theme

router = DefaultRouter()
router.register('settings',  SystemSettingViewSet,  basename='config-settings')
router.register('dropdowns', DropdownOptionViewSet, basename='config-dropdowns')

urlpatterns = router.urls + [
    path('pharmacy/', pharmacy_profile, name='config-pharmacy'),
    path('theme/',    theme,            name='config-theme'),
]
