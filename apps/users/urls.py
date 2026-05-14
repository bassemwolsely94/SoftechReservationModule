from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    login_view, refresh_view, me_view, change_password_view,
    StaffProfileViewSet, ERPUserViewSet, PermissionsMatrixView,
)

# ── Auth endpoints (mounted at /api/auth/) ─────────────────────────────────────
auth_urlpatterns = [
    path('login/',           login_view),
    path('refresh/',         refresh_view),
    path('me/',              me_view),
    path('change-password/', change_password_view),
]

# ── User management endpoints (mounted at /api/users/) ────────────────────────
router = DefaultRouter()
router.register(r'staff',       StaffProfileViewSet,   basename='staff')
router.register(r'erp-users',   ERPUserViewSet,        basename='erp-user')
router.register(r'permissions', PermissionsMatrixView, basename='permissions')

management_urlpatterns = router.urls
