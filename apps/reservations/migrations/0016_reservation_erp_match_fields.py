from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0009_reservation_reservation_status_3633ee_idx_and_more'),
        ('reservations', '0015_reservation_order_source_fulfillment_images'),
    ]

    operations = [
        migrations.AddField(
            model_name='reservation',
            name='erp_reference',
            field=models.CharField(blank=True, max_length=50, verbose_name='رقم مستند ERP (مبيعات)'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_status',
            field=models.CharField(
                blank=True, db_index=True, max_length=20,
                choices=[
                    ('pending', 'قيد الانتظار'),
                    ('matched', 'متطابق'),
                    ('partial', 'تطابق جزئي'),
                    ('not_found', 'غير موجود'),
                ],
                verbose_name='حالة مطابقة ERP',
            ),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_detail',
            field=models.TextField(blank=True, verbose_name='تفاصيل المطابقة'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_last_checked',
            field=models.DateTimeField(blank=True, null=True, verbose_name='آخر فحص'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_check_attempts',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='عدد المحاولات'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_matched_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت المطابقة'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_doc_code',
            field=models.CharField(blank=True, max_length=10, verbose_name='كود نوع المستند'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_doc_date',
            field=models.DateField(blank=True, null=True, verbose_name='تاريخ المستند'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_doc_value',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=14,
                null=True, verbose_name='قيمة المستند',
            ),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_user_code',
            field=models.CharField(blank=True, max_length=20, verbose_name='كود المستخدم (ERP)'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_user_id',
            field=models.CharField(blank=True, max_length=100, verbose_name='اسم مستخدم ERP'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_user_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='الاسم الكامل (ERP)'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_trans_time',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت تنفيذ المعاملة (ERP)'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_match_store_code',
            field=models.CharField(blank=True, max_length=20, verbose_name='كود المخزن (ERP)'),
        ),
        migrations.AddField(
            model_name='reservation',
            name='erp_matched_items',
            field=models.JSONField(blank=True, default=list, verbose_name='أصناف المطابقة'),
        ),
    ]
