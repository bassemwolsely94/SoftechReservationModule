"""
0004 — Add EngineConfig singleton model + params_snapshot field on DemandCalculationRun.

Changes:
  • New table: purchasing_engineconfig (singleton pk=1)
  • New column: purchasing_demandcalculationrun.params_snapshot (JSONField, default={})
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0003_performance_indexes'),
    ]

    operations = [
        # ── EngineConfig singleton ────────────────────────────────────────────
        migrations.CreateModel(
            name='EngineConfig',
            fields=[
                ('id',              models.AutoField(primary_key=True, serialize=False)),
                ('weight_30d',      models.FloatField(default=0.5,
                                        verbose_name='وزن معدل 30 يوم',
                                        help_text='Weight for 30-day window (default 0.5)')),
                ('weight_90d',      models.FloatField(default=0.3,
                                        verbose_name='وزن معدل 90 يوم',
                                        help_text='Weight for 90-day window (default 0.3)')),
                ('weight_365d',     models.FloatField(default=0.2,
                                        verbose_name='وزن معدل 365 يوم',
                                        help_text='Weight for 365-day window (default 0.2)')),
                ('abc_a_threshold', models.FloatField(default=70.0,
                                        verbose_name='حد فئة A (%)',
                                        help_text='Cumulative % at which A ends (default 70)')),
                ('abc_b_threshold', models.FloatField(default=90.0,
                                        verbose_name='حد فئة B (%)',
                                        help_text='Cumulative % at which B ends (default 90)')),
                ('updated_at',      models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'إعدادات محرك الطلب',
                'verbose_name_plural': 'إعدادات محرك الطلب',
            },
        ),

        # ── params_snapshot on DemandCalculationRun ───────────────────────────
        migrations.AddField(
            model_name='demandcalculationrun',
            name='params_snapshot',
            field=models.JSONField(
                default=dict, blank=True,
                help_text='Snapshot of EngineConfig params used for this run',
            ),
        ),
    ]
