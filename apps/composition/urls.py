from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import (
    SoftechIngredientRawViewSet, IngredientParseCandidateViewSet,
    IngredientClassViewSet, IngredientSearchViewSet,
)

router = DefaultRouter()
router.register(r'raw',        SoftechIngredientRawViewSet,      basename='ai-raw')
router.register(r'candidates', IngredientParseCandidateViewSet,  basename='ai-candidate')
router.register(r'classes',    IngredientClassViewSet,           basename='ai-class')
router.register(r'search',     IngredientSearchViewSet,          basename='ai-search')

urlpatterns = [
    path('', include(router.urls)),
]
