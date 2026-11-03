"""Grant RBAC module `pic_analytics` (doc 33) view + export to supervisor.
Only the pic_analytics rows are created (seed_permissions carries the same matrix for fresh
installs; it is not run on deploy, so without this supervisors fail closed)."""
from django.db import migrations

GRANTS = {'supervisor': ['view', 'export']}


def grant(apps, schema_editor):
    RoleModuleAccess = apps.get_model('users', 'RoleModuleAccess')
    for role, actions in GRANTS.items():
        for action in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module='pic_analytics', action=action,
                                                   defaults={'is_allowed': True})


def ungrant(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='pic_analytics').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('pic_analytics', '0001_initial'),
        ('users', '0041_alter_rolemoduleaccess_module'),
    ]
    operations = [migrations.RunPython(grant, ungrant)]
