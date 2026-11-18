"""Portal routes. `urlpatterns` is mounted at /api/rpa/portal/ (the staff API, Task 10);
`agent_urlpatterns` at /api/rpa/agent/portal/ (the robot, device secret)."""
from django.urls import path

from . import agent_views, views

urlpatterns = [
    path('portals/', views.portal_list),
    path('portals/<str:key>/', views.portal_edit),
    path('accounts/', views.AccountListView.as_view()),
    path('accounts/<int:pk>/', views.account_edit),
    path('buylists/', views.buylist_list),
    path('buylists/from-pivot/', views.buylist_from_pivot),
    path('buylists/from-isr/', views.buylist_from_isr),
    path('buylists/upload/', views.buylist_upload),
    path('buylists/<int:pk>/', views.buylist_detail),
    path('buylists/<int:pk>/pick/', views.buylist_pick),
    path('buylists/<int:pk>/send-other/', views.buylist_send_other),
    path('jobs/', views.job_list),
    path('jobs/<int:pk>/', views.portal_job_detail),
    path('jobs/<int:pk>/approve/', views.portal_job_approve),
    path('jobs/<int:pk>/cancel/', views.portal_job_cancel),
    path('discovery/confirm/', views.discovery_confirm),
    path('discovery/none/', views.discovery_none),
    path('discovery/<int:job_id>/', views.discovery_job),
    path('baskets/', views.basket_list),
    path('baskets/<int:pk>/', views.portal_basket_detail),
    path('baskets/<int:pk>/resolve/', views.portal_basket_resolve),
    path('baskets/<int:pk>/history-check/', views.portal_basket_history_check),
    path('remainders/', views.remainder_list),
]

agent_urlpatterns = [
    path('claim/', agent_views.ClaimView.as_view(), name='rpa-portal-agent-claim'),
    path('runs/<int:pk>/heartbeat/', agent_views.HeartbeatView.as_view(), name='rpa-portal-agent-heartbeat'),
    path('runs/<int:pk>/report/', agent_views.ReportView.as_view(), name='rpa-portal-agent-report'),
    path('runs/<int:pk>/screenshot/', agent_views.ScreenshotView.as_view(), name='rpa-portal-agent-screenshot'),
]
