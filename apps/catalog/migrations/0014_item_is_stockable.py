from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0013_alter_item_effect_code_alter_item_effect_code2_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='is_stockable',
            field=models.BooleanField(
                default=True,
                db_index=True,
                verbose_name='قابل للتخزين (Stockable)',
                help_text=(
                    'Synced from SOFTECH items.itemtrans. '
                    '1 = stockable (included in demand calculations). '
                    '0 = non-stockable (excluded from all demand, purchasing, and inventory calculations). '
                    'Only 38 items are non-stockable out of ~37,500.'
                ),
            ),
        ),
    ]
