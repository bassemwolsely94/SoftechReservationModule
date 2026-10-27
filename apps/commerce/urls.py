from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DocumentTypeViewSet, RecipientViewSet, CommerceDocumentViewSet, commerce_status,
)

router = DefaultRouter()
router.register('types',      DocumentTypeViewSet,     basename='commerce-types')
router.register('recipients', RecipientViewSet,        basename='commerce-recipients')
router.register('documents',  CommerceDocumentViewSet, basename='commerce-documents')

urlpatterns = [
    path('status/', commerce_status, name='commerce-status'),
] + router.urls
