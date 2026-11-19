from django.urls import path

from . import views

urlpatterns = [
    path('<int:pk>/', views.job_status, name='export-job'),
    path('<int:pk>/download/', views.job_download, name='export-job-download'),
]
