"""
Migration: notifications 0006
Add 'call_logged' to Notification.notification_type choices.
(AlterField only — no schema change, just updates Django's in-memory choices.)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0006_remove_notification_notif_recip_read_created_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('stock_available',           '📦 مخزون متاح'),
                    ('reservation_assigned',      '👤 حجز مُعيَّن'),
                    ('reservation_created',       '➕ حجز جديد'),
                    ('reservation_status',        '🔄 تغيير حالة حجز'),
                    ('call_logged',               '📞 تحديث نشاط حجز'),
                    ('follow_up_due',             '📅 متابعة مستحقة اليوم'),
                    ('weekly_summary',            '📊 ملخص أسبوعي'),
                    ('monthly_report',            '📈 تقرير شهري'),
                    ('transfer_request',          '🔀 طلب تحويل جديد'),
                    ('transfer_response',         '↩️ رد على طلب تحويل'),
                    ('unfulfilled_transfer_flag', '⚠️ تحويل غير مُصرَّف'),
                    ('demand_created',            '🆕 طلب جديد'),
                    ('demand_assigned',           '👤 طلب مُعيَّن'),
                    ('demand_status',             '🔄 تغيير حالة طلب'),
                    ('demand_follow_up',          '📅 متابعة طلب'),
                    ('chatter_mention',           '💬 ذِكر في تعليق'),
                    ('mention',                   '@ ذِكر'),
                    ('system',                    '⚙️ نظام'),
                ],
                db_index=True,
                default='system',
                max_length=40,
                verbose_name='نوع الإشعار',
            ),
        ),
    ]
