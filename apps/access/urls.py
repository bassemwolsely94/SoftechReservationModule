from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('networks', views.TrustedNetworkViewSet, basename='trusted-network')

urlpatterns = [
    path('whoami/', views.whoami),
    path('', include(router.urls)),
]
