"""
Migration 0006 — Near Expiry Incentive Extension

Changes:
  IncentiveRule:
    + is_imported_filter  CharField  ('any' | 'local' | 'imported')
    + origin_codes        JSONField  list of origin_code strings to include (empty = all)
    + margin_min          DecimalField null  minimum margin %
    + margin_max          DecimalField null  maximum margin %
    + pack_price_min      DecimalField null  minimum pack price
    + pack_price_max      DecimalField null  maximum pack price

  IncentiveTransaction:
    + expiry_date          DateField null  batch expiry date from stktrans.itemexpirydate
    + expiry_days_remaining IntegerField null  days remaining at sale date

  NOTE: IncentiveRule.expiry_within_days already existed from migration 0001.
        This migration wires it into the engine (no schema change for that field).
"""
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('incentives', '0005_alter_incentiverule_options_and_more'),
    ]

    operations = [
        # ── IncentiveRule: origin filter ──────────────────────────────────────
        migrations.AddField(
            model_name='incentiverule',
            name='is_imported_filter',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('any',      'الكل (محلي + مستورد)'),
                    ('local',    'محلي فقط'),
                    ('imported', 'مستورد فقط'),
                ],
                default='any',
                verbose_name='فلتر المصدر (محلي / مستورد)',
                help_text='any = لا فلترة | local = محلي فقط | imported = مستورد فقط',
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='origin_codes',
            field=models.JSONField(
                null=True, blank=True,
                verbose_name='كودات المصدر',
                help_text=(
                    'قائمة كودات الدولة المسموح بها (itemsorigin.itemorigincode). '
                    'فارغ = جميع المصادر. '
                    'مثال: ["1", "2", "5"] للمنشأ المصري + الألماني + الهندي.'
                ),
            ),
        ),
        # ── IncentiveRule: margin filter ──────────────────────────────────────
        migrations.AddField(
            model_name='incentiverule',
            name='margin_min',
            field=models.DecimalField(
                max_digits=7, decimal_places=3,
                null=True, blank=True,
                verbose_name='الحد الأدنى لهامش الربح %',
                help_text='مثال: 15 = لا تُطبَّق إلا على أصناف هامشها >= 15%',
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='margin_max',
            field=models.DecimalField(
                max_digits=7, decimal_places=3,
                null=True, blank=True,
                verbose_name='الحد الأقصى لهامش الربح %',
                help_text='مثال: 40 = لا تُطبَّق إلا على أصناف هامشها <= 40%',
            ),
        ),
        # ── IncentiveRule: pack price filter ─────────────────────────────────
        migrations.AddField(
            model_name='incentiverule',
            name='pack_price_min',
            field=models.DecimalField(
                max_digits=10, decimal_places=3,
                null=True, blank=True,
                verbose_name='الحد الأدنى لسعر العبوة',
                help_text='مثال: 50 = لا تُطبَّق إلا على أصناف سعرها >= 50 جنيه',
            ),
        ),
        migrations.AddField(
            model_name='incentiverule',
            name='pack_price_max',
            field=models.DecimalField(
                max_digits=10, decimal_places=3,
                null=True, blank=True,
                verbose_name='الحد الأقصى لسعر العبوة',
                help_text='مثال: 500 = لا تُطبَّق إلا على أصناف سعرها <= 500 جنيه',
            ),
        ),
        # ── IncentiveTransaction: expiry audit fields ─────────────────────────
        migrations.AddField(
            model_name='incentivetransaction',
            name='expiry_date',
            field=models.DateField(
                null=True, blank=True, db_index=True,
                verbose_name='تاريخ انتهاء الصلاحية',
                help_text='من stktrans.itemexpirydate — تاريخ انتهاء صلاحية الدُفعة المُباعة',
            ),
        ),
        migrations.AddField(
            model_name='incentivetransaction',
            name='expiry_days_remaining',
            field=models.IntegerField(
                null=True, blank=True,
                verbose_name='أيام الصلاحية المتبقية',
                help_text='عدد الأيام المتبقية على انتهاء الصلاحية في تاريخ البيع (سالب = منتهي الصلاحية)',
            ),
        ),
        # ── Index for expiry-based report queries ─────────────────────────────
        migrations.AddIndex(
            model_name='incentivetransaction',
            index=models.Index(
                fields=['program', 'expiry_date'],
                name='incentive_prog_expiry_idx',
            ),
        ),
    ]
