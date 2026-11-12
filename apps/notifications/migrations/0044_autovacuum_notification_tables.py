"""
Autovacuum settings for the notification tables (data lifecycle design, Stage 2).

Retention deletes old rows here in nightly batches. At the default trigger of 20% dead rows, these
760,000-row tables showed one autovacuum each (last on 2026-10-31) and took 1 GB and 487 MB on the
office database on 2026-11-07. A lower trigger reuses the space sooner. Notifications are written
all day, so the vacuum speed stays at the server default, unlike the engine tables that change in
batches.

ALTER TABLE ... SET takes a lock that does not block reads or writes, and rewrites nothing.
"""
from django.db import migrations

TABLES = (
    'notifications_notification',
    'notifications_notificationlog',
)

SETTINGS = """
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_analyze_threshold = 1000
"""

RESET = """
    autovacuum_vacuum_scale_factor,
    autovacuum_vacuum_threshold,
    autovacuum_analyze_scale_factor,
    autovacuum_analyze_threshold
"""


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0043_send_throttle'),
    ]

    operations = [
        migrations.RunSQL(
            sql=f'ALTER TABLE {table} SET ({SETTINGS})',
            reverse_sql=f'ALTER TABLE {table} RESET ({RESET})',
        )
        for table in TABLES
    ]
