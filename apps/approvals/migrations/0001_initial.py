from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApprovalWorkflowDefinition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, help_text='مثال: leave_request | salary_advance | expense_claim | supplier_claim', max_length=60, unique=True, verbose_name='الكود')),
                ('name', models.CharField(max_length=120, verbose_name='الاسم')),
                ('name_ar', models.CharField(max_length=120, verbose_name='الاسم بالعربي')),
                ('description', models.TextField(blank=True, verbose_name='الوصف')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='مفعّل')),
                ('reject_terminates', models.BooleanField(default=True, verbose_name='الرفض ينهي الطلب فوراً')),
                ('sla_hours', models.PositiveIntegerField(blank=True, help_text='اترك فارغاً إذا لم يكن هناك SLA', null=True, verbose_name='SLA بالساعات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'مسار موافقة',
                'verbose_name_plural': 'مسارات الموافقة',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='ApprovalStepDefinition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveSmallIntegerField(db_index=True, verbose_name='الترتيب')),
                ('name', models.CharField(max_length=120, verbose_name='اسم الخطوة')),
                ('name_ar', models.CharField(max_length=120, verbose_name='اسم الخطوة بالعربي')),
                ('approver_role', models.CharField(
                    blank=True, db_index=True, max_length=20, null=True,
                    verbose_name='دور المعتمِد',
                    choices=[
                        ('admin', 'Admin — Full Access'),
                        ('call_center', 'Call Center — All Branches'),
                        ('pharmacist', 'Pharmacist — Own Branch'),
                        ('salesperson', 'Sales Person — Own Branch'),
                        ('purchasing', 'Purchasing — HQ Only'),
                        ('delivery', 'Delivery'),
                        ('viewer', 'Viewer — Read Only'),
                        ('supervisor', 'Supervisor — Call Center Supervisor'),
                        ('quality_manager', 'Quality Manager — QA & Scoring'),
                    ],
                )),
                ('restrict_to_branch', models.BooleanField(default=False, verbose_name='تقييد بفرع مقدم الطلب')),
                ('is_optional', models.BooleanField(default=False, verbose_name='اختيارية')),
                ('escalation_hours', models.PositiveSmallIntegerField(default=0, verbose_name='ساعات التصعيد')),
                ('on_reject', models.CharField(
                    choices=[('terminate', 'إنهاء الطلب فوراً'), ('next_step', 'الانتقال للخطوة التالية'), ('return_prev', 'الإعادة للخطوة السابقة')],
                    default='terminate', max_length=15, verbose_name='عند الرفض',
                )),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='steps', to='approvals.approvalworkflowdefinition', verbose_name='المسار')),
                ('approver_user', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_approval_steps', to='users.staffprofile', verbose_name='معتمِد محدد',
                )),
            ],
            options={
                'verbose_name': 'خطوة موافقة',
                'verbose_name_plural': 'خطوات الموافقة',
                'ordering': ['workflow', 'order'],
                'unique_together': {('workflow', 'order')},
            },
        ),
        migrations.CreateModel(
            name='ApprovalRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='العنوان')),
                ('body', models.TextField(blank=True, verbose_name='التفاصيل')),
                ('object_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='رقم الكائن')),
                ('context_data', models.JSONField(default=dict, verbose_name='بيانات السياق')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'مسودة'), ('pending', 'في الانتظار'),
                        ('in_review', 'قيد المراجعة'), ('approved', 'معتمد'),
                        ('rejected', 'مرفوض'), ('cancelled', 'ملغي'), ('expired', 'منتهي الصلاحية'),
                    ],
                    db_index=True, default='draft', max_length=15, verbose_name='الحالة',
                )),
                ('current_step_order', models.PositiveSmallIntegerField(default=1, verbose_name='الخطوة الحالية')),
                ('due_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='الموعد النهائي')),
                ('is_overdue', models.BooleanField(db_index=True, default=False, verbose_name='متأخر')),
                ('requested_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='تاريخ الطلب')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='تاريخ الإنهاء')),
                ('completion_note', models.TextField(blank=True, verbose_name='ملاحظة الإنهاء')),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requests', to='approvals.approvalworkflowdefinition', verbose_name='المسار')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='approval_requests_submitted', to='users.staffprofile', verbose_name='مقدم الطلب')),
                ('content_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='contenttypes.contenttype', verbose_name='نوع الكائن')),
            ],
            options={
                'verbose_name': 'طلب موافقة',
                'verbose_name_plural': 'طلبات الموافقة',
                'ordering': ['-requested_at'],
            },
        ),
        migrations.AddIndex(
            model_name='approvalrequest',
            index=models.Index(fields=['status', 'current_step_order'], name='appr_req_status_step_idx'),
        ),
        migrations.AddIndex(
            model_name='approvalrequest',
            index=models.Index(fields=['workflow', 'status'], name='appr_req_wf_status_idx'),
        ),
        migrations.AddIndex(
            model_name='approvalrequest',
            index=models.Index(fields=['requested_by', 'status'], name='appr_req_by_status_idx'),
        ),
        migrations.AddIndex(
            model_name='approvalrequest',
            index=models.Index(fields=['content_type', 'object_id'], name='appr_req_content_idx'),
        ),
        migrations.CreateModel(
            name='ApprovalDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('step_order', models.PositiveSmallIntegerField(verbose_name='ترتيب الخطوة')),
                ('step_name', models.CharField(max_length=120, verbose_name='اسم الخطوة')),
                ('decision', models.CharField(
                    choices=[
                        ('approved', 'معتمد'), ('rejected', 'مرفوض'),
                        ('delegated', 'تفويض'), ('returned', 'إعادة للمراجعة'),
                        ('auto_approved', 'اعتماد تلقائي'),
                    ],
                    db_index=True, max_length=15, verbose_name='القرار',
                )),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('decided_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت القرار')),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='decisions', to='approvals.approvalrequest', verbose_name='الطلب')),
                ('step', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='approvals.approvalstepdefinition', verbose_name='الخطوة')),
                ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='approval_decisions', to='users.staffprofile', verbose_name='المعتمِد')),
                ('delegated_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='delegated_decisions', to='users.staffprofile', verbose_name='تفويض إلى')),
            ],
            options={
                'verbose_name': 'قرار موافقة',
                'verbose_name_plural': 'قرارات الموافقة',
                'ordering': ['request', 'step_order'],
            },
        ),
        migrations.CreateModel(
            name='ApprovalEscalationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('step_order', models.PositiveSmallIntegerField(verbose_name='الخطوة')),
                ('escalated_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت التصعيد')),
                ('notified_users', models.JSONField(default=list, verbose_name='المستخدمون المُبلَّغون')),
                ('note', models.CharField(blank=True, max_length=255)),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='escalations', to='approvals.approvalrequest', verbose_name='الطلب')),
            ],
            options={
                'verbose_name': 'تصعيد',
                'verbose_name_plural': 'سجلات التصعيد',
                'ordering': ['-escalated_at'],
            },
        ),
    ]
