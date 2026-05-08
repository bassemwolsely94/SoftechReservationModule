from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_remove_notification_notificatio_recipie_684eac_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='demand_id_ref',
            field=models.IntegerField(blank=True, null=True, verbose_name='معرّف طلب الطلب'),
        ),
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('stock_available', '📦 مخزون متاح'),
                    ('reservation_assigned', '👤 حجز مُعيَّن'),
                    ('reservation_created', '➕ حجز جديد'),
                    ('reservation_status', '🔄 تغيير حالة حجز'),
                    ('follow_up_due', '📅 متابعة مستحقة اليوم'),
                    ('weekly_summary', '📊 ملخص أسبوعي'),
                    ('monthly_report', '📈 تقرير شهري'),
                    ('mention', '@ ذِكر'),
                    ('transfer_request', '🔀 طلب تحويل جديد'),
                    ('transfer_response', '↩️ رد على طلب تحويل'),
                    ('unfulfilled_transfer_flag', '⚠️ تحويل غير مُصرَّف'),
                    ('demand_created', '🆕 طلب جديد'),
                    ('demand_assigned', '👤 طلب مُعيَّن'),
                    ('demand_status', '🔄 تغيير حالة طلب'),
                    ('demand_follow_up', '📅 متابعة طلب'),
                    ('system', '⚙️ نظام'),
                ],
                db_index=True,
                default='system',
                max_length=40,
                verbose_name='نوع الإشعار',
            ),
        ),
    ]
