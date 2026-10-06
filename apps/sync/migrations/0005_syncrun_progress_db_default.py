"""
SyncRun.progress got a Python-side default (0004) but the column is NOT NULL with no
DATABASE default — so a process still running code from before 0004 (the long-lived
run_scheduler) inserts SyncRun rows without the column and every fast-sync failed
(2026-09-28 23:17 → 2026-09-29). A '{}' database default makes old and new code both
insert cleanly. Django 4.2 has no db_default, hence RunSQL (reversible).
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0004_syncrun_progress'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE sync_syncrun ALTER COLUMN progress SET DEFAULT '{}'::jsonb;",
            reverse_sql="ALTER TABLE sync_syncrun ALTER COLUMN progress DROP DEFAULT;",
        ),
    ]
