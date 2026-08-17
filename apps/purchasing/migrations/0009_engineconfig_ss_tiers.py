from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0008_engineconfig_ss_multiplier'),
    ]

    operations = [
        # Threshold above which the ceil-formula tier kicks in (default 2.0)
        migrations.AddField(
            model_name='engineconfig',
            name='ss_high_threshold',
            field=models.FloatField(
                default=2.0,
                verbose_name='حد الطلب العالي (وحدة/شهر)',
                help_text=(
                    'monthly_avg × multiplier >= this value → safety = ceil(avg × multiplier). '
                    'Default 2.0. Range [0.5, 10.0].'
                ),
            ),
        ),
        # Fixed output for the "mid" tier: avg in [0.5, high_threshold)
        migrations.AddField(
            model_name='engineconfig',
            name='ss_tier_mid',
            field=models.FloatField(
                default=2.0,
                verbose_name='كمية أمان فئة متوسطة (0.5 – حد عالي)',
                help_text=(
                    'Fixed safety stock for items whose monthly_avg × multiplier is in [0.5, high_threshold). '
                    'Default 2.'
                ),
            ),
        ),
        # Fixed output for the "low" tier: avg in [0.16, 0.5)
        migrations.AddField(
            model_name='engineconfig',
            name='ss_tier_low',
            field=models.FloatField(
                default=1.0,
                verbose_name='كمية أمان فئة منخفضة (0.16 – 0.5)',
                help_text=(
                    'Fixed safety stock for items whose monthly_avg × multiplier is in [0.16, 0.5). '
                    'Default 1.'
                ),
            ),
        ),
        # Fixed output for the "very low" tier: avg in [0.016, 0.16)
        migrations.AddField(
            model_name='engineconfig',
            name='ss_tier_vlow',
            field=models.FloatField(
                default=0.5,
                verbose_name='كمية أمان فئة نادرة (0.016 – 0.16)',
                help_text=(
                    'Fixed safety stock for items whose monthly_avg × multiplier is in [0.016, 0.16). '
                    'Default 0.5.'
                ),
            ),
        ),
    ]
