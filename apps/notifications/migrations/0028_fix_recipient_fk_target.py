"""
Migration: notifications 0028

Schema drift: the live database's FK on `notifications_notification.recipient_id`
references `auth_user`, but the model (and every migration since 0001) points it
at `users.StaffProfile`. The stored recipient_ids ARE StaffProfile ids, so the
constraint only held by coincidence — it blew up (sync_in_transit warnings) once
a StaffProfile id appeared that had no same-numbered auth_user row.

Fix: drop any recipient_id FK that references auth_user and recreate it against
users_staffprofile(id). Idempotent — a no-op on databases where the constraint
is already correct.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0027_pushsubscription_failure_count'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                DECLARE
                    con record;
                BEGIN
                    FOR con IN
                        SELECT c.conname
                        FROM pg_constraint c
                        WHERE c.conrelid = 'notifications_notification'::regclass
                          AND c.contype = 'f'
                          AND c.confrelid = 'auth_user'::regclass
                          AND (SELECT attname FROM pg_attribute
                               WHERE attrelid = c.conrelid AND attnum = c.conkey[1]) = 'recipient_id'
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE notifications_notification DROP CONSTRAINT %I',
                            con.conname
                        );
                    END LOOP;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint c
                        WHERE c.conrelid = 'notifications_notification'::regclass
                          AND c.contype = 'f'
                          AND c.confrelid = 'users_staffprofile'::regclass
                          AND (SELECT attname FROM pg_attribute
                               WHERE attrelid = c.conrelid AND attnum = c.conkey[1]) = 'recipient_id'
                    ) THEN
                        ALTER TABLE notifications_notification
                            ADD CONSTRAINT notifications_notifi_recipient_id_d055f3f0_fk_users_sta
                            FOREIGN KEY (recipient_id) REFERENCES users_staffprofile (id)
                            DEFERRABLE INITIALLY DEFERRED;
                    END IF;
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
