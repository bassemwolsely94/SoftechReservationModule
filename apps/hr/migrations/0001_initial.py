from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users',    '0001_initial'),
        ('branches', '0001_initial'),
        ('approvals', '0001_initial'),
    ]

    operations = [
        # ── LeaveType ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='LeaveType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('code',    models.CharField(max_length=30, unique=True, verbose_name='الكود')),
                ('name',    models.CharField(max_length=100, verbose_name='الاسم')),
                ('name_ar', models.CharField(max_length=100, verbose_name='الاسم بالعربي')),
                ('is_paid',           models.BooleanField(default=True,  verbose_name='مدفوعة')),
                ('accrues_balance',   models.BooleanField(default=True,  verbose_name='ترصيد سنوي')),
                ('max_days_per_year', models.PositiveSmallIntegerField(default=21, verbose_name='الحد الأقصى (أيام/سنة)')),
                ('max_days_per_request', models.PositiveSmallIntegerField(default=14, verbose_name='الحد الأقصى للطلب الواحد')),
                ('approval_workflow_code', models.CharField(default='leave_request', max_length=60, verbose_name='كود مسار الموافقة')),
                ('is_active', models.BooleanField(default=True, verbose_name='مفعّل')),
            ],
            options={'ordering': ['code'], 'verbose_name': 'نوع إجازة', 'verbose_name_plural': 'أنواع الإجازات'},
        ),

        # ── LeaveBalance ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='LeaveBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('year',            models.PositiveSmallIntegerField(verbose_name='السنة')),
                ('entitled_days',   models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='الأيام المستحقة')),
                ('consumed_days',   models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='الأيام المستهلكة')),
                ('carried_forward', models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='مُرحَّل من السنة السابقة')),
                ('updated_at',      models.DateTimeField(auto_now=True)),
                ('staff',      models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,  related_name='leave_balances', to='users.staffprofile',  verbose_name='الموظف')),
                ('leave_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,  related_name='balances',       to='hr.leavetype',        verbose_name='نوع الإجازة')),
            ],
            options={'verbose_name': 'رصيد إجازة', 'verbose_name_plural': 'أرصدة الإجازات'},
        ),
        migrations.AlterUniqueTogether(name='leavebalance', unique_together={('staff', 'leave_type', 'year')}),

        # ── LeaveRequest ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='LeaveRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('start_date',     models.DateField(verbose_name='من')),
                ('end_date',       models.DateField(verbose_name='إلى')),
                ('days_requested', models.DecimalField(decimal_places=2, max_digits=5, verbose_name='عدد الأيام')),
                ('reason',         models.TextField(blank=True, verbose_name='السبب')),
                ('status', models.CharField(
                    choices=[('draft','مسودة'),('submitted','مُقدَّم'),('approved','معتمد'),('rejected','مرفوض'),('cancelled','ملغي')],
                    db_index=True, default='draft', max_length=15, verbose_name='الحالة',
                )),
                ('rejection_reason', models.TextField(blank=True, verbose_name='سبب الرفض')),
                ('created_at',       models.DateTimeField(auto_now_add=True)),
                ('updated_at',       models.DateTimeField(auto_now=True)),
                ('staff',            models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='leave_requests',   to='users.staffprofile', verbose_name='الموظف')),
                ('leave_type',       models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requests',         to='hr.leavetype',       verbose_name='نوع الإجازة')),
                ('approval_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='leave_request', to='approvals.approvalrequest', verbose_name='طلب الموافقة')),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'طلب إجازة', 'verbose_name_plural': 'طلبات الإجازات'},
        ),
        migrations.AddIndex(model_name='leaverequest', index=models.Index(fields=['staff', 'status'],          name='hr_leave_staff_status_idx')),
        migrations.AddIndex(model_name='leaverequest', index=models.Index(fields=['start_date', 'end_date'],   name='hr_leave_dates_idx')),

        # ── ShiftTemplate ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ShiftTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name',         models.CharField(max_length=100, verbose_name='اسم الشيفت')),
                ('name_ar',      models.CharField(max_length=100, verbose_name='الاسم بالعربي')),
                ('start_time',   models.TimeField(verbose_name='وقت البدء')),
                ('end_time',     models.TimeField(verbose_name='وقت الانتهاء')),
                ('days_of_week', models.CharField(max_length=120, verbose_name='أيام العمل')),
                ('is_active',    models.BooleanField(default=True, verbose_name='مفعّل')),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='shift_templates', to='branches.branch', verbose_name='الفرع')),
            ],
            options={'verbose_name': 'نموذج شيفت', 'verbose_name_plural': 'نماذج الشيفتات'},
        ),

        # ── ShiftAssignment ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ShiftAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('valid_from',  models.DateField(verbose_name='من تاريخ')),
                ('valid_until', models.DateField(blank=True, null=True, verbose_name='حتى تاريخ')),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('staff',       models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,  related_name='shift_assignments',       to='users.staffprofile', verbose_name='الموظف')),
                ('shift',       models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,  related_name='assignments',             to='hr.shifttemplate',   verbose_name='الشيفت')),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='shift_assignments_given', to='users.staffprofile', verbose_name='عُيِّن بواسطة')),
            ],
            options={'ordering': ['-valid_from'], 'verbose_name': 'تعيين شيفت', 'verbose_name_plural': 'تعيينات الشيفت'},
        ),

        # ── OvertimeRequest ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='OvertimeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('date',   models.DateField(verbose_name='التاريخ')),
                ('hours',  models.DecimalField(decimal_places=2, max_digits=4, verbose_name='الساعات')),
                ('reason', models.TextField(verbose_name='السبب')),
                ('status', models.CharField(
                    choices=[('draft','مسودة'),('submitted','مُقدَّم'),('approved','معتمد'),('rejected','مرفوض')],
                    db_index=True, default='draft', max_length=15,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('staff',            models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='overtime_requests',  to='users.staffprofile',          verbose_name='الموظف')),
                ('branch',           models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='overtime_requests',  to='branches.branch',             verbose_name='الفرع')),
                ('approval_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='overtime_request', to='approvals.approvalrequest')),
            ],
            options={'ordering': ['-date', '-created_at'], 'verbose_name': 'طلب عمل إضافي', 'verbose_name_plural': 'طلبات العمل الإضافي'},
        ),

        # ── SalaryAdvance ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='SalaryAdvance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('amount',           models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ')),
                ('repayment_date',   models.DateField(verbose_name='تاريخ السداد المتوقع')),
                ('reason',           models.TextField(verbose_name='السبب')),
                ('status', models.CharField(
                    choices=[('draft','مسودة'),('submitted','مُقدَّم'),('approved','معتمد'),('rejected','مرفوض'),('settled','تمت التسوية')],
                    db_index=True, default='draft', max_length=15,
                )),
                ('finance_record_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='رقم سجل المالية')),
                ('settled_at',        models.DateTimeField(blank=True, null=True, verbose_name='تاريخ التسوية')),
                ('created_at',        models.DateTimeField(auto_now_add=True)),
                ('updated_at',        models.DateTimeField(auto_now=True)),
                ('staff',            models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='salary_advances',  to='users.staffprofile',          verbose_name='الموظف')),
                ('approval_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='salary_advance', to='approvals.approvalrequest')),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'سلفة راتب', 'verbose_name_plural': 'سلف الرواتب'},
        ),

        # ── ExpenseClaim ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ExpenseClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('category', models.CharField(
                    choices=[
                        ('transport','مواصلات'),('meal','وجبات'),('accommodation','إقامة'),
                        ('stationery','قرطاسية'),('equipment','معدات'),('mamoriya','مأمورية'),('other','أخرى'),
                    ],
                    db_index=True, max_length=20, verbose_name='الفئة',
                )),
                ('expense_date',   models.DateField(verbose_name='تاريخ المصروف')),
                ('amount',         models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ')),
                ('description',    models.TextField(verbose_name='الوصف')),
                ('receipt',        models.FileField(blank=True, null=True, upload_to='hr/receipts/%Y/%m/', verbose_name='صورة الإيصال')),
                ('trip_destination', models.CharField(blank=True, max_length=200, verbose_name='وجهة المأمورية')),
                ('trip_purpose',     models.TextField(blank=True, verbose_name='غرض المأمورية')),
                ('trip_start',       models.DateField(blank=True, null=True, verbose_name='تاريخ المغادرة')),
                ('trip_end',         models.DateField(blank=True, null=True, verbose_name='تاريخ العودة')),
                ('distance_km',      models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, verbose_name='المسافة (كم)')),
                ('transport_type',   models.CharField(blank=True, max_length=50, verbose_name='وسيلة النقل')),
                ('allowance_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='بدل المأمورية')),
                ('status', models.CharField(
                    choices=[('draft','مسودة'),('submitted','مُقدَّم'),('approved','معتمد'),('rejected','مرفوض'),('paid','تم الصرف')],
                    db_index=True, default='draft', max_length=15,
                )),
                ('finance_record_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='رقم سجل المالية')),
                ('paid_at',           models.DateTimeField(blank=True, null=True, verbose_name='تاريخ الصرف')),
                ('rejection_reason',  models.TextField(blank=True, verbose_name='سبب الرفض')),
                ('created_at',        models.DateTimeField(auto_now_add=True)),
                ('updated_at',        models.DateTimeField(auto_now=True)),
                ('staff',            models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='expense_claims',   to='users.staffprofile', verbose_name='الموظف')),
                ('branch',           models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='expense_claims',   to='branches.branch',    verbose_name='الفرع')),
                ('approval_request', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expense_claim', to='approvals.approvalrequest')),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'مطالبة مصروفات', 'verbose_name_plural': 'مطالبات المصروفات'},
        ),
        migrations.AddIndex(model_name='expenseclaim', index=models.Index(fields=['staff', 'status'],          name='hr_exp_staff_status_idx')),
        migrations.AddIndex(model_name='expenseclaim', index=models.Index(fields=['expense_date', 'branch'],   name='hr_exp_date_branch_idx')),
    ]
