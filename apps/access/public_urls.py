"""/api/public/ - the deliberately anonymous surface (security N6; listed in public_paths.py)."""
from django.urls import path

from apps.demand import views as demand_views

from . import public_views

urlpatterns = [
    path('challenge/', public_views.challenge),
    # /notify (same views as the older /api/demand/public/*, which stay)
    path('notify/item/', demand_views.public_item_lookup),
    path('notify/branches/', demand_views.public_branches),
    path('notify/interest/', demand_views.public_demand_interest),
]
