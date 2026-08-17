from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0013_purchasehistoryline_cost_at_sale'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchasehistory',
            name='trans_time',
            field=models.DateTimeField(
                blank=True, null=True, db_index=True,
                verbose_name='وقت المعاملة',
                help_text='stktrans.transtime — actual transaction clock time (used for hour filters)',
            ),
        ),
    ]
