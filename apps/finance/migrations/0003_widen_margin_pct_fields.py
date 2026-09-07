# Generated manually 2026-05-23
#
# Widens gross_margin_pct and net_margin_pct on FinancialSnapshot from
# DecimalField(max_digits=8, decimal_places=4)  →  (max_digits=10, decimal_places=2)
#
# Reason: HQ/distribution branches have near-zero direct customer sales but
# absorb all supplier purchases, producing extreme negative margin ratios
# (e.g. -34,000%) that overflow the original precision-8/scale-4 field.
# The new type allows values up to ±99,999,999.99 while reducing decimal noise.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0002_rename_finance_acc_account_type_idx_finance_acc_account_3b66f3_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="financialsnapshot",
            name="gross_margin_pct",
            field=models.DecimalField(
                max_digits=10,
                decimal_places=2,
                default=0,
                help_text=(
                    "Gross margin % = gross_profit / net_revenue × 100. "
                    "Stored as 0 for branches where net_revenue <= 0 or the "
                    "ratio exceeds ±99,999.99 (e.g. HQ distribution hubs)."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="financialsnapshot",
            name="net_margin_pct",
            field=models.DecimalField(
                max_digits=10,
                decimal_places=2,
                default=0,
                help_text=(
                    "Net margin % = net_profit / net_revenue × 100. "
                    "Stored as 0 when net_revenue <= 0."
                ),
            ),
        ),
    ]
