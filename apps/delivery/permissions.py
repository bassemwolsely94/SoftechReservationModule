"""
Server-side permissions for the delivery API, from the RoleModuleAccess matrix
(module 'delivery'). Until 2026-10-26 every delivery endpoint only required a login, so
any staff member could cancel, close or record cash on any order; the UI hid buttons
but the API did not check (CLAUDE.md rule 9).

Each endpoint names the matrix action(s) it needs:
  read                                → view
  create an order                     → create
  edit an order / driver / fee        → edit (fees: delete to remove)
  assign a driver, build/dispatch runs→ assign
  rider steps (accept, out, delivered,
  partial, unavailable, failed, return)→ edit
  cancel                              → approve
  close, record cash                  → finalize or approve

Riders (a staff member linked to a DeliveryDriver) may always run the rider steps and
record cash on orders assigned to THEM, and — whatever the matrix says — never on
another rider's order. Admins bypass the matrix (as StaffProfile.can_do does).

Safety net, same as core.middleware.module_access: if the matrix was never seeded
(RoleModuleAccess empty) nothing is denied here, so a fresh install does not lock
everyone but admins out.
"""
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from core.permissions import matrix_allows

MODULE = 'delivery'
DENIED = 'ليس لديك صلاحية لهذا الإجراء في التوصيل'
NOT_YOURS = 'هذا الطلب غير مسند إليك'


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def driver_of(profile):
    """The DeliveryDriver linked to this staff member, or None."""
    return getattr(profile, 'driver_profile', None) if profile else None


def can(profile, *actions):
    """True when the matrix grants any of `actions` on delivery."""
    return matrix_allows(profile, MODULE, *actions)


def guard(request, *actions, order=None, rider_ok=False):
    """None when allowed, else a 403 Response.

    order    — the order acted on; a rider may only touch orders assigned to them.
    rider_ok — the order's own rider may do this even without the matrix grant.
    """
    profile = _profile(request)
    driver = driver_of(profile)
    if order is not None and driver is not None and profile.role != 'admin':
        own = order.assigned_driver_id == driver.pk
        if not own:
            return Response({'detail': NOT_YOURS}, status=status.HTTP_403_FORBIDDEN)
        if rider_ok:
            return None
    if can(profile, *actions):
        return None
    return Response({'detail': DENIED}, status=status.HTTP_403_FORBIDDEN)


class DeliveryModulePermission(BasePermission):
    """For the generic views: GET → view, POST → create, PUT/PATCH → edit, DELETE → delete."""
    message = DENIED
    BY_METHOD = {'POST': 'create', 'PUT': 'edit', 'PATCH': 'edit', 'DELETE': 'delete'}

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        action = 'view' if request.method in SAFE_METHODS else self.BY_METHOD.get(request.method, 'edit')
        return can(_profile(request), action)
