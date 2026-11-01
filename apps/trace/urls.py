from django.urls import path

from .views import parse_scan, scan

urlpatterns = [
    path('parse/', parse_scan),
    path('scan/', scan),
]
