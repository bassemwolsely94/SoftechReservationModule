"""
0012_lost_sales_fields.py

MODULE 13 — Lost Sales Intelligence.

Adds 8 fields to ItemDemandMetrics, 4 fields to ItemDemandAggregated,
and creates the LostSalesRun audit-log model.

All new fields have safe defaults so existing rows stay valid.
Migration is additive only — no column drops, no renames.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0011_margin_revenue_fields'),
    ]

    operations = [
        # ── ItemDemandMetrics — 8 new lost-sales fields ───────────────────────
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='coverage_days',
            field=models.FloatField(
                blank=True, null=True,
                verbose_name='أيام التغطية (من اليوم)',
                help_text='current_stock ÷ (monthly_avg / 30)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='stockout_days_30d',
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name='أيام النفاد (30 يوم)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='bottleneck_days_30d',
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name='أيام الاختناق (30 يوم)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='lost_qty_30d',
            field=models.DecimalField(
                max_digits=14, decimal_places=3, default=0,
                verbose_name='الكمية الضائعة (30 يوم)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='lost_revenue_30d',
            field=models.DecimalField(
                max_digits=18, decimal_places=2, default=0,
                verbose_name='الإيراد الضائع (30 يوم) ج.م',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='lost_margin_30d',
            field=models.DecimalField(
                max_digits=18, decimal_places=2, default=0,
                verbose_name='هامش الربح الضائع (30 يوم) ج.م',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='availability_rate_30d',
            field=models.FloatField(
                default=100.0,
                verbose_name='معدل التوفر (30 يوم) %',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='root_cause',
            field=models.CharField(
                blank=True,
                choices=[
                    ('purchasing', 'شراء — لم يُطلَب بما يكفي'),
                    ('supplier',   'مورد — تأخر التوريد'),
                    ('transfer',   'تحويل — متاح في فرع آخر'),
                    ('expiry',     'انتهاء صلاحية — مردودات منتهية'),
                    ('forecast',   'توقع — ارتفاع مفاجئ في الطلب'),
                    ('unknown',    'غير محدد'),
                ],
                db_index=True,
                default='unknown',
                max_length=15,
                verbose_name='السبب الجذري',
            ),
        ),

        # ── ItemDemandAggregated — 4 new network lost-sales fields ────────────
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='total_lost_qty_30d',
            field=models.DecimalField(
                max_digits=16, decimal_places=3, default=0,
                verbose_name='إجمالي الكمية الضائعة (30 يوم)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='total_lost_revenue_30d',
            field=models.DecimalField(
                max_digits=20, decimal_places=2, default=0,
                verbose_name='إجمالي الإيراد الضائع (30 يوم) ج.م',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='total_lost_margin_30d',
            field=models.DecimalField(
                max_digits=20, decimal_places=2, default=0,
                verbose_name='إجمالي الهامش الضائع (30 يوم) ج.م',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='network_availability_rate_30d',
            field=models.FloatField(
                default=100.0,
                verbose_name='متوسط معدل توفر الشبكة (30 يوم) %',
            ),
        ),

        # ── LostSalesRun — new audit-log model ────────────────────────────────
        migrations.CreateModel(
            name='LostSalesRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('started_at',   models.DateTimeField(auto_now_add=True)),
                ('finished_at',  models.DateTimeField(blank=True, null=True)),
                ('status',       models.CharField(
                    choices=[
                        ('pending', 'انتظار'),
                        ('running', 'جارٍ'),
                        ('success', 'نجح'),
                        ('failed',  'فشل'),
                    ],
                    default='pending', max_length=10,
                )),
                ('error_message',       models.TextField(blank=True)),
                ('items_affected',      models.PositiveIntegerField(default=0)),
                ('branch_item_pairs',   models.PositiveIntegerField(default=0)),
                ('total_lost_revenue',  models.DecimalField(max_digits=20, decimal_places=2, default=0)),
                ('total_lost_margin',   models.DecimalField(max_digits=20, decimal_places=2, default=0)),
                ('root_cause_breakdown', models.JSONField(blank=True, default=dict)),
                ('demand_run', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lost_sales_run',
                    to='purchasing.demandcalculationrun',
                    verbose_name='تشغيل محرك الطلب',
                )),
            ],
            options={
                'verbose_name':        'تشغيل محرك المبيعات الضائعة',
                'verbose_name_plural': 'تشغيلات محرك المبيعات الضائعة',
                'ordering':            ['-started_at'],
            },
        ),

        # ── Add index for root_cause queries ──────────────────────────────────
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(
                fields=['run', 'root_cause'],
                name='purch_metrics_run_root',
            ),
        ),
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(
                fields=['calc_date', 'lost_revenue_30d'],
                name='purch_metrics_lost_rev',
            ),
        ),
    ]
