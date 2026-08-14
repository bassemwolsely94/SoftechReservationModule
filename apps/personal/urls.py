"""apps/personal/urls.py — mounted at /api/personal/"""
from django.urls import path

from . import views

urlpatterns = [
    # person search (for claiming)
    path('persons/search/', views.persons_search, name='personal-persons-search'),

    # identity claims
    path('identities/', views.identities, name='personal-identities'),
    path('identities/pending/', views.identities_pending, name='personal-identities-pending'),
    path('identities/<int:pk>/', views.identity_detail, name='personal-identity-detail'),
    path('identities/<int:pk>/review/', views.identity_review, name='personal-identity-review'),

    # capabilities + document-comment write
    path('me/capabilities/', views.my_capabilities, name='personal-capabilities'),
    path('documents/comment/', views.set_document_comment, name='personal-doc-comment'),
    path('cheques/note/', views.set_cheque_note, name='personal-cheque-note'),
    path('revision/', views.set_revision, name='personal-revision'),

    # widgets
    path('widgets/catalog/', views.widgets_catalog, name='personal-widgets-catalog'),
    path('widgets/layout/', views.widgets_layout, name='personal-widgets-layout'),
    path('widgets/', views.widgets, name='personal-widgets'),
    path('widgets/<int:pk>/', views.widget_detail, name='personal-widget-detail'),
    path('widgets/<int:pk>/data/', views.widget_data, name='personal-widget-data'),
]
