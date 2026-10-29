from django.urls import path
from rest_framework.routers import SimpleRouter

from . import reminder_views as RV
from .views import ChronicMedicationProfileViewSet, FollowUpTaskViewSet

router = SimpleRouter()     # no API-root index page (Z-8a)
router.register(r'chronic', ChronicMedicationProfileViewSet, basename='chronic')
router.register(r'tasks',   FollowUpTaskViewSet,             basename='followup')

urlpatterns = [
    path('refill-reminders/', RV.overview, name='refill-reminders'),
    path('refill-reminders/preview/', RV.preview, name='refill-reminders-preview'),
    path('refill-reminders/run/', RV.run_now, name='refill-reminders-run'),
] + router.urls
