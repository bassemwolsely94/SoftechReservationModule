"""
0003_purchaseline_tax_rate_pct

Adds tax_rate_pct to PurchaseLine.
This field stores AVG(stktrans.origintaxp) per grouped purchase line —
the tax-rate percentage (e.g. 14.00 for Egypt's 14% VAT).

vat_value was already added in 0002 and is populated from
SUM(stktrans.itemsalestax) — the absolute tax amount in local currency.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('procurement', '0002_supplier_segmentation_foc_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseline',
            name='tax_rate_pct',
            field=models.DecimalField(
                default=0,
                max_digits=7,
                decimal_places=2,
                verbose_name='نسبة الضريبة %',
            ),
        ),
    ]
