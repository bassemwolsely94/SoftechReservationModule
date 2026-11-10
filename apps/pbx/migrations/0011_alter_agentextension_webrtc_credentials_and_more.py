# Sets the server defaults on databases that already applied 0010 before it carried them.
# Migration rule R6 (apps/tests/test_migration_rules.py): writers on older code (deploy window)
# or raw SQL that do not name these columns must not hit a NOT NULL error.
#
# Explicit SQL, not AlterField: 0010 now records db_default in its migration state, so an
# AlterField here would diff state against state, emit nothing and leave an already-migrated
# database without the defaults. SET DEFAULT is idempotent — harmless on a fresh database.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pbx', '0010_agent_webrtc'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_credentials SET DEFAULT '{}'::jsonb;",
                "ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_enabled SET DEFAULT false;",
            ],
            reverse_sql=migrations.RunSQL.noop,   # 0010's state keeps the defaults
        ),
    ]
