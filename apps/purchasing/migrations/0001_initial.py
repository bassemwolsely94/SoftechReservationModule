from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog',  '0006_rename_item_price_fields'),
        ('branches', '0001_initial'),
    ]

    operations = [
        # ── DemandCalculationRun ──────────────────────────────────────────────
        migrations.CreateModel(
            name='DemandCalculationRun',
            fields=[
                ('id',                  models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at',          models.DateTimeField(auto_now_add=True, db_index=True)),
                ('finished_at',         models.DateTimeField(blank=True, null=True)),
                ('status',              models.CharField(choices=[('running', 'جارٍ'), ('success', 'نجح'), ('partial', 'جزئي'), ('failed', 'فشل')], default='running', max_length=10)),
                ('branches_processed',  models.PositiveIntegerField(default=0)),
                ('items_processed',     models.PositiveIntegerField(default=0)),
                ('rows_written',        models.PositiveIntegerField(default=0)),
                ('calc_date',           models.DateField(blank=True, db_index=True, help_text='الحقبة الزمنية للحساب (عادةً اليوم)', null=True)),
                ('softech_available',   models.BooleanField(default=False)),
                ('error_message',       models.TextField(blank=True)),
                ('duration_seconds',    models.FloatField(blank=True, null=True)),
            ],
            options={
                'verbose_name':        'تشغيل محرك الطلب',
                'verbose_name_plural': 'تشغيلات محرك الطلب',
                'ordering':            ['-started_at'],
            },
        ),

        # ── ItemDemandMetrics ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='ItemDemandMetrics',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('calc_date',       models.DateField(db_index=True, help_text='تاريخ الحساب')),
                ('qty_30d',         models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name='المبيعات الصافية (30 يوم)')),
                ('qty_90d',         models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name='المبيعات الصافية (90 يوم)')),
                ('qty_365d',        models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name='المبيعات الصافية (365 يوم)')),
                ('invoices_30d',    models.PositiveIntegerField(default=0)),
                ('invoices_90d',    models.PositiveIntegerField(default=0)),
                ('invoices_365d',   models.PositiveIntegerField(default=0)),
                ('rate_30d',        models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='معدل الشهر (30 يوم)')),
                ('rate_90d',        models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='معدل الشهر (90 يوم)')),
                ('rate_365d',       models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='معدل الشهر (365 يوم)')),
                ('monthly_avg',     models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='المتوسط الشهري الموزون')),
                ('safety_stock',    models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='مخزون الأمان')),
                ('current_stock',   models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name='المخزون الحالي')),
                ('coverage_months', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='تغطية (شهور)')),
                ('gap',             models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name='الفجوة (وحدات)')),
                ('priority',        models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='الأولوية')),
                ('abc_class',       models.CharField(choices=[('A', 'A — الأكثر قيمةً (أعلى 70% من الإيرادات)'), ('B', 'B — متوسط القيمة (70–90%)'), ('C', 'C — أقل قيمةً (90–100%)'), ('X', 'X — لا مبيعات خلال السنة')], db_index=True, default='X', max_length=1, verbose_name='تصنيف ABC')),
                ('pack_price',      models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='سعر العبوة (وقت الحساب)')),
                ('monthly_value',   models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name='القيمة الشهرية = معدل × سعر')),
                ('last_sale_date',  models.DateField(blank=True, null=True, verbose_name='آخر بيعة في الفرع')),
                ('run',    models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='metrics',    to='purchasing.demandcalculationrun')),
                ('item',   models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='demand_metrics',  to='catalog.item')),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='demand_metrics', to='branches.branch')),
            ],
            options={
                'verbose_name':        'مقاييس الطلب',
                'verbose_name_plural': 'مقاييس الطلب',
                'ordering':            ['-priority'],
            },
        ),
        migrations.AddConstraint(
            model_name='itemdemandmetrics',
            constraint=models.UniqueConstraint(fields=['run', 'item', 'branch'], name='unique_run_item_branch'),
        ),
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(fields=['calc_date', 'branch'], name='purch_metrics_date_branch'),
        ),
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(fields=['calc_date', 'abc_class'], name='purch_metrics_date_abc'),
        ),
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(fields=['calc_date', 'priority'], name='purch_metrics_date_priority'),
        ),
        migrations.AddIndex(
            model_name='itemdemandmetrics',
            index=models.Index(fields=['item', 'branch', 'calc_date'], name='purch_metrics_item_branch_date'),
        ),

        # ── ItemDemandAggregated ──────────────────────────────────────────────
        migrations.CreateModel(
            name='ItemDemandAggregated',
            fields=[
                ('id',                   models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('calc_date',            models.DateField(db_index=True)),
                ('total_qty_30d',        models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('total_qty_90d',        models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('total_qty_365d',       models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('total_monthly_avg',    models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name='المتوسط الشهري الشبكي')),
                ('total_current_stock',  models.DecimalField(decimal_places=3, default=0, max_digits=16, verbose_name='إجمالي المخزون')),
                ('total_monthly_value',  models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name='القيمة الشهرية الشبكية')),
                ('total_gap',            models.DecimalField(decimal_places=3, default=0, max_digits=16, verbose_name='إجمالي الفجوة')),
                ('abc_class',            models.CharField(choices=[('A', 'A — الأكثر قيمةً (أعلى 70% من الإيرادات)'), ('B', 'B — متوسط القيمة (70–90%)'), ('C', 'C — أقل قيمةً (90–100%)'), ('X', 'X — لا مبيعات خلال السنة')], db_index=True, default='X', max_length=1)),
                ('cumulative_pct',       models.DecimalField(decimal_places=3, default=0, help_text='النسبة التراكمية للقيمة الشبكية', max_digits=6)),
                ('branches_with_sales',  models.PositiveSmallIntegerField(default=0)),
                ('branches_with_gap',    models.PositiveSmallIntegerField(default=0)),
                ('pack_price',           models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ('run',  models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='aggregated', to='purchasing.demandcalculationrun')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='demand_aggregated', to='catalog.item')),
            ],
            options={
                'verbose_name':        'إجماليات الطلب (شبكة)',
                'verbose_name_plural': 'إجماليات الطلب (شبكة)',
                'ordering':            ['-total_monthly_value'],
            },
        ),
        migrations.AddConstraint(
            model_name='itemdemandaggregated',
            constraint=models.UniqueConstraint(fields=['run', 'item'], name='unique_run_item_agg'),
        ),
        migrations.AddIndex(
            model_name='itemdemandaggregated',
            index=models.Index(fields=['calc_date', 'abc_class'], name='purch_agg_date_abc'),
        ),
        migrations.AddIndex(
            model_name='itemdemandaggregated',
            index=models.Index(fields=['calc_date', 'total_monthly_value'], name='purch_agg_date_value'),
        ),
    ]
