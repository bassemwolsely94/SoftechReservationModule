"""
apps/campaigns/urls.py
"""
from django.urls import path
from . import views

urlpatterns = [
    # Campaign CRUD
    path('',                  views.CampaignListCreateView.as_view(), name='campaign-list'),
    path('<int:pk>/',         views.CampaignDetailView.as_view(),     name='campaign-detail'),

    # Audience preview
    path('<int:pk>/preview-audience/', views.preview_audience,   name='campaign-preview-audience'),

    # Workflow actions
    path('<int:pk>/request-approval/', views.request_approval,   name='campaign-request-approval'),
    path('<int:pk>/approve/',          views.approve_campaign,   name='campaign-approve'),
    path('<int:pk>/reject/',           views.reject_campaign,    name='campaign-reject'),
    path('<int:pk>/queue/',            views.queue_campaign,     name='campaign-queue'),
    path('<int:pk>/cancel/',           views.cancel_campaign,    name='campaign-cancel'),

    # Messages
    path('<int:pk>/messages/',                          views.CampaignMessageListView.as_view(), name='campaign-messages'),
    path('<int:pk>/messages/<int:msg_pk>/status/',      views.update_message_status,             name='campaign-message-status'),

    # Stats
    path('<int:pk>/stats/',            views.campaign_stats,     name='campaign-stats'),
]
