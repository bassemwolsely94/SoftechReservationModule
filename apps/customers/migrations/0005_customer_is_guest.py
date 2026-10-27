from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add is_guest flag to Customer.
    Existing customers are normal SOFTECH-synced records → default False.
    New walk-in customers entered by staff get is_guest=True until merged.
    """

    dependencies = [
        ('customers', '0004_chronic_module_and_purchase_history_erp_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='is_guest',
            field=models.BooleanField(
                default=False,
                help_text='زبون مؤقت — سيتم دمجه تلقائياً عند مزامنة رقم هاتفه من SOFTECH',
            ),
        ),
    ]
