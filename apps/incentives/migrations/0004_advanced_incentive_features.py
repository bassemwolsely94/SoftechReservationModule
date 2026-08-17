"""
Migration 0004 — Advanced incentive features

Adds:
  • IncentiveRule: slab_config, min_total_qty_in_period, branch_filter,
                   time_window_start, time_window_end
                   (incentive_type choices expanded — no DB change needed for CharField)
  • IncentiveTransaction: is_cross_period_return
                          renames old indexes to avoid conflicts
  • IncentiveSettlement: total_adjustments, final_payout
  • New model: AdjustmentEntry
  • New model: IncentiveCalculationLog
"""
from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('incentives', '0003_incentive_rule_item'),
        ('users', '0010_erpuser_user_group'),
    ]

    operations = [

        # ── IncentiveRule: new fields ─────────────────────────────────────────
        migrations.AddField(
            model_name='incentiverule',
            name='slab_config',
            field=models.JSONField(
                blank=True, null=True,
                verbose_name='إعداد السلاب (للنوع المتدرج)',
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='min_total_qty_in_period',
            field=models.DecimalField(
                blank=True, null=True,
                max_digits=10, decimal_places=3,
                verbose_name='الحد الأدنى لإجمالي الكمية في الفترة',
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='branch_filter',
            field=models.CharField(
                blank=True, max_length=50,
                verbose_name='فلتر الفرع (branchcode)',
                default='',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='time_window_start',
            field=models.TimeField(blank=True, null=True, verbose_name='بداية النافذة الزمنية'),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='time_window_end',
            field=models.TimeField(blank=True, null=True, verbose_name='نهاية النافذة الزمنية'),
        ),
        # Alter incentive_type choices (no DB change — CharField stores raw value)
        migrations.AlterField(
            model_name='incentiverule',
            name='incentive_type',
            field=models.CharField(
                choices=[
                    ('percent',               'نسبة مئوية % من صافي البيع'),
                    ('fixed',                 'مبلغ ثابت / وحدة (قديم)'),
                    ('fixed_per_unit',        'مبلغ ثابت / وحدة'),
                    ('fixed_per_transaction', 'مبلغ ثابت / فاتورة'),
                    ('tiered',                'متدرج (سلاب)'),
                ],
                default='percent',
                max_length=25,
                verbose_name='نوع الحافز',
            ),
        ),
        # Alter priority direction note — no DB change needed (field already exists)

        # ── IncentiveTransaction: new field ───────────────────────────────────
        migrations.AddField(
            model_name='incentivetransaction',
            name='is_cross_period_return',
            field=models.BooleanField(
                default=False,
                verbose_name='مرتجع من فترة مختلفة',
            ),
        ),

        # ── IncentiveSettlement: new fields ───────────────────────────────────
        migrations.AddField(
            model_name='incentivesettlement',
            name='total_adjustments',
            field=models.DecimalField(
                default=Decimal('0'), max_digits=14, decimal_places=4,
                verbose_name='إجمالي التسويات اليدوية',
            ),
        ),
        migrations.AddField(
            model_name='incentivesettlement',
            name='final_payout',
            field=models.DecimalField(
                default=Decimal('0'), max_digits=14, decimal_places=4,
                verbose_name='الصافي النهائي للصرف',
            ),
        ),

        # ── AdjustmentEntry ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='AdjustmentEntry',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('period_start', models.DateField(verbose_name='بداية الفترة')),
                ('period_end',   models.DateField(verbose_name='نهاية الفترة')),
                ('amount',       models.DecimalField(
                    max_digits=12, decimal_places=4,
                    verbose_name='المبلغ (+ مكافأة / - خصم)',
                )),
                ('reason',       models.TextField(verbose_name='سبب التسوية')),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
                ('program', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='adjustments',
                    to='incentives.incentiveprogram',
                    verbose_name='البرنامج',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='incentive_adjustments',
                    to='users.staffprofile',
                    verbose_name='المندوب',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_adjustments',
                    to='users.staffprofile',
                    verbose_name='أُنشئ بواسطة',
                )),
            ],
            options={
                'verbose_name':        'تسوية يدوية',
                'verbose_name_plural': 'التسويات اليدوية',
                'ordering':            ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='adjustmententry',
            index=models.Index(
                fields=['program', 'user', 'period_start'],
                name='adj_prog_user_period_idx',
            ),
        ),

        # ── IncentiveCalculationLog ───────────────────────────────────────────
        migrations.CreateModel(
            name='IncentiveCalculationLog',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('period_start',          models.DateField(verbose_name='بداية الفترة')),
                ('period_end',            models.DateField(verbose_name='نهاية الفترة')),
                ('mode',                  models.CharField(
                    choices=[('calculate', 'احتساب فعلي'), ('simulate', 'محاكاة')],
                    default='calculate', max_length=12, verbose_name='النوع',
                )),
                ('status',                models.CharField(
                    choices=[('done', 'مكتمل'), ('failed', 'فشل')],
                    default='done', max_length=10, verbose_name='الحالة',
                )),
                ('transactions_created',  models.IntegerField(default=0)),
                ('skipped_person_codes',  models.JSONField(default=list)),
                ('user_summaries',        models.JSONField(default=dict)),
                ('error_detail',          models.TextField(blank=True)),
                ('started_at',            models.DateTimeField(auto_now_add=True)),
                ('finished_at',           models.DateTimeField(blank=True, null=True)),
                ('duration_seconds',      models.FloatField(blank=True, null=True)),
                ('program', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='calculation_logs',
                    to='incentives.incentiveprogram',
                    verbose_name='البرنامج',
                )),
                ('triggered_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='triggered_calculations',
                    to='users.staffprofile',
                    verbose_name='شُغِّل بواسطة',
                )),
            ],
            options={
                'verbose_name':        'سجل احتساب',
                'verbose_name_plural': 'سجلات الاحتساب',
                'ordering':            ['-started_at'],
            },
        ),
        migrations.AddIndex(
            model_name='incentivecalculationlog',
            index=models.Index(
                fields=['program', 'period_start'],
                name='calclog_prog_period_idx',
            ),
        ),
    ]
