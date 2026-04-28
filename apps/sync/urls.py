from django.urls import path
from .views import sync_status, trigger_sync, sync_logs

urlpatterns = [
    path('status/', sync_status),
    path('trigger/', trigger_sync),
    path('logs/', sync_logs),
]
