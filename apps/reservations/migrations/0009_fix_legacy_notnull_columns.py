"""
0009_fix_legacy_notnull_columns

The production database has three extra NOT-NULL columns that were added by an
older version of the model but are absent from the current Django model.
Django's INSERT never includes these columns, so every reservation create fails
with a NOT NULL violation.

Fix: add DB-level DEFAULT values so INSERT succeeds without specifying them.
The column data is retained — we only change the default, not the type or data.

Columns patched:
  sales_transaction_id  VARCHAR  → DEFAULT ''
  is_erp_validated      BOOLEAN  → DEFAULT FALSE
  erp_validation_note   VARCHAR  → DEFAULT ''
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0008_reservation_customer_nullable'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    -- sales_transaction_id
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'reservations_reservation'
                          AND column_name = 'sales_transaction_id'
                    ) THEN
                        ALTER TABLE reservations_reservation
                            ALTER COLUMN sales_transaction_id SET DEFAULT '';
                    END IF;

                    -- is_erp_validated
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'reservations_reservation'
                          AND column_name = 'is_erp_validated'
                    ) THEN
                        ALTER TABLE reservations_reservation
                            ALTER COLUMN is_erp_validated SET DEFAULT FALSE;
                    END IF;

                    -- erp_validation_note
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'reservations_reservation'
                          AND column_name = 'erp_validation_note'
                    ) THEN
                        ALTER TABLE reservations_reservation
                            ALTER COLUMN erp_validation_note SET DEFAULT '';
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
