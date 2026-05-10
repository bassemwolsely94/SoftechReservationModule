from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Make Item.phcode nullable.

    Many SOFTECH items have no phcode (ATC code).  The original migration
    added the column as NOT NULL with no persistent DB-level default, which
    causes IntegrityErrors when the legacy sync code inserts items without
    mentioning the column.  Allowing NULL is also semantically correct:
    absence of a phcode is different from an empty string.
    """

    dependencies = [
        ('catalog', '0003_item_phcode_chronicmedication'),
    ]

    operations = [
        migrations.AlterField(
            model_name='item',
            name='phcode',
            field=models.CharField(
                blank=True,
                null=True,
                db_index=True,
                max_length=20,
                verbose_name='ATC / phcode',
            ),
        ),
    ]
