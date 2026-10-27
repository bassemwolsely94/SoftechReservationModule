from django.urls import path
from . import views

urlpatterns = [
    # ── Orders CRUD ──────────────────────────────────────────────────────────
    path('', views.DeliveryOrderListView.as_view()),
    path('<int:pk>/', views.DeliveryOrderDetailView.as_view()),

    # ── Order workflow actions ───────────────────────────────────────────────
    path('<int:pk>/assign/',      views.delivery_assign),
    path('<int:pk>/accept/',      views.delivery_accept),
    path('<int:pk>/dispatch/',    views.delivery_dispatch),
    path('<int:pk>/complete/',    views.delivery_complete),
    path('<int:pk>/partial/',     views.delivery_partial),
    path('<int:pk>/unavailable/', views.delivery_unavailable),
    path('<int:pk>/fail/',        views.delivery_fail),
    path('<int:pk>/cancel/',      views.delivery_cancel),
    path('<int:pk>/return/',      views.delivery_return),
    path('<int:pk>/close/',       views.delivery_close),
    path('<int:pk>/collect-cash/',views.delivery_collect_cash),
    path('<int:pk>/backfill/',    views.delivery_backfill),

    # ── Order enrichment ─────────────────────────────────────────────────────
    path('<int:pk>/items/',       views.delivery_order_items),
    path('<int:pk>/whatsapp/',    views.delivery_whatsapp_message),
    path('<int:pk>/csat/',        views.delivery_submit_csat),          # F14
    path('<int:pk>/tracking-link/', views.delivery_tracking_link),      # staff: share link

    # ── Public customer tracking (no auth) ───────────────────────────────────
    path('track/<str:token>/',    views.delivery_public_track),

    # ── Analytics & dashboards ───────────────────────────────────────────────
    path('summary/',             views.delivery_summary),
    path('dashboard/',           views.delivery_dashboard),
    path('driver-performance/',  views.driver_performance),             # F10
    path('area-heatmap/',        views.delivery_area_heatmap),          # F11
    path('shift-report/',        views.delivery_shift_report),          # F12
    path('csat-report/',         views.delivery_csat_report),           # F14

    # ── Tools & helpers ──────────────────────────────────────────────────────
    path('threshold/',           views.delivery_threshold_check),       # F4
    path('route-plan/',          views.delivery_route_plan),            # F5
    path('customer-profile/',    views.customer_delivery_profile),      # F13

    # ── Area fees (F9) ───────────────────────────────────────────────────────
    path('area-fees/',           views.DeliveryAreaFeeListView.as_view()),
    path('area-fees/<int:pk>/',  views.DeliveryAreaFeeDetailView.as_view()),

    # ── Drivers ──────────────────────────────────────────────────────────────
    path('drivers/',             views.DriverListView.as_view()),
    path('drivers/<int:pk>/',    views.DriverDetailView.as_view()),

    # ── Route batching (runs) ────────────────────────────────────────────────
    path('routes/',                   views.delivery_routes),
    path('routes/<int:pk>/',          views.delivery_route_detail),
    path('routes/<int:pk>/dispatch/', views.delivery_route_dispatch),

    # ── Driver App API (F6) ──────────────────────────────────────────────────
    path('app/my-orders/',                    views.driver_app_my_orders),
    path('app/my-route/',                     views.driver_app_my_route),
    path('app/orders/<int:pk>/location/',     views.driver_app_update_location),

    # ── Customer Locations ───────────────────────────────────────────────────
    path('customers/<int:customer_id>/locations/', views.CustomerLocationListView.as_view()),
    path('locations/<int:pk>/',                    views.CustomerLocationDetailView.as_view()),
]
