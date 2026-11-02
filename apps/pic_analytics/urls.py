from django.urls import path

from . import views

urlpatterns = [
    path('access/', views.access_info),
    path('options/', views.filter_options),
    path('overview/', views.overview),
    path('pics/', views.pic_list),
    path('groups/<str:kind>/', views.group_list),
    path('retention/', views.retention),
    path('retention/overdue/', views.retention_overdue),
    path('calls/center/', views.calls_center),
    path('calls/missed/', views.calls_missed),
    path('calls/missed/rows/', views.calls_missed_rows),
    path('calls/missed/<int:call_id>/dial/', views.missed_dial),
    path('calls/missed/<int:call_id>/callback/', views.missed_callback),
    path('calls/unanswered/', views.calls_unanswered),
    path('numbers/', views.numbers_list),
    path('numbers/conversions/', views.numbers_conversions),
    path('numbers/label/', views.numbers_label),
    path('numbers/<int:number_id>/dial/', views.number_dial),
    path('export/', views.export),
    path('grants/', views.grants),
    path('grants/candidates/', views.grant_candidates),
    path('grants/<int:pk>/revoke/', views.grant_revoke),
]
