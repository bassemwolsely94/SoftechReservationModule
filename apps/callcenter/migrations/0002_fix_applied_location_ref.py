"""
Migration to fix applied_location_ref column mismatch.
The DB has applied_location_id (old FK) but the model expects
applied_location_ref (CharField). Add the missing CharField column.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('callcenter', '0001_chronic_module_and_purchase_history_erp_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE callcenter_addressupdate
                    ADD COLUMN IF NOT EXISTS applied_location_ref VARCHAR(100) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE callcenter_addressupdate
                    DROP COLUMN IF EXISTS applied_location_ref;
            """,
        ),
    ]
