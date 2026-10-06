from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0006_alter_demandcalculationrun_calc_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrecommendation',
            name='from_monthly_avg',
            field=models.DecimalField(
                decimal_places=4, default=0, max_digits=14,
                verbose_name='متوسط مبيعات فرع المُرسِل (شهري)',
            ),
        ),
        migrations.AddField(
            model_name='transferrecommendation',
            name='to_stock',
            field=models.DecimalField(
                decimal_places=3, default=0, max_digits=14,
                verbose_name='رصيد الفرع المستلِم',
            ),
        ),
        migrations.AddField(
            model_name='transferrecommendation',
            name='to_monthly_avg',
            field=models.DecimalField(
                decimal_places=4, default=0, max_digits=14,
                verbose_name='متوسط مبيعات فرع المستلِم (شهري)',
            ),
        ),
    ]
