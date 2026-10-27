"""
0010_reservation_manual_item

• Make Reservation.item nullable so reservations can be created for items
  not yet registered in the system.
• Add manual_item_name CharField for staff to record the item name in text
  when no catalog entry exists yet.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
        ('reservations', '0009_fix_legacy_notnull_columns'),
    ]

    operations = [
        # Make item FK nullable
        migrations.AlterField(
            model_name='reservation',
            name='item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='reservations',
                to='catalog.item',
            ),
        ),
        # Add free-text fallback
        migrations.AddField(
            model_name='reservation',
            name='manual_item_name',
            field=models.CharField(
                blank=True,
                default='',
                max_length=500,
                help_text='اسم صنف غير مكوَّد — يُستخدم عند عدم وجود الصنف في قاعدة البيانات',
            ),
            preserve_default=False,
        ),
    ]
