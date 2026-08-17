"""Add forecast fields to ItemDemandMetrics."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0014_remove_itemdemandmetrics_purch_metrics_run_root_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='seasonal_index',
            field=models.DecimalField(decimal_places=4, max_digits=6, null=True, blank=True, verbose_name='المؤشر الموسمي'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='yoy_growth_rate',
            field=models.DecimalField(decimal_places=4, max_digits=7, null=True, blank=True, verbose_name='معدل النمو السنوي'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='forecast_next_30d',
            field=models.DecimalField(decimal_places=2, max_digits=12, null=True, blank=True, verbose_name='توقع 30 يوم'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='forecast_next_90d',
            field=models.DecimalField(decimal_places=2, max_digits=12, null=True, blank=True, verbose_name='توقع 90 يوم'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='forecast_confidence',
            field=models.DecimalField(decimal_places=4, max_digits=5, null=True, blank=True, verbose_name='درجة ثقة التوقع (0–1)'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='expected_stockout_date',
            field=models.DateField(null=True, blank=True, verbose_name='تاريخ النفاد المتوقع'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='expected_expiry_risk_value',
            field=models.DecimalField(decimal_places=2, max_digits=12, null=True, blank=True, verbose_name='قيمة خطر الانتهاء المتوقع'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='demand_pattern',
            field=models.CharField(
                choices=[
                    ('trend_up',  'اتجاه تصاعدي'),
                    ('trend_down','اتجاه تنازلي'),
                    ('stable',    'مستقر'),
                    ('cyclical',  'دوري'),
                    ('spike',     'طفرة'),
                    ('anomaly',   'شاذ'),
                ],
                max_length=15, null=True, blank=True, db_index=True, verbose_name='نمط الطلب',
            ),
        ),
    ]
