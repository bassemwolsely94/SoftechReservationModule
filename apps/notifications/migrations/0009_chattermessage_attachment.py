from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0008_fix_notification_message_column'),
    ]

    operations = [
        migrations.AddField(
            model_name='chattermessage',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='chatter/%Y/%m/', verbose_name='مرفق'),
        ),
        migrations.AddField(
            model_name='chattermessage',
            name='file_type',
            field=models.CharField(
                blank=True,
                choices=[('image', 'صورة'), ('voice', 'صوت'), ('doc', 'مستند')],
                max_length=10,
                verbose_name='نوع المرفق',
            ),
        ),
        migrations.AddField(
            model_name='chattermessage',
            name='is_internal',
            field=models.BooleanField(
                default=True,
                help_text='إذا كان False فهو مرئي للعميل أيضاً',
                verbose_name='داخلي فقط',
            ),
        ),
    ]
