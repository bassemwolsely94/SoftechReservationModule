from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0010_reservation_manual_item'),
        ('reservations', '0007_reservation_channel'),   # merge the placeholder branch
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='channel',
            field=models.CharField(
                choices=[
                    ('pickup',        'استلام من الفرع'),
                    ('home_delivery', 'توصيل للمنزل'),
                    ('insurance',     'تأمين'),
                    ('inquiry',       'استفسار'),
                ],
                default='pickup',
                max_length=20,
                verbose_name='قناة الطلب',
            ),
        ),
    ]
