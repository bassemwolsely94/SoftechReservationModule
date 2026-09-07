"""
0007_ensure_activity_tables

Migration 0004_reservationactivity was recorded as applied in django_migrations
but the CREATE TABLE never executed on the production database (the shared DB
had a different migration history during development).

This migration re-creates the tables using raw SQL with IF NOT EXISTS so it
is safe regardless of whether the tables already exist.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0006_ensure_image_column'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS reservations_reservationactivity (
                    id          bigserial PRIMARY KEY,
                    activity_type VARCHAR(30) NOT NULL DEFAULT 'note',
                    message     TEXT NOT NULL DEFAULT '',
                    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    attachment  VARCHAR(100) NULL,
                    transfer_request_id_ref INTEGER NULL,
                    created_by_id BIGINT NULL
                        REFERENCES users_staffprofile(id)
                        ON DELETE SET NULL
                        DEFERRABLE INITIALLY DEFERRED,
                    reservation_id BIGINT NOT NULL
                        REFERENCES reservations_reservation(id)
                        ON DELETE CASCADE
                        DEFERRABLE INITIALLY DEFERRED
                );

                CREATE TABLE IF NOT EXISTS reservations_reservationactivity_mentioned_users (
                    id                           bigserial PRIMARY KEY,
                    reservationactivity_id       BIGINT NOT NULL
                        REFERENCES reservations_reservationactivity(id)
                        ON DELETE CASCADE
                        DEFERRABLE INITIALLY DEFERRED,
                    staffprofile_id              BIGINT NOT NULL
                        REFERENCES users_staffprofile(id)
                        ON DELETE CASCADE
                        DEFERRABLE INITIALLY DEFERRED,
                    UNIQUE (reservationactivity_id, staffprofile_id)
                );

                CREATE INDEX IF NOT EXISTS reservations_activity_reservation_idx
                    ON reservations_reservationactivity (reservation_id);
                CREATE INDEX IF NOT EXISTS reservations_activity_created_by_idx
                    ON reservations_reservationactivity (created_by_id);
                CREATE INDEX IF NOT EXISTS reservations_activity_type_idx
                    ON reservations_reservationactivity (activity_type);
            """,
            reverse_sql="""
                DROP TABLE IF EXISTS reservations_reservationactivity_mentioned_users;
                DROP TABLE IF EXISTS reservations_reservationactivity;
            """,
        ),
    ]
