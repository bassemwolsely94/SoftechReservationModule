from django.urls import path
from . import views

urlpatterns = [
    # ── Notification list & counts ────────────────────────────────────────────
    path('',                    views.notification_list,    name='notification-list'),
    path('unread-count/',       views.unread_count,         name='notification-unread-count'),
    path('category-counts/',    views.category_counts,      name='notification-category-counts'),

    # ── Bulk actions ──────────────────────────────────────────────────────────
    path('bulk/',               views.bulk_action,          name='notification-bulk'),
    path('mark-all-read/',      views.mark_all_read,        name='notification-mark-all-read'),
    path('delete-old/',         views.delete_old,           name='notification-delete-old'),
    path('clear-all/',          views.clear_all,            name='notification-clear-all'),

    # ── Preferences ───────────────────────────────────────────────────────────
    path('preferences/',        views.preferences,          name='notification-preferences'),

    # ── Web Push (VAPID) ──────────────────────────────────────────────────────
    path('push/vapid-public-key/', views.vapid_public_key,  name='push-vapid-public-key'),
    path('push/subscribe/',        views.push_subscribe,    name='push-subscribe'),
    path('push/unsubscribe/',      views.push_unsubscribe,  name='push-unsubscribe'),

    # ── Personal reminders ────────────────────────────────────────────────────
    path('reminders/',          views.reminders,            name='notification-reminders'),
    path('reminders/<int:pk>/', views.reminder_detail,      name='notification-reminder-detail'),

    # ── Announcements / internal broadcast ────────────────────────────────────
    path('announcements/',               views.announcements,        name='announcements'),
    path('announcements/<int:pk>/',      views.announcement_detail,  name='announcement-detail'),
    path('announcements/<int:pk>/ack/',  views.announcement_ack,     name='announcement-ack'),

    # ── Per-notification actions ──────────────────────────────────────────────
    path('<int:pk>/read/',      views.mark_read,            name='notification-mark-read'),
    path('<int:pk>/snooze/',    views.snooze_notification,  name='notification-snooze'),
    path('<int:pk>/',           views.delete_notification,  name='notification-delete'),

    # ── Chatter ───────────────────────────────────────────────────────────────
    path(
        'chatter/<str:model_name>/<int:record_id>/',
        views.chatter_list,
        name='chatter-list',
    ),
    path(
        'chatter/<str:model_name>/<int:record_id>/post/',
        views.chatter_post,
        name='chatter-post',
    ),
]
