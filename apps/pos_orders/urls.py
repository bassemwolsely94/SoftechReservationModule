from django.urls import path
from . import views

urlpatterns = [
    path('',                  views.OrderListCreateView.as_view(), name='pos-order-list'),
    path('reference/',        views.reference_data,                name='pos-order-reference'),
    path('batches/',          views.batch_availability_view,       name='pos-order-batches'),
    path('discount-suggest/', views.discount_suggest,              name='pos-order-discount-suggest'),
    path('points-preview/',   views.points_preview_view,           name='pos-order-points-preview'),
    path('customer-types/',   views.customer_types,                name='pos-order-customer-types'),
    path('contract-fields/',  views.contract_fields_view,          name='pos-order-contract-fields'),
    path('customer-entities/', views.customer_entities,            name='pos-order-customer-entities'),
    path('branch-stores/',    views.branch_stores_view,            name='pos-order-branch-stores'),
    path('salespeople/',      views.salespeople_view,              name='pos-order-salespeople'),
    path('queue-status/',     views.queue_status,                  name='pos-order-queue-status'),
    path('flush/',            views.flush_now,                     name='pos-order-flush'),
    path('<int:pk>/',         views.OrderDetailView.as_view(),     name='pos-order-detail'),
    path('<int:pk>/ready/',   views.ready_order,                   name='pos-order-ready'),
    path('<int:pk>/push/',    views.push_order,                    name='pos-order-push'),
    path('<int:pk>/cancel/',  views.cancel_order,                  name='pos-order-cancel'),
]
