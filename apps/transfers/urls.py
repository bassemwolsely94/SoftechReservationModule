from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TransferRequestViewSet

router = DefaultRouter()
router.register(r'', TransferRequestViewSet, basename='transfer')

urlpatterns = [
    path('', include(router.urls)),
]
