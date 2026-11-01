"""apps/help/urls.py — mounted at /api/help/"""
from django.urls import path

from . import glossary
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
    path('journeys/<str:jid>/', views.journey_detail, name='help-journey'),
    path('onboarding/', ob.my_path, name='help-onboarding'),
    path('onboarding/learned/', ob.mark_learned, name='help-onboarding-learned'),
    path('product-tour/', ob.product_tour, name='help-product-tour'),
    path('onboarding/team/', ob.team, name='help-onboarding-team'),
    path('onboarding/remind/', ob.remind, name='help-onboarding-remind'),
    path('first-day/', ob.first_day, name='help-first-day'),
    path('whats-new/', ob.whats_new, name='help-whats-new'),
    path('notes-log/', ob.notes_log, name='help-notes-log'),
    path('notes-check/', ob.notes_check, name='help-notes-check'),
    path('glossary/', glossary.glossary, name='help-glossary'),
    path('glossary/<int:pk>/', glossary.glossary_term, name='help-glossary-term'),
    path('glossary/scan/', glossary.scan, name='help-glossary-scan'),
    path('training/<str:kind>/<str:key>/', ob.training_edit, name='help-training-edit'),
    path('quizzes/<str:module_key>/', ob.quiz, name='help-quiz'),
    path('quizzes/<str:module_key>/submit/', ob.quiz_submit, name='help-quiz-submit'),
]
