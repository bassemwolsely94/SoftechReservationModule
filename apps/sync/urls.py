from django.urls import path
from .views import sync_status, trigger_sync, sync_logs, branch_health, scheduler_status

urlpatterns = [
    path('status/', sync_status),
    path('trigger/', trigger_sync),
    path('logs/', sync_logs),
    path('branch-health/', branch_health),
    path('scheduler-status/', scheduler_status),
]
