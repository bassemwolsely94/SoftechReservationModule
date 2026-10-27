"""
apps/catalog/migrations/0012_item_enrichment_fields.py

Add item enrichment fields synced from new SOFTECH lookup tables:
  - shape_code/name/name_ar    ← itemshape   (dosage form)
  - origin_code/name/name_ar   ← itemsorigin (country of origin)
  - is_imported                ← itemsorigin.importedorigin
  - effect_code/name/name_ar   ← itemseffect (primary indication)
  - effect_code2/name2/name2_ar← itemseffect2 (secondary indication)
  - unit_code/unit_name        ← itemsunits  (pack sub-unit type)
  - active_ingredients         ← itemsai + activeingredients (comma-sep)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0011_alter_item_producer_code_alter_item_producer_name'),
    ]

    operations = [
        # Dosage form (itemshape)
        migrations.AddField(
            model_name='item', name='shape_code',
            field=models.CharField(blank=True, max_length=5, default='',
                                   help_text='items.itemshapecode → itemshape.itemshapecode'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='shape_name',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='shape_name_ar',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        # Country of origin (itemsorigin)
        migrations.AddField(
            model_name='item', name='origin_code',
            field=models.CharField(blank=True, max_length=5, default='',
                                   help_text='items.itemorigincode → itemsorigin.itemorigincode'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='origin_name',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='origin_name_ar',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='is_imported',
            field=models.BooleanField(default=False,
                                      help_text='itemsorigin.importedorigin — True = imported product'),
        ),
        # Primary therapeutic indication (itemseffect)
        migrations.AddField(
            model_name='item', name='effect_code',
            field=models.CharField(blank=True, max_length=5, default='',
                                   help_text='items.itemeffectcode → itemseffect.itemeffectcode'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='effect_name',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='effect_name_ar',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        # Secondary therapeutic indication (itemseffect2)
        migrations.AddField(
            model_name='item', name='effect_code2',
            field=models.CharField(blank=True, max_length=5, default='',
                                   help_text='items.itemeffectcode2 → itemseffect2.itemeffectcode2'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='effect_name2',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='effect_name2_ar',
            field=models.CharField(blank=True, max_length=100, default=''),
            preserve_default=False,
        ),
        # Pack sub-unit type (itemsunits)
        migrations.AddField(
            model_name='item', name='unit_code',
            field=models.CharField(blank=True, max_length=3, default='',
                                   help_text='items.unitcode → itemsunits.unitcode'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='item', name='unit_name',
            field=models.CharField(blank=True, max_length=50, default=''),
            preserve_default=False,
        ),
        # Active ingredients (itemsai → activeingredients)
        migrations.AddField(
            model_name='item', name='active_ingredients',
            field=models.TextField(
                blank=True, default='',
                verbose_name='المواد الفعالة',
                help_text='itemsai → activeingredients.ainame — comma-separated active ingredient names',
            ),
            preserve_default=False,
        ),
    ]
