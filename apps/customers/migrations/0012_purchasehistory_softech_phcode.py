"""
apps/customers/migrations/0012_purchasehistory_softech_phcode.py

Add softech_phcode field to PurchaseHistory.
Stores stktransm.phcode (customer PIC per invoice) so distinct-PIC counts
can be computed directly from invoice data — fixes the 31 vs 278 discrepancy
caused by the previous approach of traversing customer__softech_pic.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0011_purchasehistory_store_code_cust_branch_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchasehistory',
            name='softech_phcode',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='stktransm.phcode — customer PIC stamped on this invoice header',
                max_length=20,
                verbose_name='كود PIC العميل',
            ),
            preserve_default=False,
        ),
    ]
