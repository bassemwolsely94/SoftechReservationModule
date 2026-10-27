"""
0003_fix_branch_indexes

Sync the composite indexes after renaming source_branch / destination_branch
to requesting_branch / supplying_branch.  Uses IF EXISTS / IF NOT EXISTS so
this is safe regardless of current index state in the DB.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0002_transferrequest_delivery_tracking'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP INDEX IF EXISTS transfers_t_status_69e49b_idx;
                DROP INDEX IF EXISTS transfers_t_status_2c00e7_idx;
                CREATE INDEX IF NOT EXISTS transfers_t_status_1e0631_idx
                    ON transfers_transferrequest (status, requesting_branch_id);
                CREATE INDEX IF NOT EXISTS transfers_t_status_e50678_idx
                    ON transfers_transferrequest (status, supplying_branch_id);
                CREATE INDEX IF NOT EXISTS transfers_t_created_idx
                    ON transfers_transferrequest (created_at);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS transfers_t_status_1e0631_idx;
                DROP INDEX IF EXISTS transfers_t_status_e50678_idx;
                DROP INDEX IF EXISTS transfers_t_created_idx;
            """,
        ),
    ]
