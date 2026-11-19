"""
apps/stock_audit/assignment.py — who owns a stock-audit finding's task (C13).

ONE function, so the owner can change the rule in one place. Deterministic default:

  1. the NAMED branch manager of that branch: an active StockAuditAccess grant whose holder is
     active and whose home branch is the finding's branch (oldest grant first);
  2. otherwise the active staff member of that branch with a branch-lead role
     (apps/users/roles.py `branch_lead`, today the pharmacist), lowest id first;
  3. otherwise nobody — the task is still created on the branch, unassigned.

The rule does not look at the kind of finding yet ("who owns which kind of finding" is an open
owner question). `finding` is passed so a per-rule rule can be added here later.
"""
from apps.users.roles import BRANCH_LEAD_ROLES


def default_assignee(finding):
    """StaffProfile or None for this finding's branch."""
    from apps.users.models import StaffProfile
    from .models import StockAuditAccess

    code = finding.branchcode
    grant = (StockAuditAccess.objects
             .filter(revoked_at__isnull=True, staff__is_active=True, staff__branch__softech_branch_id=code)
             .select_related('staff').order_by('granted_at', 'id').first())
    if grant:
        return grant.staff
    return (StaffProfile.objects
            .filter(is_active=True, role__in=BRANCH_LEAD_ROLES, branch__softech_branch_id=code)
            .order_by('id').first())
