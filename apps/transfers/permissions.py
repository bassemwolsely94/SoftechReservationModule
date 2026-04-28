from rest_framework.permissions import BasePermission


FULL_ACCESS_ROLES = ('admin', 'call_center', 'purchasing')
BRANCH_ROLES = ('pharmacist', 'salesperson')


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


class CanRespondToTransfer(BasePermission):
    """
    Only users belonging to the SOURCE branch can respond.
    Admins can respond to any.
    """
    message = 'فقط مستخدمو الفرع المصدر يمكنهم الرد على هذا الطلب'

    def has_object_permission(self, request, view, obj):
        profile = get_profile(request)
        if not profile:
            return False
        if profile.role == 'admin':
            return True
        return (
            profile.branch_id == obj.source_branch_id
            and profile.role in ('pharmacist', 'salesperson', 'call_center')
        )


class CanViewTransfer(BasePermission):
    """
    - Admin / purchasing / call_center: see all transfers
    - Branch staff: see only transfers where their branch is requesting OR source
    """
    message = 'ليس لديك صلاحية عرض هذا الطلب'

    def has_object_permission(self, request, view, obj):
        profile = get_profile(request)
        if not profile:
            return False
        if profile.role in FULL_ACCESS_ROLES:
            return True
        return (
            profile.branch_id == obj.requesting_branch_id
            or profile.branch_id == obj.source_branch_id
        )


class IsPurchasingOrAdmin(BasePermission):
    """For purchasing dashboard endpoints."""
    message = 'هذه الصفحة مخصصة لقسم المشتريات والمديرين فقط'

    def has_permission(self, request, view):
        profile = get_profile(request)
        if not profile:
            return False
        return profile.role in ('admin', 'purchasing')
