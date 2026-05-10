from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.notification_list,    name='notification-list'),
    path('unread-count/',       views.unread_count,         name='notification-unread-count'),
    path('mark-all-read/',      views.mark_all_read,        name='notification-mark-all-read'),
    path('delete-old/',         views.delete_old,           name='notification-delete-old'),
    path('clear-all/',          views.clear_all,            name='notification-clear-all'),
    path('<int:pk>/read/',      views.mark_read,            name='notification-mark-read'),
    path('<int:pk>/',           views.delete_notification,  name='notification-delete'),
]
