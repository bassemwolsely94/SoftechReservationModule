"""
apps/finance/urls.py — Finance Intelligence Platform URL routing.
"""

from django.urls import path

from . import views
from . import recon_views

urlpatterns = [

    # ── A/P–A/R Reconciliation (سداد فواتير) — doc 23 ─────────────────────────
    path('reconciliation/dashboard/',   recon_views.reconciliation_dashboard,  name='recon-dashboard'),
    path('reconciliation/parties/',     recon_views.ReconPartyListView.as_view(),   name='recon-parties'),
    path('reconciliation/supplier-options/', recon_views.supplier_options, name='recon-supplier-options'),
    path('reconciliation/parties/<str:personcode>/ledger/',
                                        recon_views.party_ledger,              name='recon-party-ledger'),
    path('reconciliation/parties/<str:personcode>/timeline/',
                                        recon_views.party_timeline,            name='recon-party-timeline'),
    path('reconciliation/invoices/',    recon_views.InvoiceListView.as_view(),      name='recon-invoices'),
    path('reconciliation/invoices/<int:pk>/lines/', recon_views.invoice_lines_view, name='recon-invoice-lines'),
    path('reconciliation/payments/',    recon_views.PaymentListView.as_view(),      name='recon-payments'),
    path('reconciliation/candidates/',  recon_views.CandidateListView.as_view(),    name='recon-candidates'),
    path('reconciliation/exceptions/',  recon_views.ExceptionListView.as_view(),    name='recon-exceptions'),
    path('reconciliation/workbench/',   recon_views.reconciliation_workbench,  name='recon-workbench'),
    path('reconciliation/runs/',        recon_views.ReconRunListView.as_view(),     name='recon-runs'),
    # actions (Phase E) — mirror mutations only, no SOFTECH write
    path('reconciliation/candidates/<int:pk>/approve/', recon_views.approve_candidate_view, name='recon-approve'),
    path('reconciliation/candidates/<int:pk>/reject/',  recon_views.reject_candidate_view,  name='recon-reject'),
    path('reconciliation/candidates/bulk-approve/',     recon_views.bulk_approve_view,      name='recon-bulk-approve'),
    path('reconciliation/allocations/<int:pk>/reverse-softech/', recon_views.reverse_allocation_softech, name='recon-reverse-softech'),
    path('reconciliation/candidates/bulk-reject/',      recon_views.bulk_reject_view,       name='recon-bulk-reject'),
    path('reconciliation/candidates/groups/',           recon_views.candidate_groups_view,  name='recon-candidate-groups'),
    path('reconciliation/candidates/selection-action/', recon_views.selection_action_view,  name='recon-selection-action'),
    path('reconciliation/allocations/bulk-write-softech/', recon_views.bulk_write_softech, name='recon-bulk-write'),
    path('reconciliation/unpaid/',        recon_views.unpaid_report, name='recon-unpaid'),
    path('reconciliation/partial/',        recon_views.partial_report, name='recon-partial'),
    path('reconciliation/partial/export/', recon_views.partial_export, name='recon-partial-export'),
    path('reconciliation/unpaid/export/', recon_views.unpaid_export, name='recon-unpaid-export'),
    path('reconciliation/review/export/', recon_views.review_export, name='recon-review-export'),
    path('reconciliation/returns-chains/export/', recon_views.returns_chains_export, name='recon-returns-chains-export'),
    path('reconciliation/allocations/manual/',          recon_views.manual_allocate_view,   name='recon-manual-alloc'),
    path('reconciliation/allocations/<int:pk>/undo/',   recon_views.undo_allocation_view,   name='recon-undo-alloc'),
    path('reconciliation/allocations/<int:pk>/write-softech/', recon_views.write_allocation_softech, name='recon-write-softech'),


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
