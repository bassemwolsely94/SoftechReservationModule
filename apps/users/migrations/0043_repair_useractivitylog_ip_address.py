"""Schema repair: users_useractivitylog.ip_address.

0008 created the table with CREATE TABLE IF NOT EXISTS. A database that already had an older
users_useractivitylog skipped it and never got the ip_address column, while Django's state says it
exists — so every write that names it fails (found 2026-11-03: approving a device on /access/devices
→ ProgrammingError 'column "ip_address" of relation "users_useractivitylog" does not exist').
A full model-vs-database column check on that database showed this was the only missing column.
Idempotent: adds the column only where it is missing; state is unchanged.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('users', '0042_tasks_module_incentives_owner')]
    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "users_useractivitylog" ADD COLUMN IF NOT EXISTS "ip_address" inet NULL;',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
