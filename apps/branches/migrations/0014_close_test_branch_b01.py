"""Close the test branch B01 (kind is the liveness authority)."""
from django.db import migrations


def close_b01(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    Branch.objects.filter(softech_branch_id='B01').update(
        kind='closed', is_operational=False, pos_enabled=False)


class Migration(migrations.Migration):
    dependencies = [('branches', '0013_branch_pending_kind_display_order')]
    operations = [migrations.RunPython(close_b01, migrations.RunPython.noop)]
