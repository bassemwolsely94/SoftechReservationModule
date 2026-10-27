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
    path('dial/', views.DialView.as_view(), name='pbx-dial'),
    path('status/', views.BridgeStatusView.as_view(), name='pbx-status'),
    path('diagnostics/', views.DiagnosticsView.as_view(), name='pbx-diagnostics'),
    path('extensions/status/', views.ExtensionStatusView.as_view(), name='pbx-extension-status'),
    path('extensions/map/', views.ExtensionMapView.as_view(), name='pbx-extension-map'),
    path('staff-choices/', views.StaffChoicesView.as_view(), name='pbx-staff-choices'),
    path('spy/', views.SpyView.as_view(), name='pbx-spy'),
    path('recordings/<int:pk>/', views.RecordingView.as_view(), name='pbx-recording'),
]
