from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0020_alter_productbundle_discount_value'),
    ]

    operations = [
        migrations.CreateModel(
            name='ItemBarcode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('barcode', models.CharField(db_index=True, max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='barcodes',
                    to='catalog.item',
                )),
            ],
            options={
                'verbose_name': 'باركود إضافي',
                'verbose_name_plural': 'باركودات الأصناف',
                'unique_together': {('item', 'barcode')},
            },
        ),
    ]
