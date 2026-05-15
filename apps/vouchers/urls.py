from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import VoucherViewSet, DocumentViewSet

router = DefaultRouter()
router.register('vouchers',  VoucherViewSet,  basename='vouchers')

# Documents use reference_code as lookup key, not pk
urlpatterns = router.urls + [
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
