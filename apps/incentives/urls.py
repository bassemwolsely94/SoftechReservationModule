from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    IncentiveProgramViewSet,
    IncentiveRuleViewSet,
    IncentiveTransactionViewSet,
    IncentiveSettlementViewSet,
    AdjustmentEntryViewSet,
    IncentiveCalculationLogViewSet,
    NearExpiryStockView,
    MyProgressView,
    SuggestItemsView,
    SalesTargetViewSet,
)

router = DefaultRouter()
router.register('programs',          IncentiveProgramViewSet,        basename='incentive-program')
router.register('rules',             IncentiveRuleViewSet,           basename='incentive-rule')
router.register('transactions',      IncentiveTransactionViewSet,    basename='incentive-transaction')
router.register('settlements',       IncentiveSettlementViewSet,     basename='incentive-settlement')
router.register('adjustments',       AdjustmentEntryViewSet,         basename='incentive-adjustment')
router.register('logs',              IncentiveCalculationLogViewSet, basename='incentive-log')
router.register('near-expiry-stock', NearExpiryStockView,            basename='near-expiry-stock')
router.register('targets',           SalesTargetViewSet,             basename='sales-target')

urlpatterns = [
    path('', include(router.urls)),
    path('my-progress/',   MyProgressView.as_view(),   name='my-incentive-progress'),
    path('suggest-items/', SuggestItemsView.as_view(),  name='incentive-suggest-items'),
]
