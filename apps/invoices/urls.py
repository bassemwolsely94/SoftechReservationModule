from rest_framework.routers import DefaultRouter
from .views import SupplierInvoiceViewSet, VendorProfileViewSet

router = DefaultRouter()
router.register('invoices', SupplierInvoiceViewSet, basename='invoices')
router.register('vendors',  VendorProfileViewSet,   basename='vendors')

urlpatterns = router.urls
