"""
apps/customers/migrations/0013_purchasehistoryline_cost_at_sale.py

Add cost_at_sale to PurchaseHistoryLine.
Stores stktrans.itemcostprice (cost recorded at time of each transaction) so
COGS and profit can be calculated from the authoritative per-line cost instead
of Item.cost_price (current catalog cost, changes on every sync).

This fixes the COGS / profit discrepancy between the dashboard and SOFTECH ERP.
After applying this migration, run a full sync to backfill historical lines:
    python manage.py run_sync --full
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0012_purchasehistory_softech_phcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchasehistoryline',
            name='cost_at_sale',
            field=models.DecimalField(
                decimal_places=3,
                default=0,
                help_text='stktrans.newcostprice — weighted-average cost per unit at time of transaction',
                max_digits=10,
                verbose_name='سعر التكلفة عند البيع',
            ),
        ),
    ]
