# D-09 (2026-11-19): compare-and-set price writer — new "changed in SOFTECH" state + the values
# both sides held. Additive only (a choices change and a JSON field with a default).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('discount_approvals', '0006_alter_itempricechangerequest_source'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itempricechangerequest',
            name='status',
            field=models.CharField(
                choices=[('pending', 'في الانتظار'), ('approved', 'معتمد'), ('rejected', 'مرفوض'),
                         ('executed', 'منفذ في Softech'), ('failed', 'فشل في التنفيذ'),
                         ('softech_changed', 'تغيّر في SOFTECH — للمراجعة')],
                db_index=True, default='pending', max_length=20, verbose_name='الحالة'),
        ),
        migrations.AddField(
            model_name='itempricechangerequest',
            name='softech_conflict',
            field=models.JSONField(blank=True, db_default={}, default=dict,
                                   verbose_name='اختلاف SOFTECH عن القيم المعتمدة'),
        ),
    ]
