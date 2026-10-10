"""apps/help/urls.py — mounted at /api/help/"""
from django.urls import path

from . import onboarding_views as ob
from . import views

urlpatterns = [
    path('', views.index, name='help-index'),
    path('search/', views.search, name='help-search'),
    path('stats/', views.stats, name='help-stats'),
    path('manual/', views.manual, name='help-manual'),
    path('ask/', views.ask, name='help-ask'),
    path('tour-event/', views.tour_event, name='help-tour-event'),
    path('usage/', views.usage, name='help-usage'),
    path('feedback/', views.feedback, name='help-feedback'),
    path('feedback/<int:pk>/resolve/', views.feedback_resolve, name='help-feedback-resolve'),
    path('modules/<str:key>/', views.module_detail, name='help-module'),
    path('screens/<str:key>/', views.screen_detail, name='help-screen'),
    path('screens/<str:key>/revisions/', views.screen_revisions, name='help-screen-revisions'),
    path('onboarding/', ob.my_path, name='help-onboarding'),
    path('onboarding/learned/', ob.mark_learned, name='help-onboarding-learned'),
    path('onboarding/team/', ob.team, name='help-onboarding-team'),
    path('training/<str:kind>/<str:key>/', ob.training_edit, name='help-training-edit'),
    path('quizzes/<str:module_key>/', ob.quiz, name='help-quiz'),
    path('quizzes/<str:module_key>/submit/', ob.quiz_submit, name='help-quiz-submit'),
]
