from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0013_alter_reservationactivity_voice_note'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservationactivity',
            name='is_deleted',
            field=models.BooleanField(default=False, verbose_name='محذوف'),
        ),
        migrations.AddField(
            model_name='reservationactivity',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت الحذف'),
        ),
        migrations.AddField(
            model_name='reservationactivity',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='deleted_reservation_activities',
                to='users.staffprofile',
                verbose_name='حُذف بواسطة',
            ),
        ),
    ]
