# Generated migration: Add CRM segmentation fields to Customer
# Fields: segment, ltv, last_visit_date, days_since_last_visit,
#         purchase_count_90d, complaint_risk_score, segment_updated_at

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0014_purchasehistory_trans_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='segment',
            field=models.CharField(
                blank=True, db_index=True, max_length=15,
                choices=[
                    ('vip',     'VIP 👑'),
                    ('loyal',   'مخلص'),
                    ('regular', 'عادي'),
                    ('at_risk', 'في خطر ⚠️'),
                    ('dormant', 'نائم 💤'),
                    ('new',     'جديد 🌱'),
                    ('churned', 'مفقود ❌'),
                ],
                verbose_name='شريحة العميل',
                help_text='Computed daily by segment_customers management command',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='ltv',
            field=models.DecimalField(
                blank=True, null=True,
                max_digits=12, decimal_places=2,
                verbose_name='القيمة الكلية للعميل (LTV)',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='last_visit_date',
            field=models.DateField(
                blank=True, null=True, db_index=True,
                verbose_name='آخر زيارة',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='days_since_last_visit',
            field=models.PositiveIntegerField(
                blank=True, null=True, db_index=True,
                verbose_name='الأيام منذ آخر زيارة',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='purchase_count_90d',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='عدد المشتريات (90 يوم)',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='complaint_risk_score',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                verbose_name='مخاطر الشكوى',
                help_text='0–100: computed from complaint history, call frequency, unfulfilled requests',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='segment_updated_at',
            field=models.DateTimeField(
                blank=True, null=True,
                verbose_name='آخر تحديث للتصنيف',
            ),
        ),
    ]
