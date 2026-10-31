"""
apps/stock_audit/access.py — who may see / review / configure stock-audit findings (server-side).

  • Management: admin, or a role granted RBAC module `stock_audit`:
      view → every branch · approve → review findings · export → Excel · edit → thresholds
    (seeded: supervisor = view/approve/export, quality_manager = + edit).
  • Named branch managers: an active StockAuditAccess row → view + review + export for THEIR OWN
    branches only (StaffProfile.branch + extra branches). Never thresholds, never access grants.
  • Granting / revoking branch managers: admin only.
"""
MODULE = 'stock_audit'


def _profile(user_or_request):
    user = getattr(user_or_request, 'user', user_or_request)
    return getattr(user, 'staff_profile', None)


def _mgmt(profile, action):
    return bool(profile and profile.is_active and (profile.role == 'admin' or profile.can_do(MODULE, action)))


def active_grant(profile):
    if not profile:
        return None
    from .models import StockAuditAccess
    return StockAuditAccess.objects.filter(staff=profile, revoked_at__isnull=True).first()


def own_branch_codes(profile):
    """softech_branch_id of the branches a branch manager may see (core.branch_scope: home +
    allowed branches, never a restricted one)."""
    from apps.branches.models import Branch
    from core.branch_scope import scope
    return set(scope(Branch.objects.all(), profile, 'id').values_list('softech_branch_id', flat=True))


class Access:
    """Resolved once per request."""

    def __init__(self, user_or_request):
        p = _profile(user_or_request)
        self.profile = p
        self.management = _mgmt(p, 'view')
        self.branch_manager = (not self.management) and bool(p and p.is_active and active_grant(p))
        self.branches = None if self.management else (own_branch_codes(p) if self.branch_manager else set())
        self.can_view = self.management or (self.branch_manager and bool(self.branches))
        self.can_review = _mgmt(p, 'approve') or self.branch_manager
        self.can_export = _mgmt(p, 'export') or self.branch_manager
        self.can_edit_thresholds = _mgmt(p, 'edit')
        self.can_manage_access = bool(p and p.role == 'admin')
        self.can_refresh = self.management

    def allows_branch(self, code):
        return self.branches is None or code in self.branches

    def scope(self, qs, field='branchcode'):
        return qs if self.branches is None else qs.filter(**{f'{field}__in': self.branches})

    def as_dict(self):
        return {'can_view': self.can_view, 'management': self.management,
                'branch_manager': self.branch_manager,
                'branches': None if self.branches is None else sorted(self.branches),
                'can_review': self.can_review, 'can_export': self.can_export,
                'can_edit_thresholds': self.can_edit_thresholds,
                'can_manage_access': self.can_manage_access, 'can_refresh': self.can_refresh}


def can_open(user):
    """For the sidebar flag on /api/auth/me/."""
    return Access(user).can_view
