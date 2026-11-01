from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('access', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trustednetwork',
            name='cidr',
            field=models.CharField(max_length=43, unique=True, verbose_name='نطاق الشبكة (CIDR)'),
        ),
    ]
