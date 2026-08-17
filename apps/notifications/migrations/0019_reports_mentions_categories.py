# Split periodic digests into a quiet 'reports' feed and @-mentions into a
# 'mentions' feed; churn_alert stays in the bell (now a HIGH alarm, no recat).

from django.db import migrations, models


def backfill(apps, schema_editor):
    Notification = apps.get_model('notifications', 'Notification')
    Notification.objects.filter(
        notification_type__in=['weekly_summary', 'monthly_report']
    ).exclude(category='reports').update(category='reports')
    Notification.objects.filter(
        notification_type__in=['mention', 'chatter_mention']
    ).exclude(category='mentions').update(category='mentions')


def reverse(apps, schema_editor):
    Notification = apps.get_model('notifications', 'Notification')
    Notification.objects.filter(category__in=['reports', 'mentions']).update(category='global')


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0018_notification_priority_tiers'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='category',
            field=models.CharField(choices=[('global', 'عام'), ('demand', 'الطلب الضائع'), ('followups', 'المتابعات'), ('delivery', 'التوصيل'), ('transfers', 'التحويلات'), ('reservations', 'الحجوزات'), ('monitoring', 'المراقبة'), ('settings', 'النظام والإعدادات'), ('reports', 'التقارير الدورية'), ('mentions', 'الإشارات')], db_index=True, default='global', max_length=20, verbose_name='التصنيف'),
        ),
        migrations.RunPython(backfill, reverse),
    ]
