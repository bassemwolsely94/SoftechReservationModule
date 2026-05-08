import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_alter_item_unit_price_alter_item_unit_sale_price'),
    ]

    operations = [
        # Add phcode field to Item
        migrations.AddField(
            model_name='item',
            name='phcode',
            field=models.CharField(blank=True, db_index=True, max_length=20),
        ),

        # Create ChronicMedication model
        migrations.CreateModel(
            name='ChronicMedication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category_label', models.CharField(
                    blank=True,
                    help_text='مثل: ضغط الدم، السكر، الغدة الدرقية ...',
                    max_length=100,
                    verbose_name='تصنيف المرض المزمن',
                )),
                ('is_active', models.BooleanField(default=True)),
                ('tagged_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('item', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chronic_tag',
                    to='catalog.item',
                    verbose_name='الصنف',
                )),
            ],
            options={
                'verbose_name': 'دواء مزمن',
                'verbose_name_plural': 'الأدوية المزمنة',
                'ordering': ['item__name'],
            },
        ),
    ]
