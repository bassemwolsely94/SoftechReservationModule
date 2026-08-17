from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    InsuranceClientViewSet, InsuranceSubClientViewSet,
    InsuranceContractViewSet, InsuranceClaimViewSet,
    InsuranceParentClientViewSet, InsuranceClaimBillingGroupViewSet,
    InsuranceCacheSyncView, InsuranceExportProfileViewSet,
    InsurancePivotTemplateViewSet, InsuranceItemClassificationOverrideViewSet,
)

router = DefaultRouter()
router.register('clients',        InsuranceClientViewSet,        basename='insurance-clients')
router.register('subclients',     InsuranceSubClientViewSet,     basename='insurance-subclients')
router.register('contracts',      InsuranceContractViewSet,      basename='insurance-contracts')
router.register('claims',         InsuranceClaimViewSet,         basename='insurance-claims')
router.register('parent-clients', InsuranceParentClientViewSet,  basename='insurance-parent-clients')
router.register('billing-groups', InsuranceClaimBillingGroupViewSet, basename='insurance-billing-groups')
router.register('export-profiles', InsuranceExportProfileViewSet, basename='insurance-export-profiles')
router.register('pivot-templates', InsurancePivotTemplateViewSet, basename='insurance-pivot-templates')
router.register('item-overrides',  InsuranceItemClassificationOverrideViewSet, basename='insurance-item-overrides')

urlpatterns = [
    path('sync-cache/', InsuranceCacheSyncView.as_view(), name='insurance-sync-cache'),
] + router.urls
