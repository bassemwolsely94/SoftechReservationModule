# Generated 2026-05-19 — add store_code and cust_branch_code to PurchaseHistory
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0010_cleanup_duplicate_invoices'),
    ]

    operations = [
        # stktrans.storecode — warehouse/store within the branch
        migrations.AddField(
            model_name='purchasehistory',
            name='store_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='stktrans.storecode — warehouse / store code within the branch',
                max_length=20,
                verbose_name='كود المخزن',
            ),
        ),
        # stktransm.cust_branch_code — customer ordering/delivery branch code
        migrations.AddField(
            model_name='purchasehistory',
            name='cust_branch_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='stktransm.cust_branch_code — ordering/delivery branch code for this customer',
                max_length=10,
                verbose_name='كود فرع العميل',
            ),
        ),
    ]
