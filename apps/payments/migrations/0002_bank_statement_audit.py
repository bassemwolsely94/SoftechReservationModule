from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('payments',  '0001_initial'),
        ('branches',  '0001_initial'),
        ('users',     '0001_initial'),
    ]

    operations = [
        # ── BankStatementImport ────────────────────────────────────────────────
        migrations.CreateModel(
            name='BankStatementImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('bank_name',      models.CharField(max_length=100, verbose_name='اسم البنك / المحفظة')),
                ('account_number', models.CharField(blank=True, max_length=50, verbose_name='رقم الحساب')),
                ('payment_method', models.CharField(max_length=20, verbose_name='طريقة الدفع')),
                ('statement_from', models.DateField(verbose_name='من تاريخ')),
                ('statement_to',   models.DateField(verbose_name='إلى تاريخ')),
                ('raw_file',       models.FileField(upload_to='payments/statements/%Y/%m/', verbose_name='ملف الكشف')),
                ('status', models.CharField(
                    choices=[('pending','في الانتظار'),('processing','قيد المعالجة'),('completed','مكتمل'),('failed','فشل')],
                    db_index=True, default='pending', max_length=15, verbose_name='الحالة',
                )),
                ('total_lines',     models.PositiveIntegerField(default=0, verbose_name='إجمالي السطور')),
                ('matched_lines',   models.PositiveIntegerField(default=0, verbose_name='سطور مطابَقة')),
                ('unmatched_lines', models.PositiveIntegerField(default=0, verbose_name='سطور غير مطابَقة')),
                ('error_message',   models.TextField(blank=True, verbose_name='رسالة الخطأ')),
                ('imported_at',     models.DateTimeField(auto_now_add=True, verbose_name='وقت الرفع')),
                ('completed_at',    models.DateTimeField(blank=True, null=True, verbose_name='وقت الإكمال')),
                ('branch',      models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='statement_imports', to='branches.branch',    verbose_name='الفرع')),
                ('imported_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='statement_imports',  to='users.staffprofile', verbose_name='رُفع بواسطة')),
            ],
            options={'ordering': ['-imported_at'], 'verbose_name': 'استيراد كشف حساب', 'verbose_name_plural': 'استيرادات كشوف الحسابات'},
        ),

        # ── BankStatementLine ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='BankStatementLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('transaction_date', models.DateField(db_index=True, verbose_name='تاريخ الحركة')),
                ('value_date',       models.DateField(blank=True, null=True, verbose_name='تاريخ القيمة')),
                ('reference',        models.CharField(blank=True, db_index=True, max_length=200, verbose_name='رقم المرجع')),
                ('description',      models.CharField(blank=True, max_length=500, verbose_name='البيان')),
                ('debit',            models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='مدين')),
                ('credit',           models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='دائن')),
                ('balance',          models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True, verbose_name='الرصيد')),
                ('match_confidence', models.DecimalField(decimal_places=3, default=0, max_digits=4, verbose_name='درجة الثقة (0–1)')),
                ('match_method', models.CharField(
                    choices=[('auto_exact','تطابق تلقائي دقيق'),('auto_fuzzy','تطابق تلقائي تقريبي'),('manual','تطابق يدوي'),('unmatched','غير مطابَق')],
                    db_index=True, default='unmatched', max_length=15, verbose_name='طريقة المطابقة',
                )),
                ('matched_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت المطابقة')),
                ('statement_import', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='payments.bankstatementimport', verbose_name='الكشف')),
                ('matched_payment',  models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='statement_lines', to='payments.externalpayment', verbose_name='الدفعة المطابِقة')),
                ('matched_by',       models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_matches', to='users.staffprofile', verbose_name='طابَق بواسطة')),
            ],
            options={'ordering': ['transaction_date', 'id'], 'verbose_name': 'سطر كشف حساب', 'verbose_name_plural': 'سطور كشوف الحسابات'},
        ),
        migrations.AddIndex(model_name='bankstatementline', index=models.Index(fields=['statement_import', 'match_method'], name='stmt_line_import_match_idx')),
        migrations.AddIndex(model_name='bankstatementline', index=models.Index(fields=['transaction_date', 'credit'],       name='stmt_line_date_credit_idx')),

        # ── PaymentException ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='PaymentException',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('exception_type', models.CharField(
                    choices=[
                        ('missing','دفعة مفقودة من الكشف'),('unrecorded','حركة بنكية غير مُسجَّلة'),
                        ('duplicate','دفعة مكررة'),('partial','دفع جزئي'),('wrong_branch','فرع خاطئ'),
                        ('wrong_amount','مبلغ خاطئ'),('wrong_cashier','كاشير خاطئ'),
                        ('delayed','تسوية متأخرة'),('anomaly','شذوذ / إشارة احتيال'),
                    ],
                    db_index=True, max_length=20, verbose_name='نوع الاستثناء',
                )),
                ('severity', models.CharField(
                    choices=[('info','معلومة'),('warning','تحذير'),('critical','حرج')],
                    db_index=True, default='warning', max_length=10, verbose_name='الخطورة',
                )),
                ('anomaly_score',    models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='درجة الشذوذ (0–100)')),
                ('detail',           models.TextField(blank=True, verbose_name='تفاصيل')),
                ('status', models.CharField(
                    choices=[('open','مفتوح'),('investigating','قيد التحقيق'),('resolved','محلول'),('dismissed','مرفوض')],
                    db_index=True, default='open', max_length=15, verbose_name='الحالة',
                )),
                ('resolved_at',      models.DateTimeField(blank=True, null=True, verbose_name='وقت الحل')),
                ('resolution_notes', models.TextField(blank=True, verbose_name='ملاحظات الحل')),
                ('abuse_flag_id',    models.PositiveIntegerField(blank=True, null=True, verbose_name='رقم إشارة الاحتيال')),
                ('created_at',       models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت الإنشاء')),
                ('payment',        models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='exceptions',            to='payments.externalpayment',    verbose_name='الدفعة')),
                ('statement_line', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='exceptions',            to='payments.bankstatementline',  verbose_name='سطر الكشف')),
                ('assigned_to',    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payment_exceptions_assigned', to='users.staffprofile', verbose_name='مُسنَد إلى')),
                ('resolved_by',    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payment_exceptions_resolved', to='users.staffprofile', verbose_name='حُلَّ بواسطة')),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'استثناء دفعة', 'verbose_name_plural': 'استثناءات الدفعات'},
        ),
        migrations.AddIndex(model_name='paymentexception', index=models.Index(fields=['status', 'severity'],       name='payexc_status_sev_idx')),
        migrations.AddIndex(model_name='paymentexception', index=models.Index(fields=['exception_type', 'status'], name='payexc_type_status_idx')),
    ]
