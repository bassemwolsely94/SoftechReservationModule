# Generated manually — adds sales_channel field to FollowUpTask

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('followups', '0007_alter_followuptask_reminder_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='sales_channel',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='softech_ptclassifcode: 91=كاش, 90=توصيل, 13=عميل دائم, 15=تأمين',
                max_length=10,
                verbose_name='قناة البيع',
            ),
        ),
    ]
