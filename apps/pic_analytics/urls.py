from django.urls import path

from . import views

urlpatterns = [
    path('grants/', views.grants),
    path('grants/candidates/', views.grant_candidates),
    path('grants/<int:pk>/revoke/', views.grant_revoke),
]
