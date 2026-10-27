from rest_framework.routers import DefaultRouter
from .views import (SupplierInvoiceViewSet, VendorProfileViewSet, InvoiceBatchViewSet,
                    PurchaseOrderViewSet)

router = DefaultRouter()
router.register('invoices',        SupplierInvoiceViewSet, basename='invoices')
router.register('invoice-batches', InvoiceBatchViewSet,    basename='invoice-batches')
router.register('purchase-orders', PurchaseOrderViewSet,   basename='purchase-orders')
router.register('vendors',         VendorProfileViewSet,   basename='vendors')

urlpatterns = router.urls
