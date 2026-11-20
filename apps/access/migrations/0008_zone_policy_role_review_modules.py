"""Role review 2026-11-20: ten tool modules split out of their parent module (users 0061), and
module_access.required() now maps their API paths to them. A `listed` zone policy names the modules
it allows, so a policy that listed a parent would refuse the moved paths (e.g. the call center's
off-network list has `customers`, and /api/referral/ is now `loyalty`). Append every new module whose
parent the row already lists. Idempotent; reverse is a no-op (the rows stay as an admin may have kept
them)."""
from django.db import migrations

# Frozen here on purpose (seed_permissions.ROLE_REVIEW_MODULES may change later): new module -> parent.
PARENT = {
    'forecast': 'analytics',
    'recommendations': 'analytics',
    'catalog_tools': 'catalog',
    'stock': 'catalog',
    'loyalty': 'customers',
    'dispatch': 'delivery',
    'rider': 'delivery',
    'reconciliation': 'finance',
    'access_control': 'settings',
    'code_maps': 'settings',
}


def forwards(apps, schema_editor):
    ZonePolicy = apps.get_model('access', 'ZonePolicy')
    for row in ZonePolicy.objects.all():
        modules = list(row.modules or [])
        added = [new for new, parent in PARENT.items() if parent in modules and new not in modules]
        if added:
            row.modules = modules + added
            row.save(update_fields=['modules'])


class Migration(migrations.Migration):

    dependencies = [
        ('access', '0007_accountant_role_choice'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
