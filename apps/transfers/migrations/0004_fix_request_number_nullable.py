from django.db import migrations


class Migration(migrations.Migration):
    """
    Previously fixed NOT NULL constraints on legacy columns that no longer
    exist after the table was recreated from 0001_initial. This migration
    is now a no-op — the fresh table already has the correct schema.
    """

    dependencies = [
        ('transfers', '0003_fix_request_number_nullable'),
    ]

    operations = []
