"""Grant RBAC module `stock_audit` (doc 32) to supervisor and quality_manager.
Only the stock_audit rows are created — no other module's permissions are touched
(seed_permissions carries the same matrix for fresh installs)."""
from django.db import migrations

GRANTS = {
    'supervisor':      ['view', 'approve', 'export'],
    'quality_manager': ['view', 'approve', 'export', 'edit'],
}


def grant(apps, schema_editor):
    RoleModuleAccess = apps.get_model('users', 'RoleModuleAccess')
    for role, actions in GRANTS.items():
        for action in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module='stock_audit', action=action,
                                                   defaults={'is_allowed': True})


def ungrant(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='stock_audit').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('stock_audit', '0003_stockauditaccess_and_more'),
        ('users', '0030_alter_rolemoduleaccess_module'),
    ]
    operations = [migrations.RunPython(grant, ungrant)]
