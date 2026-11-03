from django.urls import path

from . import views

urlpatterns = [
    path('policies/', views.policies, name='phone-alerts-policies'),
    path('owners/', views.owners, name='phone-alerts-owners'),
    path('owners/<int:pk>/', views.owner_detail, name='phone-alerts-owner-detail'),
    path('branch-mobiles/', views.branch_mobiles, name='phone-alerts-branch-mobiles'),
    path('branch-mobiles/<int:branch_id>/test/', views.branch_mobile_test,
         name='phone-alerts-branch-mobile-test'),
    path('channel/', views.channel, name='phone-alerts-channel'),
    path('log/', views.log, name='phone-alerts-log'),
    path('log/<int:pk>/', views.log_detail, name='phone-alerts-log-detail'),
    path('switches/', views.switches, name='phone-alerts-switches'),
]
