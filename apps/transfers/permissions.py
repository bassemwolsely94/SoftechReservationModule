from rest_framework.permissions import BasePermission


def get_profile(request):
    try:
        return request.user.staff_profile
    except Exception:
        return None


class CanCreateTransfer(BasePermission):
    """
    Any authenticated branch staff, call center, or admin can create transfers.
    Viewers cannot.
    """
    message = 'ليس لديك صلاحية إنشاء طلب تحويل'

    def has_permission(self, request, view):
        profile = get_profile(request)
        if not profile:
            return False
        return profile.role in ('admin', 'call_center', 'pharmacist', 'salesperson')
