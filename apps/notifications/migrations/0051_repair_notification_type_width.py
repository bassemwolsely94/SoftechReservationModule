"""Schema repair: notifications_notification.notification_type width (2FA reset review F2,
2026-11-21).

Same drift as users 0063 (an older table kept by CREATE TABLE IF NOT EXISTS). On the office
database notification_type is varchar(30) while the model says CharField(max_length=40), so a type
over 30 characters cannot be stored.

The target width is read from the model (not hard-coded). Idempotent: widened ONLY where
information_schema shows it narrower than the model; a fresh database is left untouched. Widening
never loses data (its indexes are rebuilt by PostgreSQL). Never narrows. State is unchanged;
reverse is a no-op.
"""
from django.db import migrations

APP, MODEL, TABLE = 'notifications', 'Notification', 'notifications_notification'
COLUMNS = ('notification_type',)


def _model(apps):
    if apps is None:                          # called directly (tests)
        from django.apps import apps as live_apps
        return live_apps.get_model(APP, MODEL)
    return apps.get_model(APP, MODEL)


def forwards(apps, schema_editor):
    model = _model(apps)
    conn = schema_editor.connection
    timeout_set = False

    def alter(cur, sql):
        # a busy table must not hang the deploy: give up after 5 s (this transaction only)
        nonlocal timeout_set
        if not timeout_set and conn.vendor == 'postgresql':
            cur.execute("SET LOCAL lock_timeout = '5s'")
            timeout_set = True
        cur.execute(sql)

    with conn.cursor() as cur:
        for column in COLUMNS:
            width = model._meta.get_field(column).max_length
            cur.execute(
                'SELECT data_type, character_maximum_length FROM information_schema.columns '
                'WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s',
                [TABLE, column],
            )
            row = cur.fetchone()
            if not row:
                continue                       # missing column: check_schema_drift reports it
            current = row[1]
            if current is None or not width:
                continue                       # already text (unlimited)
            if current < width:
                alter(cur, f'ALTER TABLE "{TABLE}" ALTER COLUMN "{column}" TYPE varchar({int(width)})')


class Migration(migrations.Migration):
    dependencies = [('notifications', '0050_c31_fridge_log')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
