"""
Autovacuum settings for the demand engine's output tables (data lifecycle design, Stage 2).

Each engine run rewrites a large share of these tables, and the default trigger of 20% dead rows
lets empty space build up between vacuums. A vacuum makes that space reusable; it does not shrink
the files (see manage.py reclaim_space). Measured on the office database on 2026-11-07:
itemdemandmetrics held 2.5 GB for about 138 MB of real row data.

ALTER TABLE ... SET takes a lock that does not block reads or writes, and rewrites nothing.
"""
from django.db import migrations

TABLES = (
    'purchasing_itemdemandmetrics',
    'purchasing_itemdemandaggregated',
    'purchasing_transferrecommendation',
)

SETTINGS = """
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_insert_scale_factor = 0.05,
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_analyze_threshold = 5000,
    autovacuum_vacuum_cost_limit = 500
"""

RESET = """
    autovacuum_vacuum_scale_factor,
    autovacuum_vacuum_threshold,
    autovacuum_vacuum_insert_scale_factor,
    autovacuum_analyze_scale_factor,
    autovacuum_analyze_threshold,
    autovacuum_vacuum_cost_limit
"""


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0043_dead_stock'),
    ]

    operations = [
        migrations.RunSQL(
            sql=f'ALTER TABLE {table} SET ({SETTINGS})',
            reverse_sql=f'ALTER TABLE {table} RESET ({RESET})',
        )
        for table in TABLES
    ]
