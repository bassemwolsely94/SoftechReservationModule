"""
apps/delivery/migrations/0003_delivery_softech_crm_fields.py

Add SOFTECH CRM integration fields to DeliveryOrder.
These fields link DeliveryOrder rows to piccrmorders in SOFTECH.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0002_delivery_overhaul'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliveryorder',
            name='softech_crm_order_no',
            field=models.IntegerField(
                blank=True, db_index=True, null=True, unique=True,
                verbose_name='رقم طلب CRM (SOFTECH)',
                help_text='piccrmorders.crmorderno',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='softech_crm_branch',
            field=models.CharField(
                blank=True, max_length=10,
                verbose_name='فرع CRM (SOFTECH)',
                help_text='piccrmorders.crmbranchcode',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='softech_order_usercode',
            field=models.CharField(
                blank=True, max_length=10,
                verbose_name='كود موظف CRM',
                help_text='piccrmorders.orderusercode',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='softech_order_status',
            field=models.SmallIntegerField(
                blank=True, null=True,
                verbose_name='حالة SOFTECH الخام',
                help_text='piccrmorders.orderstatus',
            ),
        ),
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(
                fields=['softech_crm_order_no'],
                name='del_order_crm_no',
            ),
        ),
    ]
