from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0007_transfer_rec_branch_snapshots'),
    ]

    operations = [
        migrations.AddField(
            model_name='engineconfig',
            name='ss_multiplier',
            field=models.FloatField(
                default=1.0,
                help_text=(
                    'Multiplier applied to monthly_avg before the safety-stock tier lookup. '
                    'Default 1.0 = exact Excel behaviour. '
                    '1.5 = 50% buffer on top. Range [0.5, 3.0].'
                ),
                verbose_name='معامل كمية الأمان',
            ),
        ),
    ]
