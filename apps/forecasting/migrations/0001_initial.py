from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog',  '0001_initial'),
        ('branches', '0001_initial'),
        ('users',    '0001_initial'),
    ]

    operations = [
        # ── SeasonalityIndex ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='SeasonalityIndex',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('month',               models.PositiveSmallIntegerField(verbose_name='الشهر (1–12)')),
                ('index_value',         models.DecimalField(decimal_places=4, max_digits=6, verbose_name='قيمة المؤشر')),
                ('computed_from_years', models.PositiveSmallIntegerField(default=1, verbose_name='عدد السنوات المستخدمة')),
                ('computed_at',         models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')),
                ('item',     models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='seasonality_indices', to='catalog.item',     verbose_name='الصنف')),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='seasonality_indices', to='catalog.category', verbose_name='الفئة')),
            ],
            options={'ordering': ['item', 'category', 'month'], 'verbose_name': 'مؤشر موسمي', 'verbose_name_plural': 'مؤشرات موسمية'},
        ),
        migrations.AlterUniqueTogether(name='seasonalityindex', unique_together={('item', 'category', 'month')}),

        # ── ForecastRun ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ForecastRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('started_at',      models.DateTimeField(auto_now_add=True, verbose_name='وقت البدء')),
                ('completed_at',    models.DateTimeField(blank=True, null=True, verbose_name='وقت الإكمال')),
                ('status', models.CharField(
                    choices=[('running','جارٍ'),('completed','مكتمل'),('failed','فشل')],
                    db_index=True, default='running', max_length=15,
                )),
                ('items_processed', models.PositiveIntegerField(default=0, verbose_name='أصناف معالَجة')),
                ('parameters',      models.JSONField(default=dict, verbose_name='معاملات التشغيل')),
                ('error',           models.TextField(blank=True, verbose_name='رسالة الخطأ')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='forecast_runs', to='users.staffprofile', verbose_name='أطلقه')),
            ],
            options={'ordering': ['-started_at'], 'verbose_name': 'تشغيل التنبؤ', 'verbose_name_plural': 'تشغيلات التنبؤ'},
        ),

        # ── ForecastAccuracy ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='ForecastAccuracy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('forecast_date', models.DateField(db_index=True, verbose_name='تاريخ التنبؤ')),
                ('forecast_30d',  models.DecimalField(decimal_places=2, max_digits=12, verbose_name='تنبؤ 30 يوم')),
                ('actual_30d',    models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='فعلي 30 يوم')),
                ('mape',          models.DecimalField(blank=True, decimal_places=4, max_digits=7, null=True, verbose_name='MAPE')),
                ('mae',           models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='MAE')),
                ('item',   models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecast_accuracy', to='catalog.item',     verbose_name='الصنف')),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecast_accuracy', to='branches.branch',  verbose_name='الفرع')),
            ],
            options={'ordering': ['-forecast_date'], 'verbose_name': 'دقة التنبؤ', 'verbose_name_plural': 'دقة التنبؤات'},
        ),
        migrations.AlterUniqueTogether(name='forecastaccuracy', unique_together={('item', 'branch', 'forecast_date')}),
        migrations.AddIndex(model_name='forecastaccuracy', index=models.Index(fields=['forecast_date', 'branch'], name='fcast_acc_date_branch_idx')),
    ]
