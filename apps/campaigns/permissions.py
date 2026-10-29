"""
Server-side permission for the campaign approval workflow (CLAUDE.md rule 9).

Approve, reject, send (queue) and cancel need the RoleModuleAccess action
'campaigns/approve'. Until 2026-10-26 these endpoints only required a login, so any
staff member — including the campaign's own creator — could approve and send a
campaign to customers.

Fallback, same idea as apps/delivery/permissions.py: if the matrix has no 'campaigns'
rows at all (never seeded), the roles seed_permissions grants 'approve' to are allowed,
so a fresh install is not locked out — but call center still cannot approve.
"""
import logging

logger = logging.getLogger('elrezeiky.rbac')

MODULE = 'campaigns'
DENIED = 'ليس لديك صلاحية اعتماد أو إرسال أو إلغاء الحملات'

# Roles seed_permissions grants campaigns/approve to.
FALLBACK_APPROVERS = {'admin', 'supervisor', 'purchasing'}


def _matrix_has_campaign_rows():
    from apps.users.models import RoleModuleAccess
    return RoleModuleAccess.objects.filter(module=MODULE).exists()


def can_approve(profile):
    """True when this staff member may approve / reject / send / cancel campaigns."""
    if profile is None:
        return False
    if profile.role == 'admin':
        return True
    if not _matrix_has_campaign_rows():
        logger.warning('RBAC matrix has no campaigns rows — using seeded approver roles')
        return profile.role in FALLBACK_APPROVERS
    return profile.can_do(MODULE, 'approve')
