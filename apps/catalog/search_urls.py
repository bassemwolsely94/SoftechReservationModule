"""URL routes for the cross-domain universal search (mounted at /api/search/)."""
from django.urls import path

from .search_views import universal_search_view

urlpatterns = [
    path('universal', universal_search_view, name='universal-search'),
]
