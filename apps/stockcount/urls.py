from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import StockCountSessionViewSet

router = SimpleRouter()     # no API-root index page (Z-9c)
router.register('sessions', StockCountSessionViewSet, basename='stockcount-session')

urlpatterns = [
    path('', include(router.urls)),
]
