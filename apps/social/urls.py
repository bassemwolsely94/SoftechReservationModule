from django.urls import path
from apps.social import views

urlpatterns = [
    path('webhook/meta/', views.MetaGraphWebhookView.as_view(), name='social-webhook-meta'),
    path('webhook/telegram/', views.TelegramWebhookView.as_view(), name='social-webhook-telegram'),
    path('webhook/tiktok/', views.TikTokWebhookView.as_view(), name='social-webhook-tiktok'),
]
