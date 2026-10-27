# Adds to FollowUpTask:
#   priority_score, priority_score_updated  — smart ranking (Feature 1)
#   phone_invalid, phone_invalid_at         — bad number detection (Feature 12)
#   demand_record FK                        — bridge to demand module (Feature 23)
#   source_campaign FK                      — bridge to campaigns module (Feature 3)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0001_initial'),
        ('demand',    '0001_initial'),
        ('followups', '0012_followuptaskassignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='priority_score',
            field=models.FloatField(
                db_index=True, default=0.0,
                help_text='درجة مركّبة: LTV + خطر الانقطاع + التأخير + قناة البيع. تُحدَّث يومياً.',
                verbose_name='درجة الأولوية',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='priority_score_updated',
            field=models.DateTimeField(blank=True, null=True, verbose_name='آخر تحديث للأولوية'),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='phone_invalid',
            field=models.BooleanField(
                db_index=True, default=False,
                help_text='يُرفع تلقائياً بعد 3 محاولات فاشلة متتالية أو يدوياً من الموظف',
                verbose_name='الرقم غير صالح',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='phone_invalid_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت تأكيد عدم صلاحية الرقم'),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='demand_record',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='followup_tasks',
                to='demand.demandrecord',
                verbose_name='طلب مرتبط',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='source_campaign',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='followup_tasks',
                to='campaigns.whatsappcampaign',
                verbose_name='حملة المصدر',
            ),
        ),
    ]
