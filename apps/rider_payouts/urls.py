"""/api/delivery/payouts/ — rider payout ledger (C22 / P-48). Module 'delivery' (module_access)."""
from django.urls import path

from . import views

urlpatterns = [
    path('rides/', views.rides, name='rider-payout-rides'),
    path('rides/<int:pk>/void/', views.ride_void, name='rider-payout-ride-void'),
    path('periods/', views.periods, name='rider-payout-periods'),
    path('periods/export/', views.periods_export, name='rider-payout-periods-export'),
    path('periods/<int:pk>/', views.period_detail, name='rider-payout-period'),
    path('periods/<int:pk>/finalize/', views.period_finalize, name='rider-payout-period-finalize'),
    path('periods/<int:pk>/unlock/', views.period_unlock, name='rider-payout-period-unlock'),
    path('periods/<int:pk>/adjustments/', views.period_adjustments, name='rider-payout-period-adjustments'),
    path('adjustments/<int:pk>/remove/', views.adjustment_remove, name='rider-payout-adjustment-remove'),
    path('build/', views.build, name='rider-payout-build'),
    path('rule/', views.rule, name='rider-payout-rule'),
]
