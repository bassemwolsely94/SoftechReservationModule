"""
apps/cheques/urls.py
"""
from django.urls import path
from . import views

urlpatterns = [
    # Calendar
    path('holidays/',                  views.HolidayListView.as_view(),   name='cheque-holidays'),

    # Plan preview (no DB write)
    path('preview/',                   views.preview_cheque_plan,         name='cheque-preview'),

    # Treasury dashboard
    path('treasury/',                  views.treasury_dashboard,          name='cheque-treasury'),

    # Plans CRUD
    path('plans/',                     views.PlanListCreateView.as_view(), name='cheque-plan-list'),
    path('plans/<int:pk>/',            views.PlanDetailView.as_view(),    name='cheque-plan-detail'),

    # Plan workflow
    path('plans/<int:pk>/activate/',   views.activate_plan,               name='cheque-plan-activate'),
    path('plans/<int:pk>/cancel/',     views.cancel_plan,                 name='cheque-plan-cancel'),

    # Instalment update
    path('plans/<int:plan_pk>/instalments/<int:inst_pk>/',
         views.update_instalment, name='cheque-instalment-update'),
]
