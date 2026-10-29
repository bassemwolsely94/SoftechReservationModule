"""Grant supervisors stock count (view / create / edit) and chronic edit, and call center chronic
edit (owner 2026-10-29, Batch 4 Z-11i — overblock review decision 9: the menus already show them
these screens). Turns only these rows on; every other row, and any admin override, is untouched.
"""
from django.db import migrations

GRANTS = {
    'supervisor':  {'stockcount': ['view', 'create', 'edit'], 'chronic': ['view', 'edit']},
    'call_center': {'chronic': ['view', 'edit']},
}
NEW = {('supervisor', 'stockcount', a) for a in ('view', 'create', 'edit')} | {
    ('supervisor', 'chronic', 'edit'), ('call_center', 'chronic', 'edit')}


def grant(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role, modules in GRANTS.items():
        for module, actions in modules.items():
            # only a matrix already seeded for the module: on a fresh install a few rows would mark
            # it "seeded" and lock every other role out — seed_permissions writes the full code
            # matrix (these grants included) there instead
            if not RMA.objects.filter(module=module).exclude(role=role).exists():
                continue
            for action in actions:
                RMA.objects.update_or_create(role=role, module=module, action=action,
                                             defaults={'is_allowed': True})


def revoke(apps, schema_editor):
    RMA = apps.get_model('users', 'RoleModuleAccess')
    for role, module, action in NEW:
        RMA.objects.filter(role=role, module=module, action=action).update(is_allowed=False)


class Migration(migrations.Migration):
    dependencies = [('users', '0031_alter_rolemoduleaccess_module')]
    operations = [migrations.RunPython(grant, revoke)]
