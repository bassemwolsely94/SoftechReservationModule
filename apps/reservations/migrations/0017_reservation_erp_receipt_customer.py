from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0016_reservation_erp_match_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='erp_receipt_lines',
            field=models.JSONField(blank=True, default=list, verbose_name='أصناف الإيصال الكاملة'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_customer_info',
            field=models.JSONField(blank=True, default=dict, verbose_name='بيانات العميل (ERP)'),
        ),
    ]
