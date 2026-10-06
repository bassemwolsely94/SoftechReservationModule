from django.urls import path
from apps.pbx import views

urlpatterns = [
    path('agents/', views.AgentExtensionListView.as_view(), name='pbx-agents'),
    path('agents/<int:pk>/', views.AgentExtensionDetailView.as_view(), name='pbx-agent-detail'),
    path('my-extension/', views.MyExtensionView.as_view(), name='pbx-my-extension'),
    path('queues/', views.QueueListView.as_view(), name='pbx-queues'),
    path('sessions/', views.CallSessionListView.as_view(), name='pbx-sessions'),
    path('sessions/<int:pk>/', views.CallSessionDetailView.as_view(), name='pbx-session-detail'),
    path('live/', views.LiveSessionsView.as_view(), name='pbx-live'),
    path('spy/', views.SpyView.as_view(), name='pbx-spy'),
    path('recordings/<int:pk>/', views.RecordingView.as_view(), name='pbx-recording'),
]
