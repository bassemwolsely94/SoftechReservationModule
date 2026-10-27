from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StockCountSessionViewSet

router = DefaultRouter()
router.register('sessions', StockCountSessionViewSet, basename='stockcount-session')

urlpatterns = [
    path('', include(router.urls)),
]
