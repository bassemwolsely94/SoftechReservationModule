from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0019_in_transit_qty'),
    ]

    operations = [
        migrations.AddField(
            model_name='engineconfig',
            name='in_transit_max_age_days',
            field=models.PositiveSmallIntegerField(
                default=14,
                verbose_name='أقصى عمر للبضاعة بالطريق (أيام)',
                help_text='Only transfers issued within N days count as in-transit. '
                          'Older = stale/unreconciled → excluded. Default 14. 0 = no limit.',
            ),
        ),
    ]
