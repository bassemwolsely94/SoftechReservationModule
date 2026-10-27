from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0026_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushsubscription',
            name='failure_count',
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name='عدد الإخفاقات المتتالية',
            ),
        ),
    ]
