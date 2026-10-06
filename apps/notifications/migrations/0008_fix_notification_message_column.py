"""
Migration: notifications 0008

The live database has an old `message` column (TEXT NOT NULL) that was created
before the field was renamed to `body`. Django no longer tracks `message` in the
model, so INSERT statements omit it — violating the NOT NULL constraint.

Fix: make `message` nullable and set its default to '' so legacy rows are
preserved and new rows can be inserted without providing it.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0007_add_call_logged_type'),
    ]

    operations = [
        # Make the legacy `message` column optional so Django can insert
        # without supplying it (the model uses `body` for this purpose).
        migrations.RunSQL(
            sql="""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'notifications_notification'
                          AND column_name = 'message'
                    ) THEN
                        ALTER TABLE notifications_notification
                            ALTER COLUMN message DROP NOT NULL,
                            ALTER COLUMN message SET DEFAULT '';
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
