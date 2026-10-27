# Adds is_pinned, pinned_by, pinned_at to FollowUpTask.
# Pinned (or assigned) tasks are the ONLY ones that generate notifications.
# Auto-generated tasks start un-pinned so the notification system is not flooded.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('followups', '0009_followuptask_local_customer_phcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='is_pinned',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='مثبت من قِبَل موظف — يفعّل الإشعارات لهذه المهمة',
                verbose_name='مثبتة / متابعة يدوية',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='pinned_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pinned_followup_tasks',
                to='users.staffprofile',
                verbose_name='ثبّتها',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='pinned_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت التثبيت'),
        ),
    ]
