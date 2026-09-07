"""
management command: seed_permissions
=====================================
Seeds the COMPLETE RoleModuleAccess permission matrix for all 9 roles
across all 25 modules and 8 action types.

Each (role, module, action) triplet gets an explicit True/False — no gaps.
Idempotent: uses update_or_create, so existing admin overrides can be preserved
unless --wipe is passed.

Usage:
    python manage.py seed_permissions
    python manage.py seed_permissions --dry-run          # preview only
    python manage.py seed_permissions --role pharmacist  # one role only
    python manage.py seed_permissions --wipe             # reset then seed
"""

from django.core.management.base import BaseCommand
from apps.users.models import RoleModuleAccess

# ─────────────────────────────────────────────────────────────────────────────
# ALL MODULES & ACTIONS (must match models.py MODULE_CHOICES / ACTION_CHOICES)
# ─────────────────────────────────────────────────────────────────────────────

ALL_MODULES = [
    'reservations', 'demand', 'transfers', 'followups', 'delivery',
    'customers', 'chronic', 'campaigns', 'vouchers',
    'catalog', 'stockcount', 'shortage',
    'purchasing', 'invoices', 'incentives', 'cheques', 'finance',
    'callcenter', 'hr', 'approvals', 'analytics', 'dashboard',
    'audit', 'sync', 'settings', 'users', 'admin',
]

ALL_ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']

# ─────────────────────────────────────────────────────────────────────────────
# PERMISSION MATRIX
#
# PERMISSIONS[role][module] = set of ALLOWED actions.
# Any (module, action) pair NOT listed for a role → is_allowed=False.
# ─────────────────────────────────────────────────────────────────────────────

RO  = {'view'}                      # Read-only
RE  = {'view', 'export'}            # Read + export
RW  = {'view', 'create', 'edit'}    # Standard read-write (no delete/approve)


PERMISSIONS = {

    # ─────────────────────────────────────────────────────────────────────
    # admin — Full unrestricted access to every module and action.
    # The code bypasses the table for admins; this seed is for UI display.
    # ─────────────────────────────────────────────────────────────────────
    'admin': {m: set(ALL_ACTIONS) for m in ALL_MODULES},

    # ─────────────────────────────────────────────────────────────────────
    # call_center — Works across ALL branches.
    # Primary role: intake calls, create/manage reservations & demand,
    # run OTP redemptions, manage CC cases, send campaigns.
    # ─────────────────────────────────────────────────────────────────────
    'call_center': {
        'dashboard':    RO,
        'reservations': {'view', 'create', 'edit', 'export', 'assign'},
        'demand':       {'view', 'create', 'edit', 'export', 'assign'},
        'transfers':    RO,
        'followups':    {'view', 'create', 'edit', 'export', 'assign'},
        'customers':    {'view', 'edit'},           # update notes/contact, no delete
        'chronic':      RO,
        'catalog':      RO,
        'vouchers':     {'view', 'approve'},        # initiate + confirm OTP redemption
        'shortage':     {'view', 'create', 'edit'},
        'callcenter':   {'view', 'create', 'edit', 'export', 'assign'},
        'campaigns':    {'view', 'create', 'edit'},
        'analytics':    RO,                         # call-center analytics tab
        'delivery':     {'view', 'create', 'assign'},
        'hr':           {'view', 'create'},         # self-service leave/overtime/advances/expenses
    },

    # ─────────────────────────────────────────────────────────────────────
    # pharmacist — Own branch (can be granted extra branches by admin).
    # Core clinical role: dispenses meds, fulfils reservations,
    # runs stock count, approves transfers, manages shortage.
    # ─────────────────────────────────────────────────────────────────────
    'pharmacist': {
        'dashboard':    RO,
        'reservations': {'view', 'create', 'edit', 'approve', 'finalize'},
        # approve = mark stock available;  finalize = mark fulfilled
        'demand':       {'view', 'create', 'edit'},
        'transfers':    {'view', 'create', 'edit', 'approve', 'finalize'},
        # approve = accept incoming transfer; finalize = mark received in ERP
        'followups':    {'view', 'create', 'edit', 'approve'},
        'customers':    {'view', 'edit'},
        'chronic':      {'view', 'edit'},
        'catalog':      {'view', 'edit', 'export'},
        'vouchers':     {'view', 'approve', 'finalize'},
        # approve = trigger OTP flow; finalize = POS mark-used
        'stockcount':   {'view', 'create', 'edit', 'export', 'finalize'},
        'shortage':     {'view', 'create', 'edit', 'approve', 'export'},
        'analytics':    RO,
        'finance':      RO,
        'delivery':     {'view', 'create', 'edit', 'approve', 'finalize'},
        'campaigns':    RO,
        'settings':     RO,
        'cheques':      RO,
        'hr':           {'view', 'create'},                 # self-service
        'approvals':    {'view', 'approve'},                # approves supplier_claim (pharmacist step)
    },

    # ─────────────────────────────────────────────────────────────────────
    # salesperson — Own branch only.
    # Creates reservations & demand records, assists with shortages.
    # Cannot approve, export data, or access financial screens.
    # ─────────────────────────────────────────────────────────────────────
    'salesperson': {
        'dashboard':    RO,
        'reservations': {'view', 'create', 'edit'},
        'demand':       {'view', 'create', 'edit'},
        'transfers':    {'view', 'create'},
        'followups':    {'view', 'create', 'edit'},
        'customers':    RO,
        'chronic':      RO,
        'catalog':      RO,
        'vouchers':     {'view', 'approve'},        # run OTP at POS terminal
        'shortage':     {'view', 'create', 'edit'},
        'delivery':     {'view', 'create'},
        'hr':           {'view', 'create'},         # self-service
    },

    # ─────────────────────────────────────────────────────────────────────
    # purchasing — HQ, all branches (read).
    # Full authority over procurement, invoices, incentives, suppliers.
    # Cannot touch reservations or clinical demand operations.
    # ─────────────────────────────────────────────────────────────────────
    'purchasing': {
        'dashboard':    RO,
        'catalog':      {'view', 'edit', 'export', 'approve'},
        'transfers':    {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'shortage':     {'view', 'create', 'edit', 'approve', 'export'},
        'stockcount':   RE,
        'purchasing':   {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'invoices':     {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'incentives':   {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'cheques':      {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'finance':      {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
        'campaigns':    {'view', 'create', 'edit', 'approve', 'export'},
        'vouchers':     {'view', 'create', 'edit', 'assign', 'export'},
        'customers':    RE,
        'analytics':    RE,
        'chronic':      RO,
        'delivery':     RE,
        'settings':     RO,
        'hr':           {'view', 'create'},                              # self-service
        'approvals':    {'view', 'approve'},                             # finance approval steps
    },

    # ─────────────────────────────────────────────────────────────────────
    # delivery — Delivery driver.
    # Can update/confirm their own assigned deliveries.
    # Read-only access to customers (address) and catalog (item names).
    # No access to financial, admin, or operational modules.
    # ─────────────────────────────────────────────────────────────────────
    'delivery': {
        'dashboard':    RO,
        'delivery':     {'view', 'edit', 'approve', 'finalize'},
        # edit = update delivery notes; approve = confirm pickup; finalize = delivered
        'customers':    RO,   # address + phone for navigation
        'catalog':      RO,   # item names on delivery slip
        'hr':           {'view', 'create'},   # self-service
    },

    # ─────────────────────────────────────────────────────────────────────
    # viewer — Read-only observer.
    # Can see all operational data, take no action whatsoever.
    # ─────────────────────────────────────────────────────────────────────
    'viewer': {
        'dashboard':    RO,
        'reservations': RO,
        'demand':       RO,
        'transfers':    RO,
        'followups':    RO,
        'customers':    RO,
        'chronic':      RO,
        'catalog':      RO,
        'stockcount':   RO,
        'shortage':     RO,
        'vouchers':     RO,
        'analytics':    RO,
        'purchasing':   RO,
        'delivery':     RO,
        'callcenter':   RO,
        'hr':           RO,
        'approvals':    RO,
    },

    # ─────────────────────────────────────────────────────────────────────
    # supervisor — Call Center Supervisor.
    # Full authority over all CC operations.
    # Can approve escalations, override agents, export data, audit logs.
    # ─────────────────────────────────────────────────────────────────────
    'supervisor': {
        'dashboard':    RO,
        'reservations': {'view', 'create', 'edit', 'approve', 'export', 'assign'},
        'demand':       {'view', 'create', 'edit', 'approve', 'export', 'assign'},
        'transfers':    {'view', 'approve', 'export'},
        'followups':    {'view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'},
        'customers':    {'view', 'edit', 'export'},
        'chronic':      RO,
        'catalog':      RO,
        'vouchers':     {'view', 'create', 'edit', 'approve', 'export', 'assign'},
        'shortage':     {'view', 'create', 'edit', 'approve', 'export'},
        'callcenter':   {'view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'},
        'campaigns':    {'view', 'create', 'edit', 'approve', 'export'},
        'analytics':    RE,
        'delivery':     {'view', 'create', 'edit', 'approve', 'export', 'assign'},
        'users':        RO,   # can view staff list; cannot create/edit
        'audit':        RE,
        'hr':           {'view', 'create', 'approve', 'export'},   # branch-manager approval step + own requests
        'approvals':    {'view', 'approve'},
    },

    # ─────────────────────────────────────────────────────────────────────
    # quality_manager — QA & Scoring.
    # Read + export access across all operational and analytics modules.
    # Reviews call quality, scoring, incentive calculations, audit logs.
    # No write access.
    # ─────────────────────────────────────────────────────────────────────
    'quality_manager': {
        'dashboard':    RO,
        'reservations': RE,
        'demand':       RE,
        'transfers':    RE,
        'followups':    RE,
        'customers':    RE,
        'chronic':      RE,
        'catalog':      RO,
        'stockcount':   RE,
        'shortage':     RE,
        'vouchers':     RE,
        'callcenter':   RE,
        'campaigns':    RO,
        'analytics':    RE,
        'incentives':   RE,
        'delivery':     RE,
        'audit':        RE,
        'finance':      RO,
        'hr':           RE,                  # view + export; own requests
        'approvals':    {'view', 'approve'}, # batch_quarantine authorization
    },
}


class Command(BaseCommand):
    help = 'Seed the complete RoleModuleAccess permission matrix for all 9 roles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would change without touching the DB',
        )
        parser.add_argument(
            '--role', type=str, default=None,
            help='Seed only a specific role (e.g. --role pharmacist)',
        )
        parser.add_argument(
            '--wipe', action='store_true',
            help='Delete ALL existing RoleModuleAccess rows before seeding',
        )

    def handle(self, *args, **options):
        dry_run   = options['dry_run']
        only_role = options.get('role')
        wipe      = options['wipe']

        if only_role and only_role not in PERMISSIONS:
            self.stderr.write(self.style.ERROR(f'Unknown role: "{only_role}"'))
            self.stderr.write('Known roles: ' + ', '.join(PERMISSIONS.keys()))
            return

        if wipe and not dry_run:
            count, _ = RoleModuleAccess.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'  [WIPE] Deleted {count} existing permission rows'))

        created = updated = unchanged = 0

        roles_to_seed = (
            {only_role: PERMISSIONS[only_role]} if only_role else PERMISSIONS
        )

        for role, module_map in roles_to_seed.items():
            self.stdout.write(f'\nROLE: {role}')

            for module in ALL_MODULES:
                allowed_actions = module_map.get(module, set())
                for action in ALL_ACTIONS:
                    is_allowed = action in allowed_actions

                    if dry_run:
                        icon = '[Y]' if is_allowed else '[ ]'
                        self.stdout.write(f'   {icon} {module:14s} {action:10s}')
                        continue

                    obj, was_created = RoleModuleAccess.objects.get_or_create(
                        role=role, module=module, action=action,
                        defaults={'is_allowed': is_allowed},
                    )
                    if was_created:
                        created += 1
                    elif obj.is_allowed != is_allowed:
                        obj.is_allowed = is_allowed
                        obj.save(update_fields=['is_allowed', 'updated_at'])
                        updated += 1
                    else:
                        unchanged += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry-run complete — no changes written to DB.'
            ))
        else:
            total = created + updated + unchanged
            self.stdout.write(self.style.SUCCESS(
                f'\nDone — {total} rows processed: '
                f'{created} created, {updated} updated, {unchanged} unchanged'
            ))
            self.stdout.write(
                '   Re-run with --dry-run to preview the full matrix.'
            )
