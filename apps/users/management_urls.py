"""
URL conf for /api/users/ — user management + permissions matrix.
Imported by config/urls.py as: path('api/users/', include('apps.users.management_urls'))
"""
from django.urls import path, include
from .urls import management_urlpatterns

urlpatterns = management_urlpatterns
