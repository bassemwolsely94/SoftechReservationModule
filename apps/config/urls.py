from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import SystemSettingViewSet, DropdownOptionViewSet, pharmacy_profile, theme
from . import code_maps

router = DefaultRouter()
router.register('settings',  SystemSettingViewSet,  basename='config-settings')
router.register('dropdowns', DropdownOptionViewSet, basename='config-dropdowns')

urlpatterns = router.urls + [
    path('pharmacy/', pharmacy_profile, name='config-pharmacy'),
    path('theme/',    theme,            name='config-theme'),
    # SOFTECH code maps (piece 4) — settings/view to read, settings/edit to change
    path('code-maps/channels/',              code_maps.channel_list,     name='code-maps-channels'),
    path('code-maps/channels/<int:pk>/',     code_maps.channel_detail,   name='code-maps-channel'),
    path('code-maps/item-types/',            code_maps.item_type_list,   name='code-maps-item-types'),
    path('code-maps/item-types/<int:pk>/',   code_maps.item_type_detail, name='code-maps-item-type'),
]
