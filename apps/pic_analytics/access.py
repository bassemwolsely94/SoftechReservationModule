"""
apps/pic_analytics/access.py — who may open PIC Analytics and what they see (server-side, doc 33 §5).

  • Management: admin, or a role granted RBAC module `pic_analytics` 'view' (seeded: supervisor
    view+export) → every branch, cost / GP visible, the calls tabs, Excel if 'export'.
  • Named branch managers: an active PicAnalyticsAccess row → THEIR OWN branches only
    (home + allowed branches, never a restricted one; no all-branch shortcut), view + export.
    Never cost / GP, never the calls tabs, never the grants.
  • Granting / revoking branch managers: admin only.
"""
MODULE = 'pic_analytics'


def _profile(user_or_request):
    user = getattr(user_or_request, 'user', user_or_request)
    return getattr(user, 'staff_profile', None)


def _mgmt(profile, action):
    return bool(profile and profile.is_active and (profile.role == 'admin' or profile.can_do(MODULE, action)))


def active_grant(profile):
    if not profile:
        return None
    from .models import PicAnalyticsAccess
    return PicAnalyticsAccess.objects.filter(staff=profile, revoked_at__isnull=True).first()


def own_branch_ids(profile):
    """Branch pks a named branch manager may see: home branch + allowed - restricted.
    Computed directly, WITHOUT core.branch_scope's all-branch shortcut (all-branch roles /
    access_all_branches): a grantee sees only their own branch(es), doc 33 §5. No home branch
    and no allowed branches -> empty set -> no access."""
    ids = set()
    if profile.branch_id:
        ids.add(profile.branch_id)
    ids |= set(profile.allowed_branches.values_list('pk', flat=True))
    ids -= set(profile.restricted_branches.values_list('pk', flat=True))
    return ids


class Access:
    """Resolved once per request."""

    def __init__(self, user_or_request):
        p = _profile(user_or_request)
        self.profile = p
        self.management = _mgmt(p, 'view')
        self.branch_manager = (not self.management) and bool(p and p.is_active and active_grant(p))
        self.branch_ids = None if self.management else (own_branch_ids(p) if self.branch_manager else set())
        self.can_view = self.management or (self.branch_manager and bool(self.branch_ids))
        self.can_export = _mgmt(p, 'export') or (self.branch_manager and bool(self.branch_ids))
        self.sees_cost = self.management
        self.sees_calls_tabs = self.management
        self.can_manage_access = bool(p and p.is_active and p.role == 'admin')

    def allowed_branch_ids(self, requested=None):
        """The branches a query may cover. A requested set only narrows, never widens."""
        if self.branch_ids is None:
            return set(requested) if requested else None
        return (self.branch_ids & set(requested)) if requested else set(self.branch_ids)

    def scope_facts(self, qs, field='branch'):
        """Restrict a queryset to the allowed branches, whatever the request asks for."""
        return qs if self.branch_ids is None else qs.filter(**{f'{field}__in': self.branch_ids})

    def as_dict(self):
        return {'can_view': self.can_view, 'management': self.management,
                'branch_manager': self.branch_manager,
                'branch_ids': None if self.branch_ids is None else sorted(self.branch_ids),
                'can_export': self.can_export, 'sees_cost': self.sees_cost,
                'sees_calls_tabs': self.sees_calls_tabs, 'can_manage_access': self.can_manage_access}


def can_open(user):
    """For the sidebar flag on /api/auth/me/."""
    return Access(user).can_view
