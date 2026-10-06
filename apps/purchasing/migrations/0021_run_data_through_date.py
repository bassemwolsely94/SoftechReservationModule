from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0020_engineconfig_in_transit_max_age'),
    ]

    operations = [
        migrations.AddField(
            model_name='demandcalculationrun',
            name='data_through_date',
            field=models.DateField(
                null=True, blank=True, db_index=True,
                verbose_name='المبيعات حتى تاريخ',
            ),
        ),
    ]
