from django.urls import path
from rest_framework.routers import SimpleRouter

from . import call_list_views as CL
from . import reminder_views as RV
from .views import ChronicMedicationProfileViewSet, FollowUpTaskViewSet

router = SimpleRouter()     # no API-root index page (Z-8a)
router.register(r'chronic', ChronicMedicationProfileViewSet, basename='chronic')
router.register(r'tasks',   FollowUpTaskViewSet,             basename='followup')

urlpatterns = [
    path('refill-reminders/', RV.overview, name='refill-reminders'),
    path('refill-reminders/preview/', RV.preview, name='refill-reminders-preview'),
    path('refill-reminders/run/', RV.run_now, name='refill-reminders-run'),
    path('call-lists/', CL.CallListView.as_view(), name='call-lists'),
    path('call-lists/preview/', CL.CallListPreviewView.as_view(), name='call-lists-preview'),
    path('call-lists/agents/', CL.CallListAgentsView.as_view(), name='call-lists-agents'),
    path('call-lists/<int:pk>/close/', CL.CallListCloseView.as_view(), name='call-lists-close'),
] + router.urls
