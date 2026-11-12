from django.urls import path

from . import views

urlpatterns = [
    path('growth/', views.growth),
    path('problems/', views.problems),
    path('refresh/', views.refresh),
    path('rules/', views.rules),
    path('rules/<str:key>/', views.rule_update),
    path('rules/<str:key>/preview/', views.rule_preview),
    path('held/', views.held),
    path('held/<int:pk>/thumbnail/', views.held_thumbnail),
    path('held/<int:pk>/restore/', views.held_restore),
]
