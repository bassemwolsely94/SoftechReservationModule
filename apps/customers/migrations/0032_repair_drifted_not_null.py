"""Schema repair (owner approved 2026-11-05): two columns the models allow empty were NOT NULL in a
long-lived database, so inserts without a value failed. Found by `check_schema_drift` on the office
database (round-2 R0):

  users_useractivitylog.target_user_id   model null=True, database NOT NULL
  customers_purchasehistory.invoice_date model null=True, database NOT NULL

DROP NOT NULL is a no-op where the column is already nullable, so this is safe on every database
(fresh test databases and the VPS included). The two columns that were the other way round (the
database looser than the model — notifications body, staffprofile updated_at) are harmless and left
alone. Lives in `customers` so it does not race another branch's next `users` migration.
"""
from django.db import migrations

REPAIRS = (
    ('users_useractivitylog', 'target_user_id'),
    ('customers_purchasehistory', 'invoice_date'),
)


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        for table, column in REPAIRS:
            cur.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')


class Migration(migrations.Migration):
    dependencies = [
        ('customers', '0031_customer_softech_created_at'),
        ('users', '0008_erpuser_staffprofile_extensions_useractivitylog'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
