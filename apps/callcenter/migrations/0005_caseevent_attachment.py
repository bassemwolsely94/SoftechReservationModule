from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('callcenter', '0004_rename_callcenter__cust_status_idx_callcenter__custome_aa45dc_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='caseevent',
            name='attachment',
            field=models.FileField(
                blank=True, null=True,
                upload_to='callcenter/case_events/%Y/%m/',
                verbose_name='المرفق',
            ),
        ),
        migrations.AddField(
            model_name='caseevent',
            name='attachment_type',
            field=models.CharField(
                blank=True, max_length=10,
                choices=[
                    ('image',    '🖼️ صورة'),
                    ('voice',    '🎙️ صوت'),
                    ('document', '📄 مستند'),
                ],
                verbose_name='نوع المرفق',
            ),
        ),
    ]
