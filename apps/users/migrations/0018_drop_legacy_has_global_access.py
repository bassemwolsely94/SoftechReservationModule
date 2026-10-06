"""
Drop the legacy `has_global_access` column from users_staffprofile.

This column predates the current model (which uses `access_all_branches` plus a
`has_global_access` @property) and survives only on the production database — it
is NOT part of Django's model state or any migration. Its NOT NULL constraint
breaks fresh `StaffProfile` inserts via the ORM on production.

We use SeparateDatabaseAndState with an EMPTY state operation (Django's state
never knew about the column) and an idempotent database operation. `IF EXISTS`
is essential: a migration-built database (e.g. the CI test DB) never had the
column, so an unconditional DROP would error there.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_staffprofile_mfa_backup_codes_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],  # column was never in Django's model state
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE users_staffprofile DROP COLUMN IF EXISTS has_global_access;',
                    reverse_sql=(
                        'ALTER TABLE users_staffprofile '
                        'ADD COLUMN IF NOT EXISTS has_global_access boolean NOT NULL DEFAULT false;'
                    ),
                ),
            ],
        ),
    ]
