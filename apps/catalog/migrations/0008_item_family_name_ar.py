from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_item_lookup_name_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='family_name_ar',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
