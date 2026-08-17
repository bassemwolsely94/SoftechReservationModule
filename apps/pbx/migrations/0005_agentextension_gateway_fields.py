from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pbx', '0004_merge_20260609_0122'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentextension',
            name='gateway_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('mobile',   'خط موبايل (GoIP/GSM)'),
                    ('landline', 'خط أرضي (Grandstream/PSTN)'),
                    ('sip',      'SIP Trunk'),
                    ('other_gw', 'بوابة أخرى'),
                ],
                default='',
                help_text='موبايل (GoIP) أو أرضي (Grandstream) — فقط للتحويلات من نوع gateway',
                max_length=12,
                verbose_name='نوع البوابة',
            ),
        ),
        migrations.AddField(
            model_name='agentextension',
            name='call_prefix',
            field=models.CharField(
                blank=True,
                default='',
                help_text='البادئة التي يضيفها الـ PBX لأرقام المتصلين على هذه البوابة (مثل 0 أو 00 أو +2)',
                max_length=20,
                verbose_name='بادئة الرقم',
            ),
        ),
        migrations.AddField(
            model_name='agentextension',
            name='call_suffix',
            field=models.CharField(
                blank=True,
                default='',
                help_text='اللاحقة التي يضيفها الـ PBX (نادرة — اتركها فارغة إن لم توجد)',
                max_length=20,
                verbose_name='لاحقة الرقم',
            ),
        ),
        # Seed gateway_type for the two known gateways
        migrations.RunSQL(
            sql="""
                UPDATE pbx_agentextension
                SET gateway_type = 'mobile'
                WHERE extension_type = 'gateway'
                  AND (sip_peer LIKE 'goip%' OR extension LIKE 'goip%');

                UPDATE pbx_agentextension
                SET gateway_type = 'landline'
                WHERE extension_type = 'gateway'
                  AND (sip_peer LIKE 'grandstream%' OR extension LIKE 'grandstream%');
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
