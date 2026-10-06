"""Grant the purchasing role access to the insurance + commerce modules.

admin bypasses RBAC (can_do returns True), so it needs no rows.  Every other
role stays denied by default — these modules are confidential.  Idempotent.
"""
from django.db import migrations

ACTIONS = ['view', 'create', 'edit', 'delete', 'approve', 'export', 'assign', 'finalize']
GRANTS = {
    'purchasing': {'insurance': ACTIONS, 'commerce': ACTIONS},
}


def seed(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role, modules in GRANTS.items():
        for module, actions in modules.items():
            for action in actions:
                RMA.objects.update_or_create(
                    role=role, module=module, action=action,
                    defaults={'is_allowed': True})


def unseed(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    RMA.objects.filter(module__in=['insurance', 'commerce']).delete()


class Migration(migrations.Migration):
    dependencies = [('users', '0023_alter_rolemoduleaccess_module')]
    operations = [migrations.RunPython(seed, unseed)]
