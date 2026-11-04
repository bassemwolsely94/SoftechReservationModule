"""
apps/usage_print/access.py — who may use the usage-instructions slip (server-side).

  • Feature flag settings.USAGE_PRINT_ENABLED (default OFF): when off nobody sees anything.
  • RBAC module `usage_print`: view → open sheets · create → confirm, print, attach a prescription
    · edit → presets and slip settings. Admin always passes.
  • Branch scope: an invoice opens only for a branch the user may access (core.branch_scope).
"""
from django.conf import settings

MODULE = 'usage_print'


def enabled() -> bool:
    return bool(getattr(settings, 'USAGE_PRINT_ENABLED', False))


def _profile(user_or_request):
    user = getattr(user_or_request, 'user', user_or_request)
    return getattr(user, 'staff_profile', None)


def _can(profile, action):
    return bool(profile and profile.is_active and (profile.role == 'admin' or profile.can_do(MODULE, action)))


class Access:
    """Resolved once per request."""

    def __init__(self, user_or_request):
        p = _profile(user_or_request)
        self.profile = p
        on = enabled()
        self.can_view = on and _can(p, 'view')
        self.can_create = self.can_view and _can(p, 'create')
        self.can_edit = self.can_view and _can(p, 'edit')

    def as_dict(self):
        return {'can_view': self.can_view, 'can_create': self.can_create, 'can_edit': self.can_edit}


def can_open(user):
    """For the sidebar flag on /api/auth/me/."""
    return Access(user).can_view
