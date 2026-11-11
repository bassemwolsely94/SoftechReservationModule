"""
Server-side defaults for the browser-phone columns added in 0010.

0010 first shipped without db_default, so a database migrated before this fix has the
columns NOT NULL with no DEFAULT: a process still running older code (the long-lived
scheduler, before a deploy) would insert AgentExtension rows without them and fail.
0010 now declares db_default for fresh databases; this sets the same defaults on
databases that already ran the old 0010. SET DEFAULT is idempotent. Reversible.
Same pattern as customers 0030.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('pbx', '0010_agent_webrtc'),
    ]
    operations = [
        migrations.RunSQL(
            sql=("ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_enabled SET DEFAULT false; "
                 "ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_credentials SET DEFAULT '{}'::jsonb;"),
            reverse_sql=("ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_enabled DROP DEFAULT; "
                         "ALTER TABLE pbx_agentextension ALTER COLUMN webrtc_credentials DROP DEFAULT;"),
        ),
    ]
