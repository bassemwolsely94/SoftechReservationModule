"""/api/public/ - the deliberately anonymous surface (security N6; listed in public_paths.py)."""
from django.urls import path

from . import public_views

urlpatterns = [
    path('challenge/', public_views.challenge),
]
