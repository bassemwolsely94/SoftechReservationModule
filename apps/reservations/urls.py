from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReservationViewSet
from .activity_views import reservation_activity

router = DefaultRouter()
router.register(r'', ReservationViewSet, basename='reservation')

urlpatterns = [
    path('<int:reservation_id>/activity/', reservation_activity),
] + router.urls