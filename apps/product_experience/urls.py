"""
apps/product_experience/urls.py

Commerce Catalog + Product Experience Platform — URL routing.
All endpoints mounted under /api/products/
"""
from django.urls import path
from . import views

urlpatterns = [
    # ── Discovery ─────────────────────────────────────────────────────────────
    path('',                       views.product_list,          name='product-list'),
    path('search/',                views.product_search,        name='product-search'),
    path('popular/',               views.popular_products,      name='product-popular'),
    path('filter-options/',        views.product_filter_options, name='product-filter-options'),
    path('export/',                views.product_export,         name='product-export'),

    # ── Lookup aliases ────────────────────────────────────────────────────────
    path('slug/<slug:slug>/',      views.product_by_slug,       name='product-by-slug'),
    path('barcode/<str:barcode>/', views.product_by_barcode,    name='product-by-barcode'),

    # ── Product Card (lightweight embed) ──────────────────────────────────────
    path('card/<str:softech_id>/', views.product_card,          name='product-card'),

    # ── Admin (must be before wildcard) ───────────────────────────────────────
    path('bulk-initialize/',       views.bulk_initialize,       name='product-bulk-init'),

    # ── Full detail ───────────────────────────────────────────────────────────
    path('<str:softech_id>/',      views.product_detail,        name='product-detail'),

    # ── Availability ──────────────────────────────────────────────────────────
    path('<str:softech_id>/availability/',  views.product_availability,    name='product-availability'),

    # ── Media ─────────────────────────────────────────────────────────────────
    path('<str:softech_id>/media/',         views.product_media_list,      name='product-media-list'),
    path('<str:softech_id>/media/upload/',  views.product_media_upload,    name='product-media-upload'),
    path('<str:softech_id>/media/<int:media_pk>/', views.product_media_detail, name='product-media-detail'),

    # ── Content ───────────────────────────────────────────────────────────────
    path('<str:softech_id>/content/',       views.product_content,         name='product-content'),

    # ── Attributes ────────────────────────────────────────────────────────────
    path('<str:softech_id>/attributes/',    views.product_attributes,      name='product-attributes'),

    # ── SEO ───────────────────────────────────────────────────────────────────
    path('<str:softech_id>/seo/',           views.product_seo,             name='product-seo'),

    # ── Relations ─────────────────────────────────────────────────────────────
    path('<str:softech_id>/related/',               views.product_related,         name='product-related'),
    path('<str:softech_id>/related/add/',            views.product_add_relation,    name='product-relation-add'),
    path('<str:softech_id>/related/<int:relation_pk>/remove/', views.product_remove_relation, name='product-relation-remove'),

    # ── Recommendations ───────────────────────────────────────────────────────
    path('<str:softech_id>/recommend/',     views.product_recommend,       name='product-recommend'),

    # ── Tracking ─────────────────────────────────────────────────────────────
    path('<str:softech_id>/track/',         views.product_track,           name='product-track'),

    # ── Share card ────────────────────────────────────────────────────────────
    path('<str:softech_id>/share/',         views.product_share,           name='product-share'),

    # ── Similar items (same therapeutic class) ────────────────────────────────
    path('<str:softech_id>/similar/',       views.product_similar,         name='product-similar'),

    # ── Demand crosslink (open demands + shortage) ────────────────────────────
    path('<str:softech_id>/demand/',        views.product_demand,          name='product-demand'),

]
