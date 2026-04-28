from django.urls import path
from .views import dashboard_summary, followups_today, purchasing_dashboard

urlpatterns = [
    path('summary/',    dashboard_summary),
    path('followups/',  followups_today),
    path('purchasing/', purchasing_dashboard),
]
