from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0024_pushsubscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='chattermessage',
            name='voice_note',
            field=models.FileField(
                blank=True, null=True,
                upload_to='chatter_voices/%Y/%m/',
                help_text='ملاحظة صوتية (WebRTC أو ملف صوتي) — مستقلة عن المرفق',
                verbose_name='ملاحظة صوتية',
            ),
        ),
    ]
