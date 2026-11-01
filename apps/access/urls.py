from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()   # no browsable API root / format routes
router.register('networks', views.TrustedNetworkViewSet, basename='trusted-network')
router.register('devices', views.DeviceViewSet, basename='device')

urlpatterns = [
    path('whoami/', views.whoami),
    path('', include(router.urls)),
]
