"""
Migration 0020 — Align channel field with Softech ERP POS types.

Changes:
  - channel: replaces old choices (pickup/home_delivery/insurance/inquiry)
             with Softech-aligned POS types (cash_sales/home_delivery/contract_sales)
             max_length stays at 20 (longest new value: 'contract_sales' = 13 chars)
  - contract_subtype: new CharField(max_length=30, blank=True)
             stores Softech نوع العميل when channel=contract_sales

Data migration (old → new):
  pickup        → cash_sales
  home_delivery → home_delivery  (unchanged)
  insurance     → contract_sales  + contract_subtype = health_insurance
  inquiry       → cash_sales
"""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Reservation = apps.get_model('reservations', 'Reservation')
    MAP = {
        'pickup':        ('cash_sales',     ''),
        'home_delivery': ('home_delivery',  ''),
        'insurance':     ('contract_sales', 'health_insurance'),
        'inquiry':       ('cash_sales',     ''),
    }
    for old_channel, (new_channel, subtype) in MAP.items():
        Reservation.objects.filter(channel=old_channel).update(
            channel=new_channel,
            contract_subtype=subtype,
        )


def backwards(apps, schema_editor):
    Reservation = apps.get_model('reservations', 'Reservation')
    # Best-effort reverse
    Reservation.objects.filter(channel='cash_sales').update(channel='pickup', contract_subtype='')
    Reservation.objects.filter(
        channel='contract_sales', contract_subtype='health_insurance'
    ).update(channel='insurance', contract_subtype='')
    Reservation.objects.filter(channel='contract_sales').update(channel='pickup', contract_subtype='')


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0019_reservationline'),
    ]

    operations = [
        # Add the new contract_subtype field first (so data migration can write to it)
        migrations.AddField(
            model_name='reservation',
            name='contract_subtype',
            field=models.CharField(
                max_length=30,
                blank=True,
                default='',
                verbose_name='نوع العميل / قناة الكنتراكت',
                help_text='يُملأ فقط عند اختيار بيع بالكنتراكت',
            ),
            preserve_default=False,
        ),

        # Run the data migration while old channel values still exist
        migrations.RunPython(forwards, backwards),

        # Now swap the channel field choices (no structural DB change needed — CharField)
        migrations.AlterField(
            model_name='reservation',
            name='channel',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('cash_sales',     'بيع نقدي / كاش (F2)'),
                    ('home_delivery',  'توصيل للمنزل (F3)'),
                    ('contract_sales', 'بيع بالكنتراكت (F4)'),
                ],
                default='cash_sales',
                verbose_name='قناة الطلب (نوع POS)',
            ),
        ),
    ]
