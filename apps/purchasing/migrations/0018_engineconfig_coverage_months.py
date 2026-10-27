from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0017_restore_forecast_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='engineconfig',
            name='coverage_months_a',
            field=models.FloatField(
                default=1.0,
                help_text='Months of consumption to stock for A-class items. Default 1.0.',
                verbose_name='أشهر التغطية — فئة A',
            ),
        ),
        migrations.AddField(
            model_name='engineconfig',
            name='coverage_months_b',
            field=models.FloatField(
                default=1.0,
                help_text='Months of consumption to stock for B-class items. Default 1.0.',
                verbose_name='أشهر التغطية — فئة B',
            ),
        ),
        migrations.AddField(
            model_name='engineconfig',
            name='coverage_months_c',
            field=models.FloatField(
                default=1.0,
                help_text='Months of consumption to stock for C-class items. Default 1.0.',
                verbose_name='أشهر التغطية — فئة C',
            ),
        ),
    ]
