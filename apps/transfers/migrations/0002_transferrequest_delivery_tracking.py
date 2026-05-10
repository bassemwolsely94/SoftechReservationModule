import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0001_initial'),
        ('users', '0005_alter_staffprofile_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrequest',
            name='delivery_person_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='اسم مندوب التوصيل'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='dispatched_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت الإرسال'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='dispatched_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='dispatched_transfers',
                to='users.staffprofile',
                verbose_name='أُرسل بواسطة',
            ),
        ),
    ]
