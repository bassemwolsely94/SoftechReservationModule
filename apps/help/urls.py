"""apps/help/urls.py — mounted at /api/help/"""
from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='help-index'),
    path('search/', views.search, name='help-search'),
    path('stats/', views.stats, name='help-stats'),
    path('feedback/', views.feedback, name='help-feedback'),
    path('feedback/<int:pk>/resolve/', views.feedback_resolve, name='help-feedback-resolve'),
    path('modules/<str:key>/', views.module_detail, name='help-module'),
    path('screens/<str:key>/', views.screen_detail, name='help-screen'),
    path('screens/<str:key>/revisions/', views.screen_revisions, name='help-screen-revisions'),
]
