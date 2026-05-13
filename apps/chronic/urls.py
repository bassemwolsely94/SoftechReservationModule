from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    MedicationTagViewSet,
    ActiveIngredientViewSet,
    FollowUpProtocolViewSet,
    ItemIngredientMapViewSet,
    ItemClassifierViewSet,
    TaskGeneratorViewSet,
)

router = DefaultRouter()
router.register(r'tags',           MedicationTagViewSet,    basename='medication-tag')
router.register(r'ingredients',    ActiveIngredientViewSet, basename='active-ingredient')
router.register(r'protocols',      FollowUpProtocolViewSet, basename='followup-protocol')
router.register(r'item-maps',      ItemIngredientMapViewSet, basename='item-ingredient-map')
router.register(r'items',          ItemClassifierViewSet,   basename='item-classifier')
router.register(r'task-generator', TaskGeneratorViewSet,    basename='task-generator')

urlpatterns = [
    path('', include(router.urls)),
]
