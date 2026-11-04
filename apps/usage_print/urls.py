from django.urls import path

from . import views

urlpatterns = [
    path('sheet/', views.sheet_lookup, name='usage-print-sheet'),
    path('lines/<int:pk>/', views.line_action, name='usage-print-line'),
    path('sheets/<int:pk>/print/', views.sheet_print, name='usage-print-print'),
    path('sheets/<int:pk>/prescription/', views.sheet_prescription, name='usage-print-prescription'),
    path('settings/', views.settings_view, name='usage-print-settings'),
]
