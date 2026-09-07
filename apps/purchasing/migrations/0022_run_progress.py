from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0021_run_data_through_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='demandcalculationrun',
            name='progress',
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.AddField(
            model_name='demandcalculationrun',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
