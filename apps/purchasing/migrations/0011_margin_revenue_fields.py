"""
Migration 0011 — Margin revenue fields

Adds three fields required for gross-margin and net-after-discount margin calculations:

  SalesTransactionLine.net_revenue
    Actual line revenue from SOFTECH stktrans.transprice_total, sign-corrected:
    + for sales (doccode '115'), - for returns (doccode '30').

  ItemDemandMetrics.net_sales_revenue
    Rolling 365-day sum of net_revenue per (item, branch).
    Used to compute net margin % = (avg_actual_price - cost_price) / pack_price.

  ItemDemandAggregated.total_net_sales_revenue
    Network-level (all branches) sum of net_sales_revenue for the same item.
    Used for the aggregated ABC tab net margin.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0010_alter_engineconfig_ss_high_threshold_and_more'),
    ]

    operations = [
        # ── SalesTransactionLine.net_revenue ──────────────────────────────────
        migrations.AddField(
            model_name='salestransactionline',
            name='net_revenue',
            field=models.DecimalField(
                default=0,
                decimal_places=3,
                max_digits=18,
                help_text='Actual line revenue: +transprice_total for sales, -transprice_total for returns',
            ),
        ),

        # ── ItemDemandMetrics.net_sales_revenue ───────────────────────────────
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='net_sales_revenue',
            field=models.DecimalField(
                default=0,
                decimal_places=2,
                max_digits=18,
                verbose_name='الإيرادات الفعلية (365 يوم)',
                help_text='SUM of net_revenue from SalesTransactionLine over rolling 365-day window',
            ),
        ),

        # ── ItemDemandAggregated.total_net_sales_revenue ──────────────────────
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='total_net_sales_revenue',
            field=models.DecimalField(
                default=0,
                decimal_places=2,
                max_digits=20,
                verbose_name='إجمالي الإيرادات الفعلية (شبكة)',
            ),
        ),
    ]
