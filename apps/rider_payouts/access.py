"""
apps/rider_payouts/access.py — who sees and changes the rider payout ledger (server-side).

Module 'delivery' (its API lives under /api/delivery/payouts/, mapped by module_access):

    read (rides, periods, rule)          view
    record a ride at the branch          create
    build from delivered orders, void    edit
    adjustments (extras / deductions)    finalize or approve
    finalize a period                    finalize or approve
    export                               export, finalize or approve
    unlock a finalized period            admin role only (D-16), with a reason

Rows: a rider (a staff member linked to a DeliveryDriver, not admin) sees only their own rows and
changes nothing — whatever the matrix says. Everyone else sees the rows of their branches
(core.branch_scope). Nobody adjusts or finalizes their own period.
"""
from __future__ import annotations

from core import branch_scope
from core.permissions import matrix_allows

from apps.delivery.permissions import driver_of

MODULE = 'delivery'


def profile_of(request):
    return getattr(request.user, 'staff_profile', None)


def rider_of(profile):
    """The profile's own DeliveryDriver when it acts as a rider (not admin), else None."""
    if profile is None or profile.role == 'admin':
        return None
    return driver_of(profile)


def can(profile, *actions) -> bool:
    return matrix_allows(profile, MODULE, *actions)


def scoped(qs, request):
    """Rows this user may see: a rider's own, else their branches'."""
    rider = rider_of(profile_of(request))
    if rider is not None:
        return qs.filter(driver_id=rider.pk)
    return branch_scope.scope(qs, request.user)


def may_write(request, *actions) -> bool:
    profile = profile_of(request)
    return rider_of(profile) is None and can(profile, *actions)


def own_period(request, period) -> bool:
    """True when the period is the requester's own (self-approval guard)."""
    profile = profile_of(request)
    driver = driver_of(profile) if profile is not None else None
    return driver is not None and period.driver_id == driver.pk


def export_allowed(user) -> bool:
    """Export kind gate (apps/export_jobs): not a rider, and export / finalize / approve."""
    profile = getattr(user, 'staff_profile', None)
    if profile is None:
        return bool(getattr(user, 'is_superuser', False))
    return rider_of(profile) is None and can(profile, 'export', 'finalize', 'approve')
