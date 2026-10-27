from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches',  '0001_initial'),
        ('catalog',   '0001_initial'),
        ('customers', '0003_alter_purchasehistory_invoice_date'),
        ('users',     '0001_initial'),
    ]

    operations = [

        # ── ChronicMedicationProfile ──────────────────────────────────────────
        migrations.CreateModel(
            name='ChronicMedicationProfile',
            fields=[
                ('id',                    models.BigAutoField(auto_created=True, primary_key=True)),
                ('is_chronic',            models.BooleanField(db_index=True, default=True, verbose_name='دواء مزمن')),
                ('avg_daily_usage',       models.DecimalField(decimal_places=3, default=1, max_digits=8, verbose_name='متوسط الاستخدام اليومي')),
                ('pack_size',             models.DecimalField(decimal_places=3, default=30, max_digits=8, verbose_name='حجم العبوة')),
                ('expected_duration_days', models.PositiveIntegerField(default=30, verbose_name='مدة العبوة المتوقعة')),
                ('followup_before_days',  models.PositiveIntegerField(default=5, verbose_name='أيام التذكير قبل النفاد')),
                ('notes',                 models.TextField(blank=True, verbose_name='ملاحظات')),
                ('source',                models.CharField(
                    choices=[('manual','✍️ إدخال يدوي'),('erp_infer','🤖 استنتاج من الـ ERP')],
                    default='manual', max_length=12, verbose_name='مصدر البيانات',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile', verbose_name='أنشئ بواسطة',
                )),
                ('item', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chronic_profile',
                    to='catalog.item', verbose_name='الصنف',
                )),
            ],
            options={'ordering': ['item__name'], 'verbose_name': 'بروفايل دواء مزمن'},
        ),

        # ── FollowUpTask ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='FollowUpTask',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True)),
                ('task_type',    models.CharField(
                    choices=[('refill','💊 تذكير إعادة صرف'),('chronic','🏥 متابعة مريض مزمن'),('demand','📋 متابعة طلب عميل'),('custom','📝 مخصص')],
                    db_index=True, default='refill', max_length=10, verbose_name='نوع المهمة',
                )),
                ('due_date',     models.DateField(db_index=True, verbose_name='تاريخ الاستحقاق')),
                ('status',       models.CharField(
                    choices=[('pending','معلق'),('called','تم الاتصال — لا رد'),('done','مكتمل'),('missed','فائت'),('auto_closed','أُغلق تلقائياً'),('cancelled','ملغي')],
                    db_index=True, default='pending', max_length=12, verbose_name='الحالة',
                )),
                ('notes',        models.TextField(blank=True, verbose_name='ملاحظات')),
                ('result_note',  models.TextField(blank=True, verbose_name='ملاحظة النتيجة')),
                ('attempts',     models.PositiveIntegerField(default=0, verbose_name='عدد محاولات الاتصال')),
                ('source_sale_date', models.DateField(blank=True, null=True, verbose_name='تاريخ آخر بيع')),
                # ERP transaction references stored as strings (not FK — erp app not installed)
                ('source_erp_transaction',  models.CharField(max_length=50, blank=True, verbose_name='رقم معاملة ERP المصدر')),
                ('closing_erp_transaction', models.CharField(max_length=50, blank=True, verbose_name='رقم معاملة ERP الإغلاق')),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                # related_names prefixed with chronic_ to avoid clashes with demand.FollowUpTask
                ('assigned_to',  models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chronic_followup_tasks', to='users.staffprofile', verbose_name='مُعيَّن لـ')),
                ('branch',       models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chronic_followup_tasks', to='branches.branch', verbose_name='الفرع')),
                ('chronic_profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='followup_tasks', to='followups.chronicmedicationprofile', verbose_name='بروفايل الدواء المزمن')),
                ('completed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='completed_followup_tasks', to='users.staffprofile', verbose_name='أُنجز بواسطة')),
                ('created_by',   models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_followup_tasks', to='users.staffprofile', verbose_name='أنشئ بواسطة')),
                ('customer',     models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='followup_tasks', to='customers.customer', verbose_name='العميل')),
                ('item',         models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='followup_tasks', to='catalog.item', verbose_name='الصنف')),
            ],
            options={'ordering': ['due_date', '-created_at'], 'verbose_name': 'مهمة متابعة'},
        ),
        migrations.AddIndex(model_name='followuptask', index=models.Index(fields=['status', 'due_date'], name='fu_status_due_idx')),
        migrations.AddIndex(model_name='followuptask', index=models.Index(fields=['customer', 'status'], name='fu_customer_status_idx')),
        migrations.AddIndex(model_name='followuptask', index=models.Index(fields=['item', 'status'], name='fu_item_status_idx')),
        migrations.AddIndex(model_name='followuptask', index=models.Index(fields=['branch', 'status', 'due_date'], name='fu_branch_status_due_idx')),
    ]
