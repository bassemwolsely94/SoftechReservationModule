"""
Migration 0015 — Add 9 SOFTECH-sourced operational/channel fields to catalog.Item.

New fields:
  is_fast_moving   — items.fmi (Fast Moving Item flag)
  insurance_type   — items.hi_typecode (0=none,1=Talbia,2=TPA,3=Takaful,4=Other)
  is_premium       — items.itemslevel (0=standard, 1=premium)
  has_points       — items.itempointsys (points program eligibility)
  pack_qty         — items.packqty (units per pack)
  branch_trans     — items.itemtrans1 (branch transfer permissions)
  supplier_trans   — items.itemtrans2 (supplier purchase permissions)
  customer_trans   — items.itemtrans3 (customer sale permissions)
  nosale_classif   — items.itemnosaleclassif (contract/dispensing restriction)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0014_item_is_stockable'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='is_fast_moving',
            field=models.BooleanField(
                default=False, db_index=True,
                verbose_name='سريع التداول (FMI)',
                help_text='SOFTECH items.fmi. Fast Moving Item flag.',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='insurance_type',
            field=models.CharField(
                max_length=1, blank=True, db_index=True,
                verbose_name='نوع التأمين الصحي',
                help_text=(
                    'SOFTECH items.hi_typecode. '
                    '0=not covered, 1=Talbia, 2=TPA, 3=Takaful, 4=Other.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='is_premium',
            field=models.BooleanField(
                default=False,
                verbose_name='صنف متميز (Premium)',
                help_text='SOFTECH items.itemslevel. Original mapping — see migration 0016 for correction.',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='has_points',
            field=models.BooleanField(
                default=False,
                verbose_name='مؤهل لنظام النقاط',
                help_text='SOFTECH items.itempointsys. 1 = points eligible.',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='pack_qty',
            field=models.PositiveSmallIntegerField(
                default=1,
                verbose_name='كمية العبوة',
                help_text='SOFTECH items.packqty — units per pack.',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='branch_trans',
            field=models.CharField(
                max_length=1, blank=True,
                verbose_name='صلاحية — الفروع',
                help_text=(
                    'SOFTECH items.itemtrans1. '
                    '0=صرف+ارتجاع, 1=صرف فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='supplier_trans',
            field=models.CharField(
                max_length=1, blank=True,
                verbose_name='صلاحية — الموردين',
                help_text=(
                    'SOFTECH items.itemtrans2. '
                    '0=شراء+ارتجاع, 1=شراء فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='customer_trans',
            field=models.CharField(
                max_length=1, blank=True,
                verbose_name='صلاحية — العملاء',
                help_text=(
                    'SOFTECH items.itemtrans3. '
                    '0=بيع+ارتجاع, 1=بيع فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='nosale_classif',
            field=models.CharField(
                max_length=5, blank=True,
                verbose_name='تصنيف منع الصرف',
                help_text=(
                    'SOFTECH items.itemnosaleclassif. '
                    '10=normal, 20=#2, 30=#3, 31=#4.'
                ),
            ),
        ),
    ]
