"""
Performance Stage 3: a plain btree on invoice_date, so MAX(invoice_date) (the freshness bar's
"sales data through", polled by every screen each minute) is an index lookup instead of a ~0.4 s
scan of the 1.1 GB table. Migration 0035's Cairo-date expression index cannot serve MAX(invoice_date).

CONCURRENTLY: the table is written every few minutes by the sales sync; a plain CREATE INDEX would
block those writes while it builds. Hence atomic = False.
"""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('customers', '0036_customer_found'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='purchasehistory',
            index=models.Index(fields=['invoice_date'], name='customers_ph_invoice_date_idx'),
        ),
    ]
