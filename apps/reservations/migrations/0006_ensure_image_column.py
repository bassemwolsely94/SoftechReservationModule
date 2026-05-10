"""
0006_ensure_image_column

Migration 0003_reservation_image was recorded as applied but the ALTER TABLE
never ran (Pillow was not installed when the migration first executed).
This migration re-adds the column using raw SQL with IF NOT EXISTS so it is
safe to run even if the column was already created by 0003.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0005_reservationdownpayment'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE reservations_reservation
                ADD COLUMN IF NOT EXISTS image VARCHAR(100) NULL;
            """,
            reverse_sql="""
                ALTER TABLE reservations_reservation
                DROP COLUMN IF EXISTS image;
            """,
        ),
    ]
