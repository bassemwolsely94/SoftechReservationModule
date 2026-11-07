from django.urls import path

from . import agent_views, views

urlpatterns = [
    path('me/', views.me, name='hr-attendance-me'),
    path('agent/config/', agent_views.AgentConfigView.as_view(), name='hr-attendance-agent-config'),
    path('agent/punches/', agent_views.AgentPunchesView.as_view(), name='hr-attendance-agent-punches'),
    path('agent/roster/', agent_views.AgentRosterView.as_view(), name='hr-attendance-agent-roster'),
    path('agent/runs/', agent_views.AgentRunsView.as_view(), name='hr-attendance-agent-runs'),
]
