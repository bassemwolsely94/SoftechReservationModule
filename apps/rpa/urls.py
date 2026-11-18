from django.urls import include, path

from . import agent_views, views
from .portal import urls as portal_urls

urlpatterns = [
    # ── staff API (Task 9) ──
    path('jobs/', views.JobListCreateView.as_view()),
    path('jobs/<int:pk>/', views.job_detail),
    path('jobs/<int:pk>/approve/', views.job_approve),
    path('jobs/<int:pk>/cancel/', views.job_cancel),
    path('documents/<int:pk>/', views.document_detail),
    path('documents/<int:pk>/resolve/', views.document_resolve),
    path('recipes/', views.RecipeListCreateView.as_view()),
    path('recipes/<int:pk>/', views.recipe_edit),
    path('recipes/<int:pk>/approve/', views.recipe_approve),
    path('screens/<str:key>/', views.screen_enable),
    path('devices/', views.DeviceListCreateView.as_view()),
    path('devices/<int:pk>/revoke/', views.device_revoke),
    path('status/', views.rpa_status),
    # ── staff API end ──
    # Windows agent (device secret, runs as its operator): apps/rpa/agent_views.py
    path('agent/claim/', agent_views.ClaimView.as_view(), name='rpa-agent-claim'),
    path('agent/documents/<int:pk>/heartbeat/', agent_views.HeartbeatView.as_view(), name='rpa-agent-heartbeat'),
    path('agent/documents/<int:pk>/report/', agent_views.ReportView.as_view(), name='rpa-agent-report'),
    path('agent/runs/<int:pk>/screenshot/', agent_views.ScreenshotView.as_view(), name='rpa-agent-screenshot'),
    # supplier-portal robot: apps/rpa/portal/urls.py (staff API at portal/, agent at agent/portal/)
    path('portal/', include(portal_urls.urlpatterns)),
    path('agent/portal/', include(portal_urls.agent_urlpatterns)),
]
