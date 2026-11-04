"""General-ledger routes — mounted at /api/finance/gl/ (finance-gl Task 8)."""
from django.urls import path

from . import drafting_views, views

urlpatterns = [
    path('groups/', views.groups, name='gl-groups'),
    path('accounts/', views.accounts, name='gl-accounts'),
    path('accounts/import/', views.accounts_import, name='gl-accounts-import'),
    path('accounts/<str:code>/', views.account_update, name='gl-account'),
    path('entries/', views.entries, name='gl-entries'),
    path('entries/approve/', views.entries_approve, name='gl-entries-approve'),
    path('entries/<int:pk>/', views.entry, name='gl-entry'),
    path('entries/<int:pk>/approve/', views.entry_approve, name='gl-entry-approve'),
    path('entries/<int:pk>/reverse/', views.entry_reverse, name='gl-entry-reverse'),
    path('reports/trial-balance/', views.report_trial_balance, name='gl-trial-balance'),
    path('reports/account-statement/', views.report_account_statement, name='gl-account-statement'),
    path('reports/statements/', views.report_statements, name='gl-statements'),
    path('reports/position/', views.report_position, name='gl-position'),
    path('reports/branch-pl/', views.report_branch_pl, name='gl-branch-pl'),
    path('reports/comparison/', views.report_comparison, name='gl-comparison'),
    path('drafting/run/', drafting_views.drafting_run, name='gl-drafting-run'),
    path('drafting/runs/', drafting_views.drafting_runs, name='gl-drafting-runs'),
    path('drafting/runs/<int:pk>/', drafting_views.drafting_run_detail, name='gl-drafting-run-detail'),
]
