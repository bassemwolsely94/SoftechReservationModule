# Adds local_customer FK (erp.LocalCustomer) and phcode CharField to FollowUpTask.
# Allows name + phone to be resolved even for tasks whose customer FK is NULL
# (i.e. ERP-phcode customers not yet linked to customers.Customer).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('erp', '0001_initial'),         # erp app must exist
        ('followups', '0008_followuptask_sales_channel'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='local_customer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='followup_tasks',
                to='erp.localcustomer',
                verbose_name='عميل محلي (PIC)',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='phcode',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                max_length=30,
                verbose_name='كود ERP (phcode)',
            ),
        ),
    ]
