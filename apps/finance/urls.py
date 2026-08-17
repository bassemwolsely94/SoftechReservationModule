"""
apps/finance/urls.py — Finance Intelligence Platform URL routing.
"""

from django.urls import path

from . import views

urlpatterns = [

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path('dashboard/',              views.finance_dashboard,            name='finance-dashboard'),

    # ── Periods ───────────────────────────────────────────────────────────────
    path('periods/',                views.FinancialPeriodListView.as_view(), name='finance-periods'),

    # ── Chart of Accounts ────────────────────────────────────────────────────
    path('accounts/',               views.AccountListView.as_view(),    name='finance-accounts'),
    path('accounts/tree/',          views.account_tree,                 name='finance-accounts-tree'),

    # ── Snapshots ─────────────────────────────────────────────────────────────
    path('snapshots/',              views.FinancialSnapshotListView.as_view(), name='finance-snapshots'),

    # ── P&L ───────────────────────────────────────────────────────────────────
    path('pnl/',                    views.profit_and_loss,              name='finance-pnl'),

    # ── Journal ───────────────────────────────────────────────────────────────
    path('journal/',                views.JournalEntryListView.as_view(),   name='finance-journal'),
    path('journal/<int:pk>/',       views.JournalEntryDetailView.as_view(), name='finance-journal-detail'),

    # ── Trial Balance ─────────────────────────────────────────────────────────
    path('trial-balance/',          views.trial_balance,                name='finance-trial-balance'),
    path('account-balances/',       views.AccountBalanceListView.as_view(), name='finance-account-balances'),

    # ── Treasury / Cash Flow ─────────────────────────────────────────────────
    path('treasury/',               views.TreasuryMovementListView.as_view(), name='finance-treasury'),
    path('cash-flow/',              views.cash_flow_summary,            name='finance-cash-flow'),

    # ── Expenses ─────────────────────────────────────────────────────────────
    path('expenses/',               views.ExpenseRecordListView.as_view(),  name='finance-expenses'),
    path('expenses/breakdown/',     views.expense_breakdown,               name='finance-expense-breakdown'),
    path('expenses/subcategories/', views.expense_subcategories,           name='finance-expense-subcategories'),

    # ── Schema Discovery ─────────────────────────────────────────────────────
    path('schema/',                 views.FinanceSchemaTableListView.as_view(), name='finance-schema'),
    path('schema/<int:pk>/',        views.FinanceSchemaTableDetailView.as_view(), name='finance-schema-detail'),

    # ── Sync Triggers ─────────────────────────────────────────────────────────
    path('trigger-discover/',       views.trigger_discover,             name='finance-trigger-discover'),
    path('trigger-sync/',           views.trigger_sync,                 name='finance-trigger-sync'),

    # ── Sync Run History ─────────────────────────────────────────────────────
    path('sync-runs/',              views.FinanceSyncRunListView.as_view(), name='finance-sync-runs'),
]
