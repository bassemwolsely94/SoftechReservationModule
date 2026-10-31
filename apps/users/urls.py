from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import (
    login_view, refresh_view, me_view, change_password_view,
    StaffProfileViewSet, ERPUserViewSet, PermissionsMatrixView,
    my_permissions_view, unlock_login_view, forget_devices_admin_view,
)

# ── Auth endpoints (mounted at /api/auth/) ─────────────────────────────────────
auth_urlpatterns = [
    path('login/',           login_view),
    path('refresh/',         refresh_view),
    path('me/',              me_view),
    path('change-password/', change_password_view),
]

# ── User management endpoints (mounted at /api/users/) ────────────────────────
router = SimpleRouter()     # no API-root index page under /api/users/ (Z-4)
router.register(r'staff',       StaffProfileViewSet,   basename='staff')
router.register(r'erp-users',   ERPUserViewSet,        basename='erp-user')
router.register(r'permissions', PermissionsMatrixView, basename='permissions')

from . import erp_views

management_urlpatterns = router.urls + [
    path('my-permissions/', my_permissions_view, name='my-permissions'),
    path('<int:pk>/unlock-login/', unlock_login_view, name='unlock-login'),
    path('<int:pk>/forget-devices/', forget_devices_admin_view, name='forget-devices'),

    # ── SOFTECH permission inheritance ────────────────────────────────────────
    path('erp-permissions/me/',            erp_views.my_erp_permissions,  name='erp-perms-me'),
    path('erp-permissions/groups/',        erp_views.groups_overview,     name='erp-perms-groups'),
    path('erp-permissions/systems/',       erp_views.systems_overview,    name='erp-perms-systems'),
    path('erp-permissions/map/',           erp_views.system_map,          name='erp-perms-map'),
    path('erp-permissions/map/<int:pk>/',  erp_views.system_map_delete,   name='erp-perms-map-del'),
    path('erp-permissions/rebuild/',       erp_views.rebuild,             name='erp-perms-rebuild'),
]
