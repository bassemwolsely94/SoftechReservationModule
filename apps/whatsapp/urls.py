from django.urls import path
from apps.whatsapp import views

urlpatterns = [
    # Webhook (public)
    path('webhook/', views.WebhookView.as_view(), name='wa-webhook'),

    # Conversations
    path('conversations/', views.ConversationListView.as_view(), name='wa-conversations'),
    path('conversations/<int:pk>/', views.ConversationDetailView.as_view(), name='wa-conversation-detail'),

    # Messages
    path('conversations/<int:conversation_id>/messages/', views.MessageListView.as_view(), name='wa-messages'),
    path('conversations/<int:conversation_id>/send/', views.SendTextView.as_view(), name='wa-send-text'),
    path('conversations/<int:conversation_id>/send-template/', views.SendTemplateView.as_view(), name='wa-send-template'),

    # Templates
    path('templates/', views.TemplateListView.as_view(), name='wa-templates'),
]
