"""Grant RBAC module `offers` (Batch 4, Z-5; owner 2026-10-27) to supervisor and purchasing —
the roles apps/offers managed offers with. Only the offers rows are created; no other module's
permissions are touched (seed_permissions carries the same matrix for fresh installs)."""
from django.db import migrations

GRANTS = {
    'supervisor': ['view', 'create', 'edit', 'delete'],
    'purchasing': ['view', 'create', 'edit', 'delete'],
}


def grant(apps, schema_editor):
    RoleModuleAccess = apps.get_model('users', 'RoleModuleAccess')
    for role, actions in GRANTS.items():
        for action in actions:
            RoleModuleAccess.objects.get_or_create(role=role, module='offers', action=action,
                                                   defaults={'is_allowed': True})


def ungrant(apps, schema_editor):
    apps.get_model('users', 'RoleModuleAccess').objects.filter(module='offers').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('offers', '0006_offer_bundle_price_offer_gift_item_and_more'),
        ('users', '0031_alter_rolemoduleaccess_module'),
    ]
    operations = [migrations.RunPython(grant, ungrant)]
