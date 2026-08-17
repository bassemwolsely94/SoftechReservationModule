from django.urls import path
from . import views

urlpatterns = [
    # ── Tasks CRUD ─────────────────────────────────────────────────────────────
    path('',          views.TaskListCreateView.as_view(),  name='tasks-list'),
    path('<int:pk>/', views.TaskDetailView.as_view(),      name='tasks-detail'),

    # ── Task actions ───────────────────────────────────────────────────────────
    path('<int:pk>/complete/', views.task_complete, name='tasks-complete'),
    path('<int:pk>/reopen/',   views.task_reopen,   name='tasks-reopen'),

    # ── Assignments ────────────────────────────────────────────────────────────
    path('<int:pk>/assignments/',              views.task_assignments,        name='tasks-assignments'),
    path('<int:pk>/assignments/<int:assignment_pk>/remove/',
                                               views.task_assignment_remove,  name='tasks-assignment-remove'),

    # ── Checklist items ────────────────────────────────────────────────────────
    path('<int:pk>/items/',               views.task_items,       name='tasks-items'),
    path('<int:pk>/items/<int:item_pk>/', views.task_item_detail, name='tasks-item-detail'),

    # ── Messages / Chatter ─────────────────────────────────────────────────────
    path('<int:pk>/messages/',                     views.task_messages,       name='tasks-messages'),
    path('<int:pk>/messages/<int:message_pk>/delete/', views.task_message_delete, name='tasks-message-delete'),

    # ── Attachments ────────────────────────────────────────────────────────────
    path('<int:pk>/attachments/',                  views.task_attachments,       name='tasks-attachments'),
    path('<int:pk>/attachments/<int:att_pk>/delete/', views.task_attachment_delete, name='tasks-attachment-delete'),

    # ── Audit log ──────────────────────────────────────────────────────────────
    path('<int:pk>/audit/',    views.task_audit_logs,   name='tasks-audit'),

    # ── Schedules ──────────────────────────────────────────────────────────────
    path('schedules/',          views.TaskScheduleListCreateView.as_view(), name='task-schedules-list'),
    path('schedules/<int:pk>/', views.TaskScheduleDetailView.as_view(),     name='task-schedules-detail'),
    path('schedules/<int:pk>/run/', views.schedule_run_now,                 name='task-schedules-run'),

    # ── Special views ──────────────────────────────────────────────────────────
    path('my/',        views.my_tasks,           name='tasks-mine'),
    path('dashboard/', views.task_dashboard,     name='tasks-dashboard'),
    path('options/',   views.task_filter_options, name='tasks-options'),
]
