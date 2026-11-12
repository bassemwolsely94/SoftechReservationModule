"""Grant RBAC module `tax_invoicing` (doc 36) to the accountant. Only these rows are created.
`finalize` (send to ETA, issuer settings, exclusion bases) stays admin-only until granted by name.

The admin rows matter: a module with rows only for RBAC_ENFORCED_ROLES (accountant is one) counts as
never seeded, and core.permissions.matrix_allows then fails open for every other role."""
from django.db import migrations

GRANTS = {
    'accountant': ['view', 'create', 'edit', 'approve'],
    'admin': ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize'],
}


ALL_ACTIONS = GRANTS['admin']


def grant(apps, schema_editor):
    RoleModuleAccess = apps.get_model('users', 'RoleModuleAccess')
    for role, actions in GRANTS.items():
        for action in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module='tax_invoicing', action=action,
                                                   defaults={'is_allowed': True})
    # The accountant's matrix is explicit: every action has a row, allowed or denied (users 0051).
    for action in ALL_ACTIONS:
        RoleModuleAccess.objects.get_or_create(role='accountant', module='tax_invoicing', action=action,
                                               defaults={'is_allowed': action in GRANTS['accountant']})


def ungrant(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='tax_invoicing').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('tax_invoicing', '0001_initial'),
        ('users', '0055_alter_rolemoduleaccess_module'),
    ]
    operations = [migrations.RunPython(grant, ungrant)]
