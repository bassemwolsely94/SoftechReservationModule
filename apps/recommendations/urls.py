from django.urls import path
from . import views

urlpatterns = [
    path('run/',          views.latest_run,        name='rec-latest-run'),
    path('runs/',         views.EngineRunListView.as_view(), name='rec-runs'),
    path('trigger/',      views.trigger_engine,     name='rec-trigger'),
    path('fbt/',          views.FBTPairListView.as_view(), name='rec-fbt-list'),
    path('fbt/for-item/', views.fbt_for_item,       name='rec-fbt-for-item'),
    path('customer/',     views.customer_recs,      name='rec-customer'),
]
