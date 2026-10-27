"""
Migration 0010 — Add producer_code and producer_name to Item.

SOFTECH itemsproducers table (itemcode → producercode, main_producer='1')
maps each item to its manufacturer/producer.  The producer name is resolved
from personsdata.personname.  Previously only itemssuppliers (supplier) was
stored; this adds the producer as a separate pair of fields.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0009_item_cost_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='producer_code',
            field=models.CharField(
                max_length=8, blank=True, default='',
                verbose_name='كود المنتج/الشركة المصنعة',
                help_text='producercode from SOFTECHDB9.dbo.itemsproducers (main_producer=1)',
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='producer_name',
            field=models.CharField(
                max_length=150, blank=True, default='',
                verbose_name='اسم المنتج/الشركة المصنعة',
                help_text='personsdata.personname resolved via producer_code',
            ),
        ),
    ]
