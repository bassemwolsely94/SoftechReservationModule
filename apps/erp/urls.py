from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ERPTransactionViewSet, LocalCustomerViewSet

router = DefaultRouter()
router.register(r'transactions',    ERPTransactionViewSet,  basename='erp-transaction')
router.register(r'local-customers', LocalCustomerViewSet,   basename='local-customer')

urlpatterns = [
    path('', include(router.urls)),
]
