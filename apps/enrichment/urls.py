from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ItemEnrichmentViewSet, EnrichmentSuggestionViewSet, EnrichmentBatchViewSet,
    completeness_report, item_enrichment_detail, generate_for_item, recompute_scores,
)

router = DefaultRouter()
router.register(r'enrichments', ItemEnrichmentViewSet, basename='item-enrichment')
router.register(r'suggestions', EnrichmentSuggestionViewSet, basename='enrichment-suggestion')
router.register(r'batches',     EnrichmentBatchViewSet,      basename='enrichment-batch')

urlpatterns = [
    path('', include(router.urls)),
    path('report/',                           completeness_report,   name='enrichment-report'),
    path('recompute-scores/',                 recompute_scores,      name='enrichment-recompute'),
    path('items/<int:item_pk>/',              item_enrichment_detail, name='enrichment-item-detail'),
    path('items/<int:item_pk>/generate/',     generate_for_item,     name='enrichment-generate'),
]
