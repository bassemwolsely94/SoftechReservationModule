from django.urls import path

from . import agent_views

urlpatterns = [
    # Windows agent (device secret, runs as its operator): apps/rpa/agent_views.py
    path('agent/claim/', agent_views.ClaimView.as_view(), name='rpa-agent-claim'),
    path('agent/documents/<int:pk>/heartbeat/', agent_views.HeartbeatView.as_view(), name='rpa-agent-heartbeat'),
    path('agent/documents/<int:pk>/report/', agent_views.ReportView.as_view(), name='rpa-agent-report'),
    path('agent/runs/<int:pk>/screenshot/', agent_views.ScreenshotView.as_view(), name='rpa-agent-screenshot'),
]
