"""
Migration: users 0008
  Add notification-preference fields to StaffProfile:
    enable_notifications  (default True)
    enable_sound          (default True)
    enable_browser_push   (default False)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_erpuser_user_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffprofile',
            name='enable_notifications',
            field=models.BooleanField(default=True, verbose_name='تفعيل الإشعارات'),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='enable_sound',
            field=models.BooleanField(default=True, verbose_name='تفعيل الصوت'),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='enable_browser_push',
            field=models.BooleanField(default=False, verbose_name='إشعارات المتصفح'),
        ),
    ]
