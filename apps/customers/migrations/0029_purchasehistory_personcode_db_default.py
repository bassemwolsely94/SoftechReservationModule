"""
Give customers_purchasehistory.softech_personcode a DB-level DEFAULT ''.

Django 4.2's CharField(blank=True) has no server default: 0028 created the column
NOT NULL with nothing behind it. A run_scheduler process started before 0028 still
built PurchaseHistory without the field, so its INSERT … ON CONFLICT left the column
out → null → the whole fast-sync bulk_create aborted every tick from 2026-10-28 02:58
(first row of the batch: receipt 140-30-15560-20261028), blocking every later sale.

'' is what the field already means when unknown (blank=True; 0028 back-filled every
existing row with ''). The next correct sync rewrites it via ON CONFLICT (it is in
sync_sales' update_fields). Same pattern as catalog 0027. Reversible (DROP DEFAULT).
"""
from django.db import migrations


def _set_default(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute("ALTER TABLE customers_purchasehistory ALTER COLUMN softech_personcode SET DEFAULT ''")


def _drop_default(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute('ALTER TABLE customers_purchasehistory ALTER COLUMN softech_personcode DROP DEFAULT')


class Migration(migrations.Migration):
    dependencies = [
        ('customers', '0028_account_placeholder_and_personcode'),
    ]
    operations = [
        migrations.RunPython(_set_default, _drop_default),
    ]
