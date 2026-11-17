from django.urls import path

from . import views

urlpatterns = [
    # ── staff API (Task 9) ──
    path('jobs/', views.JobListCreateView.as_view()),
    path('jobs/<int:pk>/', views.job_detail),
    path('jobs/<int:pk>/approve/', views.job_approve),
    path('jobs/<int:pk>/cancel/', views.job_cancel),
    path('documents/<int:pk>/', views.document_detail),
    path('documents/<int:pk>/resolve/', views.document_resolve),
    path('recipes/', views.RecipeListCreateView.as_view()),
    path('recipes/<int:pk>/approve/', views.recipe_approve),
    path('devices/', views.DeviceListCreateView.as_view()),
    path('devices/<int:pk>/revoke/', views.device_revoke),
    path('status/', views.rpa_status),
    # ── staff API end ──
]
