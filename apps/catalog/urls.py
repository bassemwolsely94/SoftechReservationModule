from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, ItemViewSet,
    VariantGroupListCreateView, VariantGroupDetailView,
    add_variant_member, remove_variant_member,
    ProductBundleListCreateView, ProductBundleDetailView,
    add_bundle_item, remove_bundle_item,
    item_full_intel, item_ingredients, item_ingredient_delete,
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'', ItemViewSet, basename='item')

# Custom paths MUST come before router.urls so Django resolves them before
# the ItemViewSet detail pattern ^(?P<pk>[^/.]+)/$ can swallow 'variant-groups'
# or 'bundles' as a pk value.
urlpatterns = [
    # Variant groups — named literal paths must be before the <str:softech_id> wildcard
    path('variant-groups/',                         VariantGroupListCreateView.as_view(), name='variant-group-list'),
    path('variant-groups/<int:pk>/',                VariantGroupDetailView.as_view(),     name='variant-group-detail'),
    path('variant-groups/<int:group_pk>/members/',  add_variant_member,                   name='variant-member-add'),
    path('variant-groups/<int:group_pk>/members/<int:member_pk>/', remove_variant_member, name='variant-member-remove'),

    # Bundles
    path('bundles/',                          ProductBundleListCreateView.as_view(), name='bundle-list'),
    path('bundles/<int:pk>/',                 ProductBundleDetailView.as_view(),     name='bundle-detail'),
    path('bundles/<int:bundle_pk>/items/',    add_bundle_item,                       name='bundle-item-add'),
    path('bundles/<int:bundle_pk>/items/<int:bi_pk>/', remove_bundle_item,           name='bundle-item-remove'),

    # Item intelligence — softech_id wildcard AFTER all named paths to avoid shadowing
    path('<str:softech_id>/intel/',                          item_full_intel,         name='item-full-intel'),
    path('<str:softech_id>/ingredients/',                    item_ingredients,        name='item-ingredients'),
    path('<str:softech_id>/ingredients/<int:map_id>/',       item_ingredient_delete,  name='item-ingredient-delete'),
] + router.urls
