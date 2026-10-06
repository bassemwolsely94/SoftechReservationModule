"""
Migration to fix mismatched ERP transaction columns.

The DB was originally created with source_erp_transaction and
closing_erp_transaction as ForeignKeys (creating _id columns).
The model changed them to CharFields but the DB wasn't updated.

This migration adds the CharField columns the model now expects.
The old _id columns (FK remnants) are left intact to avoid data loss.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('followups', '0004_chronic_module_and_purchase_history_erp_fields'),
    ]

    operations = [
        migrations.RunSQL(
            # Add CharField columns that the model expects
            sql="""
                ALTER TABLE followups_followuptask
                    ADD COLUMN IF NOT EXISTS source_erp_transaction VARCHAR(50) NOT NULL DEFAULT '';
                ALTER TABLE followups_followuptask
                    ADD COLUMN IF NOT EXISTS closing_erp_transaction VARCHAR(50) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE followups_followuptask
                    DROP COLUMN IF EXISTS source_erp_transaction;
                ALTER TABLE followups_followuptask
                    DROP COLUMN IF EXISTS closing_erp_transaction;
            """,
        ),
    ]
