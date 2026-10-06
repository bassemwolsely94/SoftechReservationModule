"""
Migration: purchasing 0003

Add performance indexes to SalesTransactionLine to accelerate the two
most expensive queries in the demand engine:

  1. stl_agg_sales_idx  — PARTIAL index on (item_id, branch_id, doc_date)
     WHERE item_id IS NOT NULL AND branch_id IS NOT NULL

     Accelerates PG_AGGREGATE_SQL (MODULE 3).  The WHERE clause matches the
     filter on the aggregation query exactly, so PostgreSQL uses this index
     for an index scan instead of a full sequential scan on every daily run.

  2. stl_sync_at_idx   — index on synced_at

     Accelerates maintenance / monitoring queries that look up recently synced
     rows (e.g. "how many rows were updated in the last sync?").

Note: these are non-CONCURRENTLY indexes (safe to run in a migration
transaction).  On a table with existing data the migration will hold an
AccessShareLock during index build.  For large tables (>1M rows), run
during off-peak hours or apply manually with CREATE INDEX CONCURRENTLY
and fake this migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0002_salestransactionline_and_new_metric_fields'),
    ]

    operations = [

        # ── Partial index for MODULE 3 aggregation query ──────────────────────
        # Covers: WHERE item_id IS NOT NULL AND branch_id IS NOT NULL AND doc_date >= ?
        # Also covers: GROUP BY item_id, branch_id
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS stl_agg_sales_idx
                    ON purchasing_salestransactionline (item_id, branch_id, doc_date)
                    WHERE item_id IS NOT NULL
                      AND branch_id IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS stl_agg_sales_idx;",
        ),

        # ── Index on synced_at for maintenance / monitoring queries ───────────
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS stl_synced_at_idx
                    ON purchasing_salestransactionline (synced_at);
            """,
            reverse_sql="DROP INDEX IF EXISTS stl_synced_at_idx;",
        ),

    ]
