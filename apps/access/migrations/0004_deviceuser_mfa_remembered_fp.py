from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('access', '0003_device'),
    ]

    operations = [
        migrations.AddField(
            model_name='deviceuser',
            name='mfa_remembered_fp',
            field=models.CharField(blank=True, default='', max_length=24),
        ),
    ]
