from rest_framework.routers import DefaultRouter
from .views import SupplierInvoiceViewSet

router = DefaultRouter()
router.register('invoices', SupplierInvoiceViewSet, basename='invoices')

urlpatterns = router.urls
