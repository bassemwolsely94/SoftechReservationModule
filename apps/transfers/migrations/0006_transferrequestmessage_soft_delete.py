from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0005_transferrequestmessage_voice_attachment'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrequestmessage',
            name='is_deleted',
            field=models.BooleanField(default=False, verbose_name='محذوف'),
        ),
        migrations.AddField(
            model_name='transferrequestmessage',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت الحذف'),
        ),
        migrations.AddField(
            model_name='transferrequestmessage',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='deleted_transfer_messages',
                to='users.staffprofile',
                verbose_name='حُذف بواسطة',
            ),
        ),
    ]
