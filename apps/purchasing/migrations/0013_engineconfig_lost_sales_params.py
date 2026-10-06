"""
Migration 0013 — Add MODULE 13 Lost Sales Intelligence parameters to EngineConfig.

Four new tunable float fields:
  ls_min_daily_demand       — skip very slow movers from stockout counting
  ls_bulk_sale_coverage_pct — detect bulk/institutional sales (main fix)
  ls_forecast_spike_ratio   — demand-spike threshold for root cause 'forecast'
  ls_bottleneck_days        — coverage threshold for 'bottleneck' classification
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0012_lost_sales_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='engineconfig',
            name='ls_min_daily_demand',
            field=models.FloatField(
                default=0.03,
                verbose_name='الحد الأدنى للطلب اليومي (مبيعات ضائعة)',
                help_text=(
                    'Items whose daily_demand (monthly_avg/30) is below this are excluded '
                    'from stockout detection. Default 0.03.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='engineconfig',
            name='ls_bulk_sale_coverage_pct',
            field=models.FloatField(
                default=0.85,
                verbose_name='نسبة تغطية المبيعات الكبيرة (bulk sale)',
                help_text=(
                    'If actual qty sold in 30d >= monthly_avg × this, treat as bulk sale '
                    '(demand fulfilled in large transactions) and set stockout_days=0. '
                    'Default 0.85 = 85%%.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='engineconfig',
            name='ls_forecast_spike_ratio',
            field=models.FloatField(
                default=1.35,
                verbose_name='معامل ارتفاع الطلب (توقعات)',
                help_text=(
                    'If rate_30d > rate_365d × this, root cause = "forecast". '
                    'Default 1.35 = 35%% above annual rate.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='engineconfig',
            name='ls_bottleneck_days',
            field=models.FloatField(
                default=7.0,
                verbose_name='أيام تغطية حد الاختناق',
                help_text=(
                    'Items with coverage_days < this while in stock = bottleneck. '
                    'Default 7 days.'
                ),
            ),
        ),
    ]
