from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('followups', '0001_initial'),
        ('customers', '0003_alter_purchasehistory_invoice_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='followuptask',
            name='customer',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='followup_tasks',
                to='customers.customer',
                verbose_name='العميل',
            ),
        ),
    ]
