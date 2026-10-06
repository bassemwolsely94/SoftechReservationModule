"""
Migration 0007 — Incentive Module Features

Changes:

  IncentiveProgram:
    + sponsor_name              CharField  blank
    + sponsor_contribution_pct  Decimal    null   (0–100)

  IncentiveRule:
    + target_qty    Decimal  null   — total target units per employee per period
    + target_tiers  JSON     null   — achievement-tier config for target_based type
    + incentive_type now includes 'target_based'

  No schema change needed for category_code wiring — field already exists.
"""
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('incentives', '0006_near_expiry_incentive'),
    ]

    operations = [
        # ── IncentiveProgram: supplier sponsor fields ──────────────────────────
        migrations.AddField(
            model_name='incentiveprogram',
            name='sponsor_name',
            field=models.CharField(
                max_length=200, blank=True,
                verbose_name='اسم الجهة الراعية',
                help_text='اسم المورد أو الشركة التي تموّل هذا البرنامج جزئياً أو كلياً',
            ),
        ),
        migrations.AddField(
            model_name='incentiveprogram',
            name='sponsor_contribution_pct',
            field=models.DecimalField(
                max_digits=6, decimal_places=3,
                null=True, blank=True,
                verbose_name='نسبة مساهمة الراعي %',
                help_text=(
                    'نسبة تحمّل الراعي من إجمالي الحافز (0–100). '
                    'مثال: 60 = الراعي يتحمّل 60%، الصيدلية 40%.'
                ),
            ),
        ),

        # ── IncentiveRule: target-based fields ───────────────────────────────
        migrations.AddField(
            model_name='incentiverule',
            name='target_qty',
            field=models.DecimalField(
                max_digits=12, decimal_places=3,
                null=True, blank=True,
                verbose_name='الهدف الكمي (وحدات/فترة)',
                help_text=(
                    'الكمية الكاملة المستهدفة (100% إنجاز) لكل مندوب في الفترة. '
                    'مطلوب عند نوع الحافز target_based.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='target_tiers',
            field=models.JSONField(
                null=True, blank=True,
                verbose_name='شرائح الإنجاز (للنوع target_based)',
                help_text=(
                    'مثال: {"tiers": ['
                    '{"min_pct": 80, "max_pct": 99,  "rate": 5.0,  "type": "fixed_per_unit"},'
                    '{"min_pct": 100,"max_pct": 119, "rate": 10.0, "type": "fixed_per_unit"},'
                    '{"min_pct": 120,"max_pct": null,"rate": 15.0, "type": "fixed_per_unit"}'
                    ']}'
                ),
            ),
        ),

        # ── Update incentive_type choices to include target_based ─────────────
        migrations.AlterField(
            model_name='incentiverule',
            name='incentive_type',
            field=models.CharField(
                max_length=25,
                choices=[
                    ('percent',               'نسبة مئوية % من صافي البيع'),
                    ('fixed',                 'مبلغ ثابت / وحدة (قديم)'),
                    ('fixed_per_unit',        'مبلغ ثابت / وحدة'),
                    ('fixed_per_transaction', 'مبلغ ثابت / فاتورة'),
                    ('tiered',                'متدرج (سلاب)'),
                    ('target_based',          'قائم على الهدف (شرائح إنجاز)'),
                ],
                default='percent',
                verbose_name='نوع الحافز',
            ),
        ),
    ]
