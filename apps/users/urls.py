from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    login_view, refresh_view, me_view, change_password_view,
    StaffProfileViewSet, ERPUserViewSet, PermissionsMatrixView,
    my_permissions_view,
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

from . import erp_views

management_urlpatterns = router.urls + [
    path('my-permissions/', my_permissions_view, name='my-permissions'),

    # ── SOFTECH permission inheritance ────────────────────────────────────────
    path('erp-permissions/me/',            erp_views.my_erp_permissions,  name='erp-perms-me'),
    path('erp-permissions/groups/',        erp_views.groups_overview,     name='erp-perms-groups'),
    path('erp-permissions/systems/',       erp_views.systems_overview,    name='erp-perms-systems'),
    path('erp-permissions/map/',           erp_views.system_map,          name='erp-perms-map'),
    path('erp-permissions/map/<int:pk>/',  erp_views.system_map_delete,   name='erp-perms-map-del'),
    path('erp-permissions/rebuild/',       erp_views.rebuild,             name='erp-perms-rebuild'),
]
