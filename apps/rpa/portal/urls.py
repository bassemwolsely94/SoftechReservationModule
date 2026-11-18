"""Portal routes. `urlpatterns` is mounted at /api/rpa/portal/ (the staff API, Task 10);
`agent_urlpatterns` at /api/rpa/agent/portal/ (the robot, device secret)."""
from django.urls import path

from . import agent_views

urlpatterns = []

agent_urlpatterns = [
    path('claim/', agent_views.ClaimView.as_view(), name='rpa-portal-agent-claim'),
    path('runs/<int:pk>/heartbeat/', agent_views.HeartbeatView.as_view(), name='rpa-portal-agent-heartbeat'),
    path('runs/<int:pk>/report/', agent_views.ReportView.as_view(), name='rpa-portal-agent-report'),
    path('runs/<int:pk>/screenshot/', agent_views.ScreenshotView.as_view(), name='rpa-portal-agent-screenshot'),
]
