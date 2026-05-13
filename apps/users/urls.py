from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import login_view, refresh_view, me_view, StaffProfileViewSet, ERPUserViewSet

# Auth endpoints (existing)
auth_urlpatterns = [
    path('login/',   login_view),
    path('refresh/', refresh_view),
    path('me/',      me_view),
]

# Management endpoints (Phase 9)
router = DefaultRouter()
router.register(r'staff',     StaffProfileViewSet, basename='staff')
router.register(r'erp-users', ERPUserViewSet,      basename='erp-user')

management_urlpatterns = router.urls
