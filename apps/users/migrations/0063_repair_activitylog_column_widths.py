"""Schema repair: users_useractivitylog column widths (UAT W8, 2026-11-20).

0008 created the table with CREATE TABLE IF NOT EXISTS, so a database that already had an older
users_useractivitylog kept the older column types (the same drift as 0043's missing ip_address).
On the office database (read-only check, 2026-11-20):

  action  varchar(20)   model CharField(max_length=30) -> 21+ char actions fail
                         ('mfa_devices_forgotten': forget-devices answered 500, audit row lost)
  note    varchar(255)  model TextField              -> a note over 255 characters fails

network (10), network_site (120) and user_agent (300) already match the model.

Idempotent: each column is widened ONLY where information_schema shows it narrower than the model;
a fresh database (already varchar(30) / text) is left untouched. Widening never loses data. Never
narrows. State is unchanged; reverse is a no-op. Found by `check_column_widths` /
`check_schema_drift` (kind `column_width`).
"""
from django.db import migrations

TABLE = 'users_useractivitylog'
# column -> target width (None = unlimited text, as the model's TextField)
WIDTHS = {
    'action': 30,
    'note': None,
}


def forwards(apps, schema_editor):
    conn = schema_editor.connection
    timeout_set = False

    def alter(cur, sql):
        # a busy audit table must not hang the deploy: give up after 5 s (this transaction only)
        nonlocal timeout_set
        if not timeout_set and conn.vendor == 'postgresql':
            cur.execute("SET LOCAL lock_timeout = '5s'")
            timeout_set = True
        cur.execute(sql)

    with conn.cursor() as cur:
        for column, width in WIDTHS.items():
            cur.execute(
                'SELECT data_type, character_maximum_length FROM information_schema.columns '
                'WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s',
                [TABLE, column],
            )
            row = cur.fetchone()
            if not row:
                continue                       # missing column: check_schema_drift reports it
            current = row[1]
            if current is None:
                continue                       # already text (unlimited)
            if width is None:
                alter(cur, f'ALTER TABLE "{TABLE}" ALTER COLUMN "{column}" TYPE text')
            elif current < width:
                alter(cur, f'ALTER TABLE "{TABLE}" ALTER COLUMN "{column}" TYPE varchar({int(width)})')


class Migration(migrations.Migration):
    dependencies = [('users', '0062_role_review_modules')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
