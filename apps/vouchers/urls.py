from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import VoucherViewSet, DocumentViewSet, coupon_check
from . import coupon_views as cv

router = DefaultRouter()
router.register('vouchers',  VoucherViewSet,  basename='vouchers')

# Documents use reference_code as lookup key, not pk
urlpatterns = router.urls + [
    path('coupons/check/', coupon_check, name='coupon-check'),
    # Gift-coupon screen (coupon_views.py — view / manage roles enforced there)
    path('coupons/overview/', cv.overview, name='coupon-overview'),
    path('coupons/serial/', cv.serial_lookup, name='coupon-serial'),
    path('coupons/customers/', cv.customers, name='coupon-customers'),
    path('coupons/no-serial/', cv.no_serial, name='coupon-no-serial'),
    path('coupons/sync/', cv.sync_now, name='coupon-sync'),
    path('coupons/batches/', cv.batches, name='coupon-batches'),
    path('coupons/batches/<int:pk>/export/', cv.batch_export, name='coupon-batch-export'),
    path('coupons/batches/<int:pk>/probe/', cv.batch_probe, name='coupon-batch-probe'),
    path('coupons/batches/<int:pk>/push/', cv.batch_push, name='coupon-batch-push'),
    path('coupons/batches/<int:pk>/verify/', cv.batch_verify, name='coupon-batch-verify'),
    path(
        'documents/<str:reference_code>/',
        DocumentViewSet.as_view({'get': 'retrieve'}),
        name='document-detail',
    ),
    path(
        'documents/<str:reference_code>/mark-used/',
        DocumentViewSet.as_view({'post': 'mark_used'}),
        name='document-mark-used',
    ),
    path(
        'documents/<str:reference_code>/print/',
        DocumentViewSet.as_view({'get': 'print_receipt'}),
        name='document-print',
    ),
    path(
        'documents/<str:reference_code>/whatsapp/',
        DocumentViewSet.as_view({'post': 'share_whatsapp'}),
        name='document-whatsapp',
    ),
]
