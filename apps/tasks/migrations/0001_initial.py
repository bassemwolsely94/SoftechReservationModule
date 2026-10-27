import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('catalog', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        # ── TaskSchedule (no FK to OperationalTask) ────────────────────────────
        migrations.CreateModel(
            name='TaskSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='اسم الجدول')),
                ('task_type', models.CharField(choices=[
                    ('stock_count', 'جرد المخزون'), ('receiving', 'استلام بضاعة'),
                    ('transfer', 'طلب تحويل'), ('delivery', 'توصيل'),
                    ('shortage', 'قائمة نقص'), ('purchasing', 'مشتريات'),
                    ('maintenance', 'صيانة'), ('meeting', 'اجتماع'),
                    ('training', 'تدريب'), ('audit', 'تدقيق'),
                    ('customer', 'خدمة عملاء'), ('other', 'أخرى'),
                ], default='other', max_length=30, verbose_name='نوع المهمة')),
                ('category', models.CharField(choices=[
                    ('operations', 'عمليات'), ('logistics', 'لوجستيات'),
                    ('purchasing', 'مشتريات'), ('sales', 'مبيعات'),
                    ('hr', 'موارد بشرية'), ('admin', 'إدارة'),
                ], default='operations', max_length=30, verbose_name='التصنيف')),
                ('priority', models.CharField(choices=[
                    ('low', 'منخفضة'), ('normal', 'عادية'), ('high', 'عالية'),
                    ('urgent', 'عاجلة'), ('critical', 'حرجة'),
                ], default='normal', max_length=20, verbose_name='الأولوية')),
                ('title_template', models.CharField(max_length=255, verbose_name='قالب العنوان')),
                ('description_template', models.TextField(blank=True, verbose_name='قالب الوصف')),
                ('assign_to_role', models.CharField(blank=True, max_length=30, verbose_name='يُعيَّن إلى الدور')),
                ('frequency', models.CharField(choices=[
                    ('none', 'لا تتكرر'), ('daily', 'يومياً'),
                    ('weekly', 'أسبوعياً'), ('monthly', 'شهرياً'),
                ], default='daily', max_length=10, verbose_name='التكرار')),
                ('day_of_week', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='يوم الأسبوع')),
                ('day_of_month', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='يوم الشهر')),
                ('time_of_day', models.TimeField(blank=True, null=True, verbose_name='وقت التنفيذ')),
                ('advance_days', models.PositiveSmallIntegerField(default=1, verbose_name='أيام مسبقة')),
                ('estimated_hours', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('is_active', models.BooleanField(default=True, verbose_name='نشط')),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('next_run_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_schedules',
                    to='branches.branch', verbose_name='الفرع',
                )),
                ('assign_to', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='scheduled_tasks',
                    to='users.staffprofile', verbose_name='يُعيَّن إلى',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'جدول مهام',
                'verbose_name_plural': 'جداول المهام',
                'ordering': ['name'],
            },
        ),

        # ── OperationalTask ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='OperationalTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_number', models.CharField(blank=True, max_length=20, null=True, unique=True, verbose_name='رقم المهمة')),
                ('title', models.CharField(max_length=255, verbose_name='عنوان المهمة')),
                ('description', models.TextField(blank=True, verbose_name='الوصف')),
                ('task_type', models.CharField(choices=[
                    ('stock_count', 'جرد المخزون'), ('receiving', 'استلام بضاعة'),
                    ('transfer', 'طلب تحويل'), ('delivery', 'توصيل'),
                    ('shortage', 'قائمة نقص'), ('purchasing', 'مشتريات'),
                    ('maintenance', 'صيانة'), ('meeting', 'اجتماع'),
                    ('training', 'تدريب'), ('audit', 'تدقيق'),
                    ('customer', 'خدمة عملاء'), ('other', 'أخرى'),
                ], db_index=True, default='other', max_length=30, verbose_name='نوع المهمة')),
                ('category', models.CharField(choices=[
                    ('operations', 'عمليات'), ('logistics', 'لوجستيات'),
                    ('purchasing', 'مشتريات'), ('sales', 'مبيعات'),
                    ('hr', 'موارد بشرية'), ('admin', 'إدارة'),
                ], db_index=True, default='operations', max_length=30, verbose_name='التصنيف')),
                ('priority', models.CharField(choices=[
                    ('low', 'منخفضة'), ('normal', 'عادية'), ('high', 'عالية'),
                    ('urgent', 'عاجلة'), ('critical', 'حرجة'),
                ], db_index=True, default='normal', max_length=20, verbose_name='الأولوية')),
                ('status', models.CharField(choices=[
                    ('open', 'مفتوحة'), ('in_progress', 'قيد التنفيذ'),
                    ('on_hold', 'متوقفة'), ('completed', 'مكتملة'), ('cancelled', 'ملغاة'),
                ], db_index=True, default='open', max_length=20, verbose_name='الحالة')),
                ('related_model', models.CharField(blank=True, max_length=50, verbose_name='النموذج المرتبط')),
                ('related_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='معرّف السجل المرتبط')),
                ('due_date', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='الموعد النهائي')),
                ('start_date', models.DateTimeField(blank=True, null=True, verbose_name='تاريخ البدء')),
                ('estimated_hours', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name='الساعات المقدَّرة')),
                ('actual_hours', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name='الساعات الفعلية')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الاكتمال')),
                ('completion_notes', models.TextField(blank=True, verbose_name='ملاحظات الإغلاق')),
                ('recurrence', models.CharField(choices=[
                    ('none', 'لا تتكرر'), ('daily', 'يومياً'),
                    ('weekly', 'أسبوعياً'), ('monthly', 'شهرياً'),
                ], default='none', max_length=10, verbose_name='التكرار')),
                ('tags', models.CharField(blank=True, max_length=500, verbose_name='الوسوم')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='tasks', to='branches.branch', verbose_name='الفرع',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_tasks',
                    to='users.staffprofile', verbose_name='أنشئ بواسطة',
                )),
                ('assigned_to', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='primary_tasks',
                    to='users.staffprofile', verbose_name='مُعيَّن إلى',
                )),
                ('completed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='completed_tasks',
                    to='users.staffprofile', verbose_name='أُكمل بواسطة',
                )),
                ('parent_task', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subtasks', to='tasks.operationaltask', verbose_name='المهمة الأم',
                )),
                ('schedule', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='generated_tasks',
                    to='tasks.taskschedule', verbose_name='الجدولة المصدر',
                )),
            ],
            options={
                'verbose_name': 'مهمة تشغيلية',
                'verbose_name_plural': 'المهام التشغيلية',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['status', 'priority'], name='tasks_oper_status_pri_idx'),
                    models.Index(fields=['branch', 'status'], name='tasks_oper_branch_sta_idx'),
                    models.Index(fields=['assigned_to', 'status'], name='tasks_oper_assign_sta_idx'),
                    models.Index(fields=['due_date'], name='tasks_oper_due_date_idx'),
                ],
            },
        ),

        # ── TaskAssignment ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TaskAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[
                    ('lead', 'مسؤول رئيسي'), ('contributor', 'مساهم'),
                    ('reviewer', 'مراجع'), ('observer', 'مراقب'),
                ], default='contributor', max_length=20, verbose_name='الدور')),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('is_completed', models.BooleanField(default=False, verbose_name='أنهى')),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='assignments', to='tasks.operationaltask', verbose_name='المهمة',
                )),
                ('staff', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_assignments',
                    to='users.staffprofile', verbose_name='الموظف',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assignments_made',
                    to='users.staffprofile', verbose_name='عُيِّن بواسطة',
                )),
            ],
            options={
                'verbose_name': 'تعيين مهمة',
                'verbose_name_plural': 'تعيينات المهام',
                'unique_together': {('task', 'staff')},
            },
        ),

        # ── TaskItem ───────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TaskItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_name', models.CharField(blank=True, max_length=255, verbose_name='اسم الصنف')),
                ('item_code', models.CharField(blank=True, max_length=50, verbose_name='كود الصنف')),
                ('quantity_expected', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name='الكمية المتوقعة')),
                ('quantity_actual', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name='الكمية الفعلية')),
                ('unit', models.CharField(blank=True, max_length=30, verbose_name='الوحدة')),
                ('notes', models.CharField(blank=True, max_length=500, verbose_name='ملاحظات')),
                ('is_checked', models.BooleanField(default=False, verbose_name='تم التحقق')),
                ('checked_at', models.DateTimeField(blank=True, null=True)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items', to='tasks.operationaltask', verbose_name='المهمة',
                )),
                ('item', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_items',
                    to='catalog.item', verbose_name='الصنف',
                )),
                ('checked_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'عنصر مهمة',
                'verbose_name_plural': 'عناصر المهام',
                'ordering': ['sort_order', 'id'],
            },
        ),

        # ── TaskMessage ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TaskMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message_type', models.CharField(choices=[
                    ('comment', 'تعليق'), ('status_change', 'تغيير الحالة'),
                    ('assignment', 'تعيين'), ('system', 'نظام'),
                ], default='comment', max_length=20, verbose_name='نوع الرسالة')),
                ('body', models.TextField(verbose_name='النص')),
                ('is_deleted', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='messages', to='tasks.operationaltask', verbose_name='المهمة',
                )),
                ('author', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_messages',
                    to='users.staffprofile', verbose_name='الكاتب',
                )),
            ],
            options={
                'verbose_name': 'رسالة مهمة',
                'verbose_name_plural': 'رسائل المهام',
                'ordering': ['created_at'],
            },
        ),

        # ── TaskAttachment ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TaskAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='tasks/attachments/%Y/%m/', verbose_name='الملف')),
                ('file_name', models.CharField(blank=True, max_length=255)),
                ('file_type', models.CharField(blank=True, max_length=50)),
                ('file_size', models.PositiveIntegerField(blank=True, null=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attachments', to='tasks.operationaltask', verbose_name='المهمة',
                )),
                ('uploaded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'مرفق مهمة',
                'verbose_name_plural': 'مرفقات المهام',
                'ordering': ['-uploaded_at'],
            },
        ),

        # ── TaskAuditLog ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='TaskAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[
                    ('created', 'إنشاء'), ('status_changed', 'تغيير الحالة'),
                    ('assigned', 'تعيين'), ('unassigned', 'إلغاء تعيين'),
                    ('priority_changed', 'تغيير الأولوية'),
                    ('due_date_changed', 'تغيير الموعد'),
                    ('completed', 'اكتمال'), ('comment_added', 'إضافة تعليق'),
                    ('attachment_added', 'إضافة مرفق'), ('field_changed', 'تغيير حقل'),
                ], max_length=30, verbose_name='الإجراء')),
                ('field_name', models.CharField(blank=True, max_length=50, verbose_name='الحقل')),
                ('old_value', models.TextField(blank=True, verbose_name='القيمة القديمة')),
                ('new_value', models.TextField(blank=True, verbose_name='القيمة الجديدة')),
                ('extra', models.JSONField(blank=True, default=dict, verbose_name='بيانات إضافية')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='audit_logs', to='tasks.operationaltask', verbose_name='المهمة',
                )),
                ('actor', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_audit_logs',
                    to='users.staffprofile', verbose_name='المنفِّذ',
                )),
            ],
            options={
                'verbose_name': 'سجل تدقيق المهام',
                'verbose_name_plural': 'سجلات تدقيق المهام',
                'ordering': ['-created_at'],
            },
        ),
    ]
