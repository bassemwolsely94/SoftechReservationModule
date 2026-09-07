from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_item_family_name_ar'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='cost_price',
            field=models.DecimalField(
                decimal_places=3, default=0, max_digits=10,
                verbose_name='سعر الشراء',
            ),
        ),
    ]
