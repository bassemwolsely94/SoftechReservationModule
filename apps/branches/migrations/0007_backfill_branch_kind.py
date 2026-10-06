"""
Backfill Branch.kind and pos_enabled from existing data.

The SOFTECH branches table has no active/kind column, so every row synced in as
is_active=True. We classify each existing branch ONCE here; from now on `kind` is
admin-curated (sync no longer overwrites it):

    softech_branch_id == '100'         → hq
    softech_branch_id == 'CC'          → call_center
    is_operational AND has db_host     → retail (+ pos_enabled=True)
    everything else (لاغى / متوقف)      → closed

Reversible: the reverse resets kind to the model default and pos_enabled to False.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    for b in Branch.objects.all():
        sid = (b.softech_branch_id or '').strip()
        has_db = bool((b.db_host or '').strip())
        if sid == '100':
            kind = 'hq'
        elif sid.upper() == 'CC':
            kind = 'call_center'
        elif b.is_operational and has_db:
            kind = 'retail'
        else:
            kind = 'closed'
        b.kind = kind
        # Retail branches with a local DB are the POS targets. HQ is left off
        # (no db_host today); admin can enable it once an HQ POS target exists.
        b.pos_enabled = (kind == 'retail')
        b.save(update_fields=['kind', 'pos_enabled'])


def backwards(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    Branch.objects.all().update(kind='retail', pos_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ('branches', '0006_branch_kind_branch_pos_enabled'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
