from django.urls import path

from . import agent_views, views

urlpatterns = [
    # view level
    path('me/', views.me, name='hr-attendance-me'),
    path('month/', views.month, name='hr-attendance-month'),
    path('month/export/', views.month_export, name='hr-attendance-month-export'),
    path('employees/', views.employees, name='hr-attendance-employees'),
    path('employees/<int:pk>/days/', views.employee_days, name='hr-attendance-employee-days'),
    path('issues/', views.issues_view, name='hr-attendance-issues'),
    path('unknown-ids/', views.unknown_ids, name='hr-attendance-unknown-ids'),
    path('devices/', views.devices, name='hr-attendance-devices'),
    # manage level
    path('employees/<int:pk>/', views.employee_edit, name='hr-attendance-employee-edit'),
    path('employees/<int:pk>/link/', views.employee_link, name='hr-attendance-employee-link'),
    path('employees/<int:pk>/reject-link/', views.employee_reject_link, name='hr-attendance-employee-reject-link'),
    path('employees/<int:pk>/unlink/', views.employee_unlink, name='hr-attendance-employee-unlink'),
    path('employees/<int:pk>/hold/', views.employee_hold, name='hr-attendance-employee-hold'),
    path('generic-login/', views.generic_login, name='hr-attendance-generic-login'),
    path('not-generic-login/', views.not_generic_login, name='hr-attendance-not-generic-login'),
    path('unknown-ids/<str:code>/create-employee/', views.unknown_create_employee,
         name='hr-attendance-unknown-create'),
    path('unknown-ids/<str:code>/ignore/', views.unknown_ignore, name='hr-attendance-unknown-ignore'),
    path('unknown-ids/<str:code>/unignore/', views.unknown_unignore, name='hr-attendance-unknown-unignore'),
    path('conflicts/<str:code>/confirm/', views.conflict_confirm, name='hr-attendance-conflict-confirm'),
    path('collect-now/', views.collect_now, name='hr-attendance-collect-now'),
    # admin only
    path('devices/<int:pk>/', views.device_edit, name='hr-attendance-device-edit'),
    path('agents/', views.agents, name='hr-attendance-agents'),
    path('agents/issue/', views.agent_issue, name='hr-attendance-agent-issue'),
    path('agents/<int:pk>/revoke/', views.agent_revoke, name='hr-attendance-agent-revoke'),
    path('grants/', views.grants, name='hr-attendance-grants'),
    path('grants/<int:pk>/revoke/', views.grant_revoke, name='hr-attendance-grant-revoke'),
    # the office agent (its own secret, not a staff login)
    path('agent/config/', agent_views.AgentConfigView.as_view(), name='hr-attendance-agent-config'),
    path('agent/punches/', agent_views.AgentPunchesView.as_view(), name='hr-attendance-agent-punches'),
    path('agent/roster/', agent_views.AgentRosterView.as_view(), name='hr-attendance-agent-roster'),
    path('agent/runs/', agent_views.AgentRunsView.as_view(), name='hr-attendance-agent-runs'),
]
