from django.urls import path
from . import views
from . import shortage_views

urlpatterns = [
    # ── Demand engine ─────────────────────────────────────────────────────────
    path('runs/',        views.RunListView.as_view(),        name='purchasing-runs'),
    path('runs/latest/', views.latest_run,                   name='purchasing-run-latest'),
    path('runs/active/', views.active_run,                   name='purchasing-run-active'),
    path('summary/',     views.purchasing_summary,           name='purchasing-summary'),
    path('metrics/',     views.MetricsListView.as_view(),    name='purchasing-metrics'),
    path('aggregated/',  views.AggregatedListView.as_view(), name='purchasing-aggregated'),
    path('export/',      views.export_purchasing,            name='purchasing-export'),
    path('advanced-export/', views.advanced_export,          name='purchasing-advanced-export'),
    path('advanced-pivot-export/', views.advanced_pivot_export, name='purchasing-advanced-pivot-export'),
    path('trigger/',     views.trigger_run,                  name='purchasing-trigger'),
    path('catchup/',     views.catchup_sync,                 name='purchasing-catchup'),
    path('config/',      views.engine_config,                name='purchasing-config'),

    # ── Filter options (dropdown population) ─────────────────────────────────────
    path('filter-options/',
         views.filter_options,
         name='purchasing-filter-options'),

    # ── Module 13 — Lost Sales Intelligence ──────────────────────────────────
    path('lost-sales/run/',
         views.lost_sales_latest_run,
         name='purchasing-lost-sales-run'),
    path('lost-sales/summary/',
         views.lost_sales_summary,
         name='purchasing-lost-sales-summary'),

    # ── Module 2 — Transfer recommendations ──────────────────────────────────
    path('transfer-recs/',
         views.TransferRecommendationListView.as_view(),
         name='purchasing-transfer-recs'),
    path('transfer-recs/run/',
         views.transfer_rec_latest_run,
         name='purchasing-transfer-recs-run'),
    path('transfer-recs/summary/',
         views.transfer_rec_summary,
         name='purchasing-transfer-recs-summary'),
    path('transfer-recs/<int:pk>/status/',
         views.transfer_rec_update_status,
         name='purchasing-transfer-rec-status'),

    # ── Market shortage detector (نواقص السوق) ───────────────────────────────
    path('shortage/candidates/', shortage_views.shortage_candidates, name='shortage-candidates'),
    path('shortage/deltas/',     shortage_views.shortage_deltas,     name='shortage-deltas'),
    path('shortage/confirmed/',  shortage_views.shortage_confirmed,  name='shortage-confirmed'),
    path('shortage/dismissed/',  shortage_views.shortage_dismissed,  name='shortage-dismissed'),
    path('shortage/med-types/',  shortage_views.shortage_med_types,  name='shortage-med-types'),
    path('shortage/search/',     shortage_views.shortage_search,     name='shortage-search'),
    path('shortage/flag/',       shortage_views.shortage_flag,       name='shortage-flag'),
    path('shortage/unflag/',     shortage_views.shortage_unflag,     name='shortage-unflag'),
    path('shortage/dismiss/',    shortage_views.shortage_dismiss,    name='shortage-dismiss'),
    path('shortage/retrieve/',   shortage_views.shortage_retrieve,   name='shortage-retrieve'),
    path('shortage/export/',     shortage_views.shortage_export,     name='shortage-export'),
    path('shortage/whatsapp/',   shortage_views.shortage_whatsapp,   name='shortage-whatsapp'),
    path('shortage/suggest-matches/', shortage_views.shortage_suggest_matches, name='shortage-suggest-matches'),
    path('shortage/trends/',     shortage_views.shortage_trends,     name='shortage-trends'),
]
