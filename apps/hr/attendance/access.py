"""
apps/hr/attendance/access.py — who may open HR Attendance (server-side).

Attendance is COMPANY-LEVEL by decision (2026-11-07): it is not branch-scoped. It is seen only by
admins and by NAMED grantees (an active AttendanceAccess row, level view or manage). The ordinary
`hr` self-service module (leave / permit requests) never opens it.

  • admin                      → everything (view, export, manage, admin)
  • RBAC `hr_attendance` view  → view + export (seeded for no role but admin)
  • grant level 'view'         → view + export
  • grant level 'manage'       → view + export + manage
  • can_admin (grants, agent tokens, device setup) → admin only
"""
MODULE = 'hr_attendance'


def _profile(user_or_request):
    user = getattr(user_or_request, 'user', user_or_request)
    return getattr(user, 'staff_profile', None)


def active_grant(profile):
    if not profile:
        return None
    from apps.hr.models import AttendanceAccess
    return AttendanceAccess.objects.filter(staff=profile, revoked_at__isnull=True).first()


class Access:
    """Resolved once per request."""

    def __init__(self, user_or_request):
        p = _profile(user_or_request)
        self.profile = p
        active = bool(p and p.is_active)
        is_admin = active and p.role == 'admin'
        grant = active_grant(p) if active and not is_admin else None
        rbac_view = bool(active and not is_admin and p.can_do(MODULE, 'view'))
        self.can_admin = is_admin
        self.can_manage = is_admin or bool(grant and grant.level == 'manage')
        self.can_view = is_admin or rbac_view or bool(grant)
        self.can_export = self.can_view

    def as_dict(self):
        return {'can_view': self.can_view, 'can_export': self.can_export,
                'can_manage': self.can_manage, 'can_admin': self.can_admin}


def can_open(user):
    """For the sidebar flag on /api/auth/me/."""
    return Access(user).can_view


def manager_recipients():
    """Staff who get attendance alerts: active admins plus active 'manage' grantees."""
    from django.db.models import Q
    from apps.hr.models import AttendanceAccess
    from apps.users.models import StaffProfile
    granted = AttendanceAccess.objects.filter(level='manage', revoked_at__isnull=True).values('staff_id')
    return list(StaffProfile.objects.filter(is_active=True).filter(
        Q(role='admin') | Q(pk__in=granted)).distinct())
