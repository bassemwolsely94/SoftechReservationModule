from rest_framework.routers import SimpleRouter
from .views import (SupplierInvoiceViewSet, VendorProfileViewSet, InvoiceBatchViewSet,
                    PurchaseOrderViewSet)

router = SimpleRouter()     # no API-root index page (Z-7a)
router.register('invoices',        SupplierInvoiceViewSet, basename='invoices')
router.register('invoice-batches', InvoiceBatchViewSet,    basename='invoice-batches')
router.register('purchase-orders', PurchaseOrderViewSet,   basename='purchase-orders')
router.register('vendors',         VendorProfileViewSet,   basename='vendors')

urlpatterns = router.urls
