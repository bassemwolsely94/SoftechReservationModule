"""
management command: seed_permissions

Populates RoleModuleAccess with sensible defaults.
Safe to re-run — uses get_or_create so existing overrides are preserved.

Usage:
    python manage.py seed_permissions
    python manage.py seed_permissions --reset   # wipe and recreate all
"""
from django.core.management.base import BaseCommand
from apps.users.models import RoleModuleAccess

# (role, module, allowed_actions)
DEFAULT_PERMISSIONS = [
    # ── Admin: full access (bypasses table, but seed anyway for completeness) ──
    ('admin', 'reservations', ['view', 'create', 'edit', 'delete', 'approve', 'export']),
    ('admin', 'demand',       ['view', 'create', 'edit', 'delete', 'approve', 'export']),
    ('admin', 'transfers',    ['view', 'create', 'edit', 'delete', 'approve', 'export']),
    ('admin', 'customers',    ['view', 'create', 'edit', 'delete', 'export']),
    ('admin', 'catalog',      ['view', 'export']),
    ('admin', 'dashboard',    ['view', 'export']),
    ('admin', 'sync',         ['view', 'create']),
    ('admin', 'purchasing',   ['view', 'export']),
    ('admin', 'chronic',      ['view', 'create', 'edit', 'delete']),
    ('admin', 'admin',        ['view', 'create', 'edit', 'delete']),

    # ── Call Center: all views, create/edit reservations & demand, no delete ──
    ('call_center', 'reservations', ['view', 'create', 'edit']),
    ('call_center', 'demand',       ['view', 'create', 'edit']),
    ('call_center', 'transfers',    ['view', 'create']),
    ('call_center', 'customers',    ['view', 'create', 'edit']),
    ('call_center', 'catalog',      ['view']),
    ('call_center', 'dashboard',    ['view']),
    ('call_center', 'chronic',      ['view']),

    # ── Pharmacist: own branch — full operational access ──────────────────────
    ('pharmacist', 'reservations', ['view', 'create', 'edit']),
    ('pharmacist', 'demand',       ['view', 'create', 'edit']),
    ('pharmacist', 'transfers',    ['view', 'create', 'approve']),
    ('pharmacist', 'customers',    ['view', 'create', 'edit']),
    ('pharmacist', 'catalog',      ['view']),
    ('pharmacist', 'dashboard',    ['view']),
    ('pharmacist', 'chronic',      ['view', 'create', 'edit']),

    # ── Salesperson: own branch — create & edit reservations/demand ───────────
    ('salesperson', 'reservations', ['view', 'create', 'edit']),
    ('salesperson', 'demand',       ['view', 'create', 'edit']),
    ('salesperson', 'transfers',    ['view', 'create']),
    ('salesperson', 'customers',    ['view', 'create', 'edit']),
    ('salesperson', 'catalog',      ['view']),
    ('salesperson', 'dashboard',    ['view']),

    # ── Purchasing: HQ — all branches, ordering focus ─────────────────────────
    ('purchasing', 'reservations', ['view']),
    ('purchasing', 'demand',       ['view', 'export']),
    ('purchasing', 'transfers',    ['view', 'approve']),
    ('purchasing', 'customers',    ['view']),
    ('purchasing', 'catalog',      ['view', 'edit']),
    ('purchasing', 'dashboard',    ['view', 'export']),
    ('purchasing', 'purchasing',   ['view', 'export']),
    ('purchasing', 'chronic',      ['view']),

    # ── Delivery: own branch — view only ─────────────────────────────────────
    ('delivery', 'reservations', ['view']),
    ('delivery', 'transfers',    ['view']),
    ('delivery', 'customers',    ['view']),

    # ── Viewer: read-only across everything ───────────────────────────────────
    ('viewer', 'reservations', ['view']),
    ('viewer', 'demand',       ['view']),
    ('viewer', 'transfers',    ['view']),
    ('viewer', 'customers',    ['view']),
    ('viewer', 'catalog',      ['view']),
    ('viewer', 'dashboard',    ['view']),
    ('viewer', 'chronic',      ['view']),
]


class Command(BaseCommand):
    help = 'Seed default RoleModuleAccess permissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete all existing entries before seeding'
        )

    def handle(self, *args, **options):
        if options['reset']:
            deleted, _ = RoleModuleAccess.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Deleted {deleted} existing entries'))

        created = updated = 0
        all_actions = {'view', 'create', 'edit', 'delete', 'approve', 'export'}

        for role, module, allowed_actions in DEFAULT_PERMISSIONS:
            for action in all_actions:
                is_allowed = action in allowed_actions
                obj, was_created = RoleModuleAccess.objects.get_or_create(
                    role=role, module=module, action=action,
                    defaults={'is_allowed': is_allowed},
                )
                if was_created:
                    created += 1
                elif not options['reset'] and obj.is_allowed != is_allowed:
                    # Only update if --reset wasn't used (preserve manual overrides)
                    pass

        self.stdout.write(self.style.SUCCESS(
            f'Done — {created} entries created. '
            'Existing manual overrides were preserved.'
        ))
