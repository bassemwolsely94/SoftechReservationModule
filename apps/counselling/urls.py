from django.urls import path

from . import views

urlpatterns = [
    path('status/', views.StatusView.as_view()),
    path('assistant/<int:item_id>/', views.AssistantView.as_view()),
    path('cards/', views.CardHistory.as_view()),
    path('cards/preview/', views.CardPreview.as_view()),
    path('cards/send/', views.CardSend.as_view()),
    path('content/', views.ContentListCreate.as_view()),
    path('content/needs/', views.NeedsContent.as_view()),
    path('content/ai-draft/', views.ContentAiDraft.as_view()),
    path('content/<int:pk>/', views.ContentDetail.as_view()),
    path('content/<int:pk>/submit/', views.ContentSubmit.as_view()),
    path('content/<int:pk>/approve/', views.ContentApprove.as_view()),
    path('content/<int:pk>/retire/', views.ContentRetire.as_view()),
    path('content/<int:pk>/link/', views.ContentLink.as_view()),
    path('content/<int:pk>/unlink/', views.ContentUnlink.as_view()),
    path('content/<int:pk>/suggest-items/', views.ContentSuggestItems.as_view()),
    path('content/<int:pk>/versions/', views.ContentVersions.as_view()),
]
