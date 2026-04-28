from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches',     '0001_initial'),
        ('catalog',      '0001_initial'),
        ('customers',    '0001_initial'),
        ('users',        '0001_initial'),
    ]

    operations = [

        # ── DemandRecord ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='DemandRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('demand_number', models.CharField(blank=True, max_length=20, unique=True, verbose_name='رقم الطلب')),
                ('phone', models.CharField(db_index=True, max_length=50, verbose_name='رقم الهاتف')),
                ('customer_name', models.CharField(max_length=255, verbose_name='اسم العميل')),
                ('phcode', models.CharField(blank=True, db_index=True, max_length=20, verbose_name='كود PIC (ERP)')),
                ('erp_branch_code', models.CharField(blank=True, max_length=10)),
                ('status', models.CharField(
                    choices=[
                        ('new', 'جديد — لم يُعالَج'),
                        ('assigned', 'مُعيَّن — جارٍ المتابعة'),
                        ('follow_up', 'متابعة — في الانتظار'),
                        ('stock_eta', 'في انتظار المخزون'),
                        ('transfer_suggested', 'تم اقتراح تحويل'),
                        ('purchasing_flagged', 'مُرسَل للمشتريات'),
                        ('fulfilled', 'تم التسليم ✅'),
                        ('lost', 'مبيعة ضائعة ❌'),
                        ('cancelled', 'ملغي'),
                    ],
                    db_index=True, default='new', max_length=25, verbose_name='الحالة',
                )),
                ('priority', models.CharField(
                    choices=[
                        ('low', 'منخفضة'), ('normal', 'عادية'), ('high', 'مرتفعة'),
                        ('urgent', 'عاجلة 🔴'), ('chronic', 'مريض مزمن 💊'),
                    ],
                    default='normal', max_length=10,
                )),
                ('source', models.CharField(
                    choices=[
                        ('walk_in', 'زيارة مباشرة'), ('phone', 'اتصال هاتفي'),
                        ('whatsapp', 'واتساب'), ('delivery', 'توصيل'),
                        ('online', 'أونلاين'), ('call_center', 'مركز الاتصالات'),
                        ('other', 'أخرى'),
                    ],
                    default='walk_in', max_length=20,
                )),
                ('follow_up_date', models.DateField(blank=True, db_index=True, null=True)),
                ('expected_stock_date', models.DateField(blank=True, null=True)),
                ('lost_reason', models.CharField(
                    blank=True, max_length=30,
                    choices=[
                        ('no_stock', 'لا يوجد مخزون'), ('delayed', 'تأخر الوصول'),
                        ('discontinued', 'متوقف عن الإنتاج'), ('no_response', 'لا استجابة من العميل'),
                        ('price', 'السعر مرتفع'), ('competitor', 'ذهب لمنافس'), ('other', 'أخرى'),
                    ],
                    verbose_name='سبب الفقد',
                )),
                ('erp_invoice_ref', models.CharField(blank=True, max_length=100)),
                ('fulfilled_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('assigned_at', models.DateTimeField(blank=True, null=True)),
                ('contacted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_demands', to='users.staffprofile', verbose_name='مُعيَّن لـ',
                )),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='demand_records', to='branches.branch', verbose_name='الفرع',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_demands', to='users.staffprofile', verbose_name='أنشئ بواسطة',
                )),
                ('customer', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='demand_records', to='customers.customer', verbose_name='العميل',
                )),
            ],
            options={
                'verbose_name': 'طلب طلب',
                'verbose_name_plural': 'طلبات الطلب',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='demandrecord',
            index=models.Index(fields=['status', 'branch'], name='demand_status_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='demandrecord',
            index=models.Index(fields=['follow_up_date'], name='demand_followup_idx'),
        ),
        migrations.AddIndex(
            model_name='demandrecord',
            index=models.Index(fields=['phone'], name='demand_phone_idx'),
        ),
        migrations.AddIndex(
            model_name='demandrecord',
            index=models.Index(fields=['status', 'priority'], name='demand_status_priority_idx'),
        ),

        # ── DemandItem ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='DemandItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('item_name_free', models.CharField(blank=True, max_length=255, verbose_name='اسم الصنف (حر)')),
                ('quantity', models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name='الكمية المطلوبة')),
                ('demand_type', models.CharField(
                    choices=[
                        ('out_of_stock', 'نفد من المخزون'), ('low_stock', 'مخزون منخفض'),
                        ('new_item', 'صنف جديد / غير مُخزَّن'), ('price_check', 'استفسار سعر'),
                    ],
                    default='out_of_stock', max_length=15, verbose_name='نوع الطلب',
                )),
                ('item_status', models.CharField(
                    choices=[
                        ('pending', 'قيد الانتظار'), ('sourcing', 'جارٍ التوفير'),
                        ('fulfilled', 'تم التسليم ✅'), ('lost', 'ضاعت المبيعة ❌'), ('cancelled', 'ملغي'),
                    ],
                    default='pending', max_length=15, verbose_name='حالة الصنف',
                )),
                ('is_long_shortage', models.BooleanField(default=False, verbose_name='نقص طويل الأمد')),
                ('is_discontinued', models.BooleanField(default=False, verbose_name='متوقف عن الإنتاج')),
                ('shortage_note', models.CharField(blank=True, max_length=255)),
                ('notes', models.CharField(blank=True, max_length=255)),
                ('demand', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items', to='demand.demandrecord', verbose_name='طلب الطلب',
                )),
                ('item', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='demand_items', to='catalog.item', verbose_name='الصنف',
                )),
            ],
            options={'verbose_name': 'صنف في الطلب', 'verbose_name_plural': 'أصناف الطلب'},
        ),

        # ── FollowUpTask ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='FollowUpTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('task_type', models.CharField(
                    choices=[
                        ('call', 'اتصال هاتفي'), ('whatsapp', 'واتساب'), ('sms', 'رسالة نصية'),
                        ('visit', 'زيارة'), ('stock_check', 'فحص المخزون'), ('other', 'أخرى'),
                    ],
                    default='call', max_length=15,
                )),
                ('due_date', models.DateTimeField(db_index=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'مجدولة'), ('done', 'تم التنفيذ'),
                        ('missed', 'فائت'), ('cancelled', 'ملغي'),
                    ],
                    default='pending', max_length=15,
                )),
                ('note', models.TextField(blank=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assigned_to', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='followup_tasks', to='users.staffprofile',
                )),
                ('completed_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='completed_followups', to='users.staffprofile',
                )),
                ('demand', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='followups', to='demand.demandrecord', verbose_name='الطلب',
                )),
            ],
            options={'verbose_name': 'مهمة متابعة', 'verbose_name_plural': 'مهام المتابعة', 'ordering': ['due_date']},
        ),

        # ── DemandLog ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='DemandLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('log_type', models.CharField(
                    choices=[
                        ('note', '📝 ملاحظة'), ('call', '📞 مكالمة'), ('whatsapp', '💬 واتساب'),
                        ('sms', '📱 رسالة'), ('system', '⚙️ نظام'), ('status', '🔄 تغيير حالة'),
                    ],
                    default='note', max_length=10,
                )),
                ('message', models.TextField(verbose_name='الرسالة')),
                ('call_outcome', models.CharField(blank=True, max_length=20,
                    choices=[
                        ('answered', 'رد'), ('no_answer', 'لم يرد'), ('busy', 'مشغول'),
                        ('wrong_number', 'رقم خاطئ'), ('callback', 'طلب الاتصال لاحقاً'),
                    ],
                )),
                ('call_duration_seconds', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='demand_logs', to='users.staffprofile',
                )),
                ('demand', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='logs', to='demand.demandrecord', verbose_name='الطلب',
                )),
            ],
            options={'verbose_name': 'سجل', 'verbose_name_plural': 'سجلات الطلب', 'ordering': ['created_at']},
        ),

        # ── ItemDemandStat ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ItemDemandStat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('demand_count_30d',    models.PositiveIntegerField(default=0)),
                ('lost_count_30d',      models.PositiveIntegerField(default=0)),
                ('fulfilled_count_30d', models.PositiveIntegerField(default=0)),
                ('lost_qty_30d', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('is_long_shortage',  models.BooleanField(db_index=True, default=False)),
                ('is_discontinued',   models.BooleanField(default=False)),
                ('shortage_start',    models.DateField(blank=True, null=True)),
                ('suggest_order',     models.BooleanField(default=False)),
                ('suggest_transfer',  models.BooleanField(default=False)),
                ('last_updated',      models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    to='branches.branch',
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='demand_stats', to='catalog.item',
                )),
            ],
            options={
                'verbose_name': 'إحصاء طلب الصنف',
                'ordering': ['-demand_count_30d'],
                'unique_together': {('item', 'branch')},
            },
        ),
    ]
