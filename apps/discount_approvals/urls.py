from django.urls import path
from . import views

urlpatterns = [
    # ── Requests ──────────────────────────────────────────────────────────────
    path('',                                views.RequestListCreateView.as_view(), name='da-list'),
    path('<int:pk>/',                       views.RequestDetailView.as_view(),     name='da-detail'),
    path('<int:pk>/approve/',               views.approve_request,                 name='da-approve'),
    path('<int:pk>/reject/',                views.reject_request,                  name='da-reject'),
    path('<int:pk>/rollback/',              views.rollback_request,                name='da-rollback'),
    path('<int:pk>/replication/',           views.request_replication,             name='da-req-repl'),
    path('<int:pk>/force-replication/',     views.request_force_replication,       name='da-req-force-repl'),

    # ── Helpers ───────────────────────────────────────────────────────────────
    path('items/<str:softech_id>/prices/',  views.item_current_prices,            name='da-item-prices'),
    path('preview/',                        views.price_preview,                   name='da-preview'),
    path('approver-info/',                  views.approver_softech_info,           name='da-approver-info'),
    path('pending-count/',                  views.pending_count,                   name='da-pending-count'),
    path('sla/',                            views.sla_dashboard,                   name='da-sla'),
    path('import/',                         views.import_requests,                 name='da-import'),

    # ── Replication audit & repair ────────────────────────────────────────────
    path('replication/scan/',               views.run_replication_scan,           name='da-repl-scan'),
    path('replication/scans/',              views.replication_scans,              name='da-repl-scans'),
    path('replication/scans/<int:pk>/',     views.replication_scan_detail,        name='da-repl-scan-detail'),
    path('replication/repair/',             views.repair_gaps,                     name='da-repl-repair'),
    path('replication/item/<str:softech_id>/', views.item_replication_status,     name='da-repl-item'),

    # ── Insights & policy (features #4/#5/#8/#11) ─────────────────────────────
    path('branch-health/',                  views.branch_health,                  name='da-branch-health'),
    path('who-changed-what/',               views.who_changed_what,               name='da-who-changed'),
    path('discount-impact/',                views.discount_impact,                name='da-discount-impact'),
    path('policy/',                         views.replication_policy,             name='da-policy'),
    path('history/<str:softech_id>/',       views.price_history,                  name='da-price-history'),

    # ── Discount-alignment audit ──────────────────────────────────────────────
    path('alignment/',          views.alignment_scan,     name='da-alignment'),
    path('alignment/policies/', views.alignment_policies, name='da-alignment-policies'),
    path('alignment/tiers/',    views.alignment_tiers,    name='da-alignment-tiers'),
    path('alignment/apply/',    views.alignment_apply,    name='da-alignment-apply'),
    path('alignment/tier-preview/', views.alignment_tier_preview, name='da-alignment-tier-preview'),
    path('alignment/tier-create/',  views.alignment_tier_create,  name='da-alignment-tier-create'),
]
