from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    IncentiveProgramViewSet,
    IncentiveRuleViewSet,
    IncentiveTransactionViewSet,
    IncentiveSettlementViewSet,
)

router = DefaultRouter()
router.register('programs',     IncentiveProgramViewSet,     basename='incentive-program')
router.register('rules',        IncentiveRuleViewSet,         basename='incentive-rule')
router.register('transactions', IncentiveTransactionViewSet,  basename='incentive-transaction')
router.register('settlements',  IncentiveSettlementViewSet,   basename='incentive-settlement')

urlpatterns = [
    path('', include(router.urls)),
]
