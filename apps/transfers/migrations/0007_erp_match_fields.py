"""
apps/transfers/migrations/0007_erp_match_fields.py

Add ERP match verification fields to TransferRequest.
All fields are additive — no drops, no renames, safe on live data.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0006_transferrequestmessage_soft_delete'),
        ('transfers', '0003_transferrequestmessage_is_deleted_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_status',
            field=models.CharField(
                blank=True, choices=[
                    ('pending',   'قيد التحقق'),
                    ('matched',   'مطابق'),
                    ('partial',   'مطابقة جزئية'),
                    ('not_found', 'غير موجود'),
                    ('timeout',   'انتهت المهلة'),
                ],
                db_index=True, default='', max_length=20,
                verbose_name='حالة مطابقة ERP',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_matched_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت المطابقة'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_doc_code',
            field=models.CharField(blank=True, max_length=20, verbose_name='كود نوع المستند'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_doc_date',
            field=models.DateField(blank=True, null=True, verbose_name='تاريخ المستند'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_doc_value',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=14,
                null=True, verbose_name='قيمة المستند',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_user_code',
            field=models.CharField(blank=True, max_length=50, verbose_name='كود المستخدم (ERP)'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_store_code',
            field=models.CharField(blank=True, max_length=50, verbose_name='كود المخزن (ERP)'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_matched_items',
            field=models.JSONField(blank=True, default=list, verbose_name='الأصناف المطابقة'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_last_checked',
            field=models.DateTimeField(blank=True, null=True, verbose_name='آخر فحص'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_check_attempts',
            field=models.PositiveIntegerField(default=0, verbose_name='عدد محاولات الفحص'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_match_detail',
            field=models.CharField(blank=True, max_length=500, verbose_name='تفاصيل المطابقة'),
        ),
    ]
