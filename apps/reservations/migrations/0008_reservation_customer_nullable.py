from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """
    Allow walk-in reservations — customer FK becomes nullable.
    Existing rows are unaffected (they all have a customer_id already).
    """

    dependencies = [
        ('customers', '__first__'),
        ('reservations', '0007_ensure_activity_tables'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reservation',
            name='customer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='reservations',
                to='customers.customer',
            ),
        ),
    ]
