"""
core/branch_scope.py — the ONE answer to "which branches may this user see?" (security Batch 5,
owner decision 3, 2026-10-26).

  • Home branch + `allowed_branches` (the real extra-branch list; UserBranchAccess rows were
    folded into it by users.0033).
  • `access_all_branches` and the all-branch roles (admin, call_center, purchasing, supervisor,
    quality_manager — owner decision B-3, 2026-10-30) see every branch …
  • … except a `restricted_branches` entry, which always wins.
  • Fail-closed: no user / no profile / inactive profile / branch role with no branch → nothing.
    A superuser without a staff profile (Django shell, tests) is unrestricted.

`branch_ids()` returns None for "every branch" and a set of Branch pks otherwise.
"""
from __future__ import annotations

ALL_BRANCH_ROLES = ('admin', 'call_center', 'purchasing', 'supervisor', 'quality_manager')


def _profile(user_or_profile):
    if hasattr(user_or_profile, 'restricted_branches'):
        return user_or_profile
    user = getattr(user_or_profile, 'user', user_or_profile)  # a request works too
    return getattr(user, 'staff_profile', None)


def _user(user_or_profile):
    if hasattr(user_or_profile, 'restricted_branches'):
        return user_or_profile.user
    return getattr(user_or_profile, 'user', user_or_profile)


def sees_all_branches(profile) -> bool:
    return bool(profile.access_all_branches or profile.role in ALL_BRANCH_ROLES)


def branch_ids(user_or_profile):
    """None = every branch; otherwise the set of Branch pks (possibly empty)."""
    profile = _profile(user_or_profile)
    if profile is None:
        user = _user(user_or_profile)
        if getattr(user, 'is_authenticated', False) and getattr(user, 'is_superuser', False):
            return None
        return set()
    if not profile.is_active or not getattr(profile.user, 'is_active', True):
        return set()
    restricted = set(profile.restricted_branches.values_list('id', flat=True))
    if sees_all_branches(profile):
        if not restricted:
            return None
        from apps.branches.models import Branch
        return set(Branch.objects.exclude(id__in=restricted).values_list('id', flat=True))
    ids = set(profile.allowed_branches.values_list('id', flat=True))
    if profile.branch_id:
        ids.add(profile.branch_id)
    return ids - restricted


def sees_everything(user_or_profile) -> bool:
    """Company-level data (consolidated finance, supplier A/P): an active all-branch user —
    all-branch role or access_all_branches — or a profile-less superuser. Restricted branches are
    still filtered out of branch-level rows by scope()."""
    profile = _profile(user_or_profile)
    if profile is None:
        user = _user(user_or_profile)
        return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'is_superuser', False))
    return bool(profile.is_active and getattr(profile.user, 'is_active', True) and sees_all_branches(profile))


def allows(user_or_profile, branch_id) -> bool:
    if branch_id is None:
        return branch_ids(user_or_profile) is None
    ids = branch_ids(user_or_profile)
    return ids is None or branch_id in ids


def scope(qs, user_or_profile, field: str = 'branch'):
    """Filter `qs` to the user's branches through `field` (an FK to Branch, or `<fk>_id`/`id`)."""
    ids = branch_ids(user_or_profile)
    if ids is None:
        return qs
    lookup = field if field == 'id' or field.endswith('_id') else f'{field}_id'
    return qs.filter(**{f'{lookup}__in': ids})


def get_or_404(model_or_qs, user_or_profile, field: str = 'branch', **lookup):
    """The record if it exists AND is in the user's branches — otherwise Http404, so another
    branch's record is indistinguishable from a missing one."""
    from django.shortcuts import get_object_or_404
    qs = model_or_qs._default_manager.all() if hasattr(model_or_qs, '_default_manager') else model_or_qs
    return get_object_or_404(scope(qs, user_or_profile, field), **lookup)


def check_branch_value(user_or_profile, serializer, field: str = 'branch'):
    """A created / edited record may only point at a branch the user may access."""
    from rest_framework.exceptions import PermissionDenied
    if field not in serializer.validated_data:
        return
    b = serializer.validated_data[field]
    if not allows(user_or_profile, getattr(b, 'pk', b)):
        raise PermissionDenied('لا يمكنك التسجيل على فرع خارج فروعك.')


class BranchScopedMixin:
    """For DRF generic views: get_queryset() is narrowed to the user's branches via
    `branch_scope_field`, so list, retrieve, update and destroy all inherit the scope."""
    branch_scope_field = 'branch'

    def get_queryset(self):
        return scope(super().get_queryset(), self.request.user, self.branch_scope_field)

    def check_branch_value(self, serializer):
        check_branch_value(self.request.user, serializer, self.branch_scope_field)

    def perform_create(self, serializer):
        self.check_branch_value(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self.check_branch_value(serializer)
        super().perform_update(serializer)
