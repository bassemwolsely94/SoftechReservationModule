from django.urls import path
from apps.omni import views

urlpatterns = [
    path('conversations/', views.ConversationListView.as_view(), name='omni-conversations'),
    path('conversations/<int:pk>/', views.ConversationDetailView.as_view(), name='omni-conversation-detail'),
    path('conversations/<int:conversation_id>/timeline/', views.TimelineListView.as_view(), name='omni-timeline'),
    path('conversations/<int:conversation_id>/reply/', views.ReplyView.as_view(), name='omni-reply'),
    path('accounts/', views.AccountListView.as_view(), name='omni-accounts'),
    path('accounts/<int:pk>/', views.AccountDetailView.as_view(), name='omni-account-detail'),
    path('accounts/<int:pk>/health/', views.AccountHealthView.as_view(), name='omni-account-health'),
    path('events/<int:pk>/transcribe/', views.TranscribeEventView.as_view(), name='omni-transcribe'),
    path('conversations/<int:pk>/ai-assist/', views.AIAssistView.as_view(), name='omni-ai-assist'),
    path('wallboard/', views.WallboardView.as_view(), name='omni-wallboard'),
    path('analytics/', views.AnalyticsView.as_view(), name='omni-analytics'),
    path('automations/', views.AutomationListView.as_view(), name='omni-automations'),
    path('automations/<int:pk>/', views.AutomationDetailView.as_view(), name='omni-automation-detail'),
    path('automation-runs/', views.AutomationRunsView.as_view(), name='omni-automation-runs'),
]
