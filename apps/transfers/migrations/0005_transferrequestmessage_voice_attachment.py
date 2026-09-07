"""
Migration: add voice_note + attachment fields to TransferRequestMessage,
           and make message text optional (blank=True).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0004_fix_request_number_nullable'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transferrequestmessage',
            name='message',
            field=models.TextField(blank=True, verbose_name='الرسالة'),
        ),
        migrations.AddField(
            model_name='transferrequestmessage',
            name='attachment',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='transfer_attachments/%Y/%m/',
                verbose_name='مرفق صورة',
            ),
        ),
        migrations.AddField(
            model_name='transferrequestmessage',
            name='voice_note',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='transfer_voices/%Y/%m/',
                verbose_name='ملاحظة صوتية',
            ),
        ),
    ]
