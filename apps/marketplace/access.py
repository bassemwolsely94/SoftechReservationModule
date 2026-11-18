"""
apps/marketplace/access.py — who may use the marketplace / delivery-platform channels (server-side).

  • Feature flag settings.MARKETPLACE_ENABLED (default OFF): when off nobody sees anything.
  • RBAC module `marketplace`: view → orders and listings · create → manual intake, accept / reject,
    status changes · approve → approve listings for a channel · edit → channels, stores, settlement.
    Admin always passes.
"""
from django.conf import settings

MODULE = 'marketplace'


def enabled() -> bool:
    return bool(getattr(settings, 'MARKETPLACE_ENABLED', False))


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
        self.can_approve = self.can_view and _can(p, 'approve')
        self.can_edit = self.can_view and _can(p, 'edit')

    def as_dict(self):
        return {'can_view': self.can_view, 'can_create': self.can_create,
                'can_approve': self.can_approve, 'can_edit': self.can_edit}


def can_open(user):
    """For the sidebar flag on /api/auth/me/."""
    return Access(user).can_view
