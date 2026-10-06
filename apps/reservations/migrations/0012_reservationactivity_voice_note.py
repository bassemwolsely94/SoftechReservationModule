"""
Migration: add voice_note FileField to ReservationActivity
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0011_reservation_channel'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservationactivity',
            name='voice_note',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='reservation_voices/%Y/%m/',
                verbose_name='ملاحظة صوتية',
            ),
        ),
    ]
