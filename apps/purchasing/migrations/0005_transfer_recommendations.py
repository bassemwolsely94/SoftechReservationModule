"""
0005 — Module 2: Inter-Branch Transfer Recommendations.

Changes:
  • New table: purchasing_transferrecommendationrun
  • New table: purchasing_transferrecommendation
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0004_engine_config_and_params_snapshot'),
        ('catalog',  '__first__'),
        ('branches', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── TransferRecommendationRun ─────────────────────────────────────────
        migrations.CreateModel(
            name='TransferRecommendationRun',
            fields=[
                ('id',           models.AutoField(primary_key=True, serialize=False)),
                ('started_at',   models.DateTimeField(auto_now_add=True)),
                ('finished_at',  models.DateTimeField(blank=True, null=True)),
                ('status',       models.CharField(
                    max_length=10,
                    choices=[
                        ('pending', 'انتظار'), ('running', 'جارٍ'),
                        ('success', 'نجح'),    ('failed',  'فشل'),
                    ],
                    default='pending',
                )),
                ('error_message',          models.TextField(blank=True)),
                ('total_recommendations',  models.PositiveIntegerField(default=0)),
                ('total_items_covered',    models.PositiveIntegerField(default=0)),
                ('total_transfer_value',   models.DecimalField(
                    max_digits=18, decimal_places=2, default=0,
                )),
                ('demand_run', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transfer_rec_run',
                    to='purchasing.demandcalculationrun',
                    verbose_name='تشغيل محرك الطلب',
                )),
            ],
            options={
                'verbose_name':        'تشغيل محرك التحويلات',
                'verbose_name_plural': 'تشغيلات محرك التحويلات',
                'ordering': ['-started_at'],
            },
        ),

        # ── TransferRecommendation ────────────────────────────────────────────
        migrations.CreateModel(
            name='TransferRecommendation',
            fields=[
                ('id',         models.AutoField(primary_key=True, serialize=False)),
                ('quantity',   models.DecimalField(
                    max_digits=14, decimal_places=3,
                    verbose_name='الكمية المقترحة للتحويل',
                )),
                ('pack_price', models.DecimalField(
                    max_digits=10, decimal_places=3, default=0,
                    verbose_name='سعر الوحدة (ج.م)',
                )),
                ('estimated_value', models.DecimalField(
                    max_digits=18, decimal_places=2, default=0,
                    verbose_name='القيمة التقديرية',
                )),
                ('priority_score', models.FloatField(
                    default=0, verbose_name='درجة الأولوية',
                )),
                ('from_stock',   models.DecimalField(max_digits=14, decimal_places=3, default=0)),
                ('from_safety',  models.DecimalField(max_digits=10, decimal_places=2, default=0)),
                ('from_surplus', models.DecimalField(max_digits=14, decimal_places=3, default=0)),
                ('to_gap',      models.DecimalField(max_digits=14, decimal_places=3, default=0)),
                ('to_priority', models.FloatField(default=0)),
                ('abc_class',   models.CharField(
                    max_length=1,
                    choices=[('A','A'), ('B','B'), ('C','C'), ('X','X')],
                    default='X', db_index=True,
                )),
                ('status', models.CharField(
                    max_length=10,
                    choices=[
                        ('pending',  'انتظار مراجعة'),
                        ('approved', 'موافق عليه'),
                        ('rejected', 'مرفوض'),
                        ('executed', 'منفّذ'),
                    ],
                    default='pending', db_index=True,
                )),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('notes',       models.TextField(blank=True)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),

                # ── FKs ───────────────────────────────────────────────────────
                ('run', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='recommendations',
                    to='purchasing.transferrecommendationrun',
                    db_index=True,
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transfer_recs',
                    to='catalog.item',
                )),
                ('from_branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transfer_recs_out',
                    to='branches.branch',
                )),
                ('to_branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transfer_recs_in',
                    to='branches.branch',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transfer_rec_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name':        'توصية تحويل',
                'verbose_name_plural': 'توصيات التحويل',
                'ordering': ['-priority_score', '-estimated_value'],
            },
        ),

        # ── Constraints & indexes ─────────────────────────────────────────────
        migrations.AddConstraint(
            model_name='transferrecommendation',
            constraint=models.UniqueConstraint(
                fields=['run', 'item', 'from_branch', 'to_branch'],
                name='unique_transfer_rec_per_run',
            ),
        ),
        migrations.AddIndex(
            model_name='transferrecommendation',
            index=models.Index(fields=['run', 'status'],      name='trec_run_status'),
        ),
        migrations.AddIndex(
            model_name='transferrecommendation',
            index=models.Index(fields=['run', 'abc_class'],   name='trec_run_abc'),
        ),
        migrations.AddIndex(
            model_name='transferrecommendation',
            index=models.Index(fields=['run', 'from_branch'], name='trec_run_from'),
        ),
        migrations.AddIndex(
            model_name='transferrecommendation',
            index=models.Index(fields=['run', 'to_branch'],   name='trec_run_to'),
        ),
        migrations.AddIndex(
            model_name='transferrecommendation',
            index=models.Index(fields=['run', 'item'],        name='trec_run_item'),
        ),
    ]
