"""
apps/tests/security/fixtures.py

One staff user per role, authenticated the way a real browser is (Bearer JWT),
on top of the role matrix exactly as the code defines it in
apps/users/management/commands/seed_permissions.py — the owner's source of
truth for who may do what.

force_authenticate() is deliberately NOT used: it only sets the user on the DRF
request, so ModuleAccessMiddleware (which runs before DRF) would see an
anonymous caller and wave everything through.
"""
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.tests.factories import make_branch, make_user
from apps.users.management.commands.seed_permissions import ALL_ACTIONS, ALL_MODULES, PERMISSIONS
from apps.users.models import ROLE_CHOICES, RoleModuleAccess
from core.middleware import module_access

ROLES = [r for r, _ in ROLE_CHOICES]
NON_ADMIN_ROLES = [r for r in ROLES if r != 'admin']


def seed_code_matrix() -> None:
    """Replace RoleModuleAccess with the code matrix: one row per (role, module, action)."""
    RoleModuleAccess.objects.all().delete()
    RoleModuleAccess.objects.bulk_create([
        RoleModuleAccess(role=role, module=module, action=action,
                         is_allowed=action in PERMISSIONS.get(role, {}).get(module, set()))
        for role in ROLES for module in ALL_MODULES for action in ALL_ACTIONS
    ])
    module_access.clear_cache()


def granted(role: str, module: str, actions) -> bool:
    """True when the code matrix grants the role any of the actions on the module."""
    if role == 'admin':
        return True
    allowed = PERMISSIONS.get(role, {}).get(module, set())
    return any(a in allowed for a in actions)


def bearer_client(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def role_clients(branch=None) -> dict:
    """{role: APIClient} — one sec_<role> user per role, all in `branch`."""
    branch = branch or make_branch()
    clients = {}
    for role in ROLES:
        user, _, _ = make_user(f'sec_{role}', role=role, branch=branch,
                               access_all=(role == 'admin'))
        clients[role] = bearer_client(user)
    return clients
