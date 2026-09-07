from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pbx', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        # Make staff nullable
        migrations.AlterField(
            model_name='agentextension',
            name='staff',
            field=models.OneToOneField(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pbx_extension',
                to='users.staffprofile',
                verbose_name='الموظف',
            ),
        ),
        # Add extension_type
        migrations.AddField(
            model_name='agentextension',
            name='extension_type',
            field=models.CharField(
                choices=[
                    ('agent',   'عامل مركز اتصال'),
                    ('branch',  'تحويلة فرع'),
                    ('gateway', 'بوابة خارجية (GoIP/Trunk)'),
                    ('other',   'أخرى'),
                ],
                default='other',
                db_index=True,
                max_length=10,
                verbose_name='نوع التحويلة',
            ),
        ),
        # Add last_status
        migrations.AddField(
            model_name='agentextension',
            name='last_status',
            field=models.CharField(blank=True, max_length=50, verbose_name='آخر حالة'),
        ),
        # Add last_ip
        migrations.AddField(
            model_name='agentextension',
            name='last_ip',
            field=models.CharField(blank=True, max_length=50, verbose_name='آخر IP مسجّل'),
        ),
        # Add updated_at
        migrations.AddField(
            model_name='agentextension',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
