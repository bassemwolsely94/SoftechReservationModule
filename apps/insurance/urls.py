from django.urls import path
from rest_framework.routers import SimpleRouter
from apps.tax_invoicing.views import claim_fiscal_status
from .views import (
    InsuranceClientViewSet, InsuranceSubClientViewSet,
    InsuranceContractViewSet, InsuranceClaimViewSet,
    InsuranceParentClientViewSet, InsuranceClaimBillingGroupViewSet,
    InsuranceCacheSyncView, InsuranceExportProfileViewSet,
    InsurancePivotTemplateViewSet, InsuranceItemClassificationOverrideViewSet,
    InsuranceSeparationListViewSet, InsuranceRosterView, InsurancePortfolioView,
)

router = SimpleRouter()     # no API-root index page (Z-9c)
router.register('clients',        InsuranceClientViewSet,        basename='insurance-clients')
router.register('subclients',     InsuranceSubClientViewSet,     basename='insurance-subclients')
router.register('contracts',      InsuranceContractViewSet,      basename='insurance-contracts')
router.register('claims',         InsuranceClaimViewSet,         basename='insurance-claims')
router.register('parent-clients', InsuranceParentClientViewSet,  basename='insurance-parent-clients')
router.register('billing-groups', InsuranceClaimBillingGroupViewSet, basename='insurance-billing-groups')
router.register('export-profiles', InsuranceExportProfileViewSet, basename='insurance-export-profiles')
router.register('pivot-templates', InsurancePivotTemplateViewSet, basename='insurance-pivot-templates')
router.register('item-overrides',  InsuranceItemClassificationOverrideViewSet, basename='insurance-item-overrides')
router.register('separation-lists', InsuranceSeparationListViewSet, basename='insurance-separation-lists')

urlpatterns = [
    # Read-only link to the claim's tax documents (doc 36); the module itself is apps/tax_invoicing.
    path('claims/<int:pk>/fiscal-status/', claim_fiscal_status, name='insurance-claim-fiscal-status'),
    path('sync-cache/', InsuranceCacheSyncView.as_view(), name='insurance-sync-cache'),
    path('rosters/', InsuranceRosterView.as_view(), name='insurance-rosters'),
    path('portfolio/', InsurancePortfolioView.as_view(), name='insurance-portfolio'),
] + router.urls
