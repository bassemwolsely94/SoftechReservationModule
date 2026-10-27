from django.urls import path

from . import views

urlpatterns = [
    path('me/', views.me),
    path('summary/', views.summary),
    path('findings/', views.findings),
    path('findings/export/', views.export_findings),
    path('findings/bulk-review/', views.bulk_review),
    path('findings/<int:pk>/', views.finding_detail),
    path('findings/<int:pk>/review/', views.review),
    path('by-user/', views.by_user),
    path('rules/', views.rules_list),
    path('rules/<str:code>/', views.rule_update),
    path('rules/<str:code>/overrides/<str:branch>/', views.override_update),
    path('access/', views.access_list),
    path('access/candidates/', views.access_candidates),
    path('access/<int:pk>/revoke/', views.access_revoke),
    path('refresh/', views.refresh),
    path('runs/', views.runs),
]
