# apps/callcenter/urls.py
from rest_framework.routers import DefaultRouter
from .views import CallLogViewSet, AddressUpdateViewSet, CustomerCaseViewSet

router = DefaultRouter()
router.register(r'calls',           CallLogViewSet,       basename='calllog')
router.register(r'address-updates', AddressUpdateViewSet, basename='address-update')
router.register(r'cases',           CustomerCaseViewSet,  basename='customercase')

from django.urls import path
from .whisper_views import TranscriptCorrectView, WhisperControlView, WhisperStatusView

urlpatterns = [
    path('whisper/', WhisperStatusView.as_view(), name='whisper-status'),
    path('whisper/control/', WhisperControlView.as_view(), name='whisper-control'),
    path('transcripts/<int:pk>/correct/', TranscriptCorrectView.as_view(), name='transcript-correct'),
] + router.urls
