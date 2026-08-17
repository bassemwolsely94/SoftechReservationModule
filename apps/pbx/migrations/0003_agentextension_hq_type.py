from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pbx', '0002_agentextension_update'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agentextension',
            name='extension_type',
            field=models.CharField(
                choices=[
                    ('agent',   'عامل مركز اتصال'),
                    ('branch',  'تحويلة فرع'),
                    ('hq',      'موظف إداري (المقر الرئيسي)'),
                    ('gateway', 'بوابة خارجية (GoIP/Trunk)'),
                    ('other',   'أخرى'),
                ],
                default='other',
                db_index=True,
                max_length=10,
                verbose_name='نوع التحويلة',
            ),
        ),
    ]
