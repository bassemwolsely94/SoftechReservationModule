"""
Empty placeholder — resolves the leaf-node conflict between
0007_ensure_activity_tables and this file.
The actual channel field is added in 0011_reservation_channel.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0006_ensure_image_column'),
    ]

    operations = []
