from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0018_engineconfig_coverage_months'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='in_transit_qty',
            field=models.DecimalField(
                max_digits=14, decimal_places=3, default=0,
                verbose_name='بضاعة في الطريق (لم تُستلم)',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandaggregated',
            name='total_in_transit',
            field=models.DecimalField(
                max_digits=16, decimal_places=3, default=0,
                verbose_name='إجمالي البضاعة بالطريق',
            ),
        ),
    ]
