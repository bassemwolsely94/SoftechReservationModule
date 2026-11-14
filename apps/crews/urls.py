"""apps/crews/urls.py — /api/crews/ (see views.py for the route table)."""
from django.urls import path

from . import views

urlpatterns = [
    path('', views.crew_list),
    path('options/', views.options),
    path('preview/', views.preview),
    path('unattributed-sales/', views.unattributed_sales),
    path('unattributed-sales/config/', views.unattributed_config),
    path('<int:pk>/', views.crew_detail),
    path('<int:pk>/unarchive/', views.crew_unarchive),
    path('<int:pk>/members/', views.crew_members),
    path('<int:pk>/history/', views.crew_history),
    path('<int:pk>/rules/', views.rule_add),
    path('<int:pk>/rules/<int:rid>/end/', views.rule_end),
    path('<int:pk>/rules/<int:rid>/replace/', views.rule_replace),
    path('<int:pk>/manual/', views.manual_add),
    path('<int:pk>/manual/<int:mid>/end/', views.manual_end),
]
