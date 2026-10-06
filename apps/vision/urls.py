from django.urls import path

from . import views

urlpatterns = [
    path('corpus-stats/',    views.corpus_stats,    name='vision-corpus-stats'),
    path('corpus-accuracy/', views.corpus_accuracy, name='vision-corpus-accuracy'),
]
