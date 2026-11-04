"""/api/public/ - the deliberately anonymous surface (security N6; listed in public_paths.py)."""
from django.urls import path

from apps.delivery import views as delivery_views
from apps.counselling import public_views as counsel_views
from apps.demand import views as demand_views

from . import public_views

urlpatterns = [
    path('challenge/', public_views.challenge),
    path('health/', public_views.health),     # liveness: DB reachable → 200, else 503
    path('track/<str:token>/', delivery_views.delivery_public_track),
    # Project 4: the customer's counselling card (signed send token) + its opt-out link
    path('counsel/<str:token>/', counsel_views.counsel_card_public),
    path('counsel/<str:token>/opt-out/', counsel_views.counsel_card_opt_out),
    # /notify (same views as the older /api/demand/public/*, which stay)
    path('notify/item/', demand_views.public_item_lookup),
    path('notify/branches/', demand_views.public_branches),
    path('notify/interest/', demand_views.public_demand_interest),
]
