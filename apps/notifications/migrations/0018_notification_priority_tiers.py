# Priority-tier notification redesign: add 'monitoring' + 'settings' categories,
# move high-frequency SLA/transit/routine-status + system/connectivity rows out of
# the alarming bell into their quiet feeds.

from django.db import migrations, models


_MONITORING_TYPES = [
    'reservation_status', 'call_logged', 'follow_up_due',
    'delivery_status', 'delivery_sla_alert', 'delivery_csat',
    'transit_issued', 'transit_approaching_cancel', 'transit_overdue',
    'transit_critical', 'transit_received', 'transit_cancelled',
]
_SETTINGS_TYPES = ['system', 'branch_connectivity']


def backfill(apps, schema_editor):
    Notification = apps.get_model('notifications', 'Notification')
    Notification.objects.filter(notification_type__in=_MONITORING_TYPES).exclude(
        category='monitoring').update(category='monitoring')
    Notification.objects.filter(notification_type__in=_SETTINGS_TYPES).exclude(
        category='settings').update(category='settings')


def reverse(apps, schema_editor):
    Notification = apps.get_model('notifications', 'Notification')
    # Best-effort: route monitoring rows back to their old module category.
    Notification.objects.filter(
        category='monitoring',
        notification_type__in=['reservation_status', 'call_logged', 'follow_up_due'],
    ).update(category='reservations')
    Notification.objects.filter(
        category='monitoring',
        notification_type__in=['delivery_status', 'delivery_sla_alert', 'delivery_csat'],
    ).update(category='delivery')
    Notification.objects.filter(category='monitoring').update(category='transfers')
    Notification.objects.filter(category='settings').update(category='global')


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0017_alter_notification_category'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='category',
            field=models.CharField(choices=[('global', 'عام'), ('demand', 'الطلب الضائع'), ('followups', 'المتابعات'), ('delivery', 'التوصيل'), ('transfers', 'التحويلات'), ('reservations', 'الحجوزات'), ('monitoring', 'المراقبة'), ('settings', 'النظام والإعدادات')], db_index=True, default='global', max_length=20, verbose_name='التصنيف'),
        ),
        migrations.RunPython(backfill, reverse),
    ]
