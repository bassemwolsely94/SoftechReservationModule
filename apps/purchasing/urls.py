from django.urls import path
from . import views
from . import shortage_views
from . import phantom_views
from . import spike_views
from . import rate_writer_views
from . import isr_views
from . import branch_request_views

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
    path('sync-items/',  views.sync_items_now,               name='purchasing-sync-items'),
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

    # ── Phantom substitution detector (مبيعات وهمية) ─────────────────────────
    path('phantom/candidates/', phantom_views.phantom_candidates, name='phantom-candidates'),
    path('phantom/excluded/',   phantom_views.phantom_excluded,   name='phantom-excluded'),
    path('phantom/summary/',    phantom_views.phantom_summary,    name='phantom-summary'),
    path('phantom/med-types/',  phantom_views.phantom_med_types,  name='phantom-med-types'),
    path('phantom/confirm/',    phantom_views.phantom_confirm,    name='phantom-confirm'),
    path('phantom/exclude/',    phantom_views.phantom_exclude,    name='phantom-exclude'),
    path('phantom/reset/',      phantom_views.phantom_reset,      name='phantom-reset'),

    # ── /supply — Sales-rate writeback (Feature 1): معدل الإستهلاك → SOFTECH ───
    path('rates/pushes/',            rate_writer_views.pushes_list, name='rate-pushes'),
    path('rates/pushes/<int:pk>/',   rate_writer_views.push_detail, name='rate-push-detail'),
    path('rates/propose/',           rate_writer_views.propose,     name='rate-propose'),
    path('rates/pushes/<int:pk>/approve/', rate_writer_views.approve, name='rate-push-approve'),
    path('rates/pushes/<int:pk>/execute/', rate_writer_views.execute, name='rate-push-execute'),

    # ── /supply — ISR (طلب توريد) generation (Feature 2) ──────────────────────
    path('isr/pushes/',            isr_views.isr_list,    name='isr-pushes'),
    path('isr/pushes/<int:pk>/',   isr_views.isr_detail,  name='isr-push-detail'),
    path('isr/propose/',           isr_views.isr_propose, name='isr-propose'),
    path('isr/transfer-preview/',  isr_views.isr_transfer_preview, name='isr-transfer-preview'),
    path('isr/transfer/',          isr_views.isr_transfer, name='isr-transfer'),
    path('isr/distribution/',      isr_views.distribution_preview,  name='isr-distribution-preview'),
    path('isr/distribution/generate/', isr_views.distribution_generate, name='isr-distribution-generate'),
    path('isr/pushes/<int:pk>/approve/', isr_views.isr_approve, name='isr-push-approve'),
    path('isr/pushes/<int:pk>/push/',    isr_views.isr_push,    name='isr-push-push'),
    path('isr/fulfilment/',        isr_views.isr_fulfilment,        name='isr-fulfilment'),
    path('isr/fulfilment/export/', isr_views.isr_fulfilment_export, name='isr-fulfilment-export'),
    path('isr/fulfilment/recent/', isr_views.isr_fulfilment_recent, name='isr-fulfilment-recent'),
    path('isr/fulfilment/proposals/', isr_views.isr_fulfilment_proposals, name='isr-fulfilment-proposals'),
    # «طلبات واتساب» — branch requests pasted from WhatsApp groups
    path('isr/branch-requests/', branch_request_views.branch_requests, name='branch-requests'),
    path('isr/branch-requests/<int:pk>/', branch_request_views.branch_request_detail, name='branch-request'),
    path('isr/branch-requests/<int:pk>/text/', branch_request_views.branch_request_text),
    path('isr/branch-requests/<int:pk>/ocr/', branch_request_views.branch_request_ocr),
    path('isr/branch-requests/<int:pk>/lines/<int:lid>/', branch_request_views.branch_request_line),
    path('isr/branch-requests/<int:pk>/lines/<int:lid>/search/', branch_request_views.branch_request_search),
    path('isr/branch-requests/<int:pk>/confirm-safe/', branch_request_views.branch_request_confirm_safe),
    path('isr/branch-requests/<int:pk>/confirm/', branch_request_views.branch_request_confirm),
    path('isr/branch-requests/<int:pk>/cancel/', branch_request_views.branch_request_cancel),
    path('isr/branch-requests/<int:pk>/analysis/', branch_request_views.branch_request_analysis),
    path('isr/branch-requests/<int:pk>/analysis/export/', branch_request_views.branch_request_analysis_export),
    path('isr/branch-requests/<int:pk>/transfers/', branch_request_views.branch_request_transfers),

    # ── Demand-spike over-purchase detector (📈 ذروة الطلب) ───────────────────
    path('spike/candidates/', spike_views.spike_candidates, name='spike-candidates'),
    path('spike/summary/',    spike_views.spike_summary,    name='spike-summary'),
    path('spike/med-types/',  spike_views.spike_med_types,  name='spike-med-types'),
    path('spike/confirm/',    spike_views.spike_confirm,    name='spike-confirm'),
    path('spike/unconfirm/',  spike_views.spike_unconfirm,  name='spike-unconfirm'),
]
