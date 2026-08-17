"""
apps/finance/migrations/0001_initial.py

Initial migration for the Finance Intelligence Platform.
Creates all 9 models defined in apps/finance/models.py.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
    ]

    operations = [

        # ── FinanceSchemaTable ────────────────────────────────────────────────
        migrations.CreateModel(
            name='FinanceSchemaTable',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('table_name',       models.CharField(max_length=100, unique=True)),
                ('inferred_purpose', models.CharField(blank=True, max_length=300)),
                ('row_count',        models.BigIntegerField(default=0)),
                ('columns',          models.JSONField(default=list)),
                ('sample_rows',      models.JSONField(default=list)),
                ('is_confirmed',     models.BooleanField(default=False)),
                ('sync_enabled',     models.BooleanField(default=False)),
                ('category',         models.CharField(blank=True, max_length=50)),
                ('discovered_at',    models.DateTimeField(default=django.utils.timezone.now)),
                ('notes',            models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'جدول مالي مكتشف',
                'verbose_name_plural': 'جداول مالية مكتشفة',
                'ordering': ['table_name'],
            },
        ),

        # ── Account ───────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code',         models.CharField(db_index=True, max_length=50, unique=True)),
                ('name',         models.CharField(max_length=500)),
                ('name_ar',      models.CharField(blank=True, max_length=500)),
                ('account_type', models.CharField(
                    choices=[
                        ('asset', 'أصول'), ('liability', 'التزامات'),
                        ('equity', 'حقوق الملكية'), ('revenue', 'إيرادات'),
                        ('expense', 'مصروفات'), ('cogs', 'تكلفة المبيعات'),
                        ('contra', 'مقابل'), ('memo', 'إيضاح'), ('unknown', 'غير محدد'),
                    ],
                    default='unknown', max_length=20,
                )),
                ('nature', models.CharField(
                    choices=[('debit', 'مدين'), ('credit', 'دائن')],
                    default='debit', max_length=10,
                )),
                ('parent',       models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='children', to='finance.account',
                )),
                ('level',        models.IntegerField(default=1)),
                ('is_leaf',      models.BooleanField(default=True)),
                ('is_active',    models.BooleanField(default=True)),
                ('softech_code', models.CharField(blank=True, max_length=50)),
                ('description',  models.TextField(blank=True)),
                ('synced_at',    models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'حساب',
                'verbose_name_plural': 'الحسابات',
                'ordering': ['code'],
            },
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['account_type'], name='finance_acc_account_type_idx'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['parent'], name='finance_acc_parent_idx'),
        ),

        # ── FinancialPeriod ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='FinancialPeriod',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year',         models.IntegerField()),
                ('month',        models.IntegerField(default=0)),
                ('period_type',  models.CharField(
                    choices=[('month', 'شهري'), ('quarter', 'ربع سنوي'), ('year', 'سنوي')],
                    default='month', max_length=10,
                )),
                ('period_start', models.DateField()),
                ('period_end',   models.DateField()),
                ('label',        models.CharField(blank=True, max_length=20)),
                ('is_closed',    models.BooleanField(default=False)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'فترة مالية',
                'verbose_name_plural': 'الفترات المالية',
                'ordering': ['-year', '-month'],
                'unique_together': {('year', 'month', 'period_type')},
            },
        ),

        # ── JournalEntry ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='JournalEntry',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_number', models.CharField(blank=True, db_index=True, max_length=100)),
                ('entry_date',     models.DateField(db_index=True)),
                ('branch',         models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='journal_entries', to='branches.branch',
                )),
                ('description',    models.CharField(blank=True, max_length=1000)),
                ('description_ar', models.CharField(blank=True, max_length=1000)),
                ('entry_type',     models.CharField(
                    choices=[
                        ('manual', 'يدوي'), ('sales', 'مبيعات'),
                        ('purchase', 'مشتريات'), ('cash_receipt', 'قبض نقدي'),
                        ('cash_payment', 'صرف نقدي'), ('bank_receipt', 'قبض بنكي'),
                        ('bank_payment', 'صرف بنكي'), ('depreciation', 'استهلاك'),
                        ('adjustment', 'تسوية'), ('closing', 'إقفال'),
                        ('opening', 'افتتاح'), ('expense', 'مصروف'),
                        ('payroll', 'رواتب'), ('other', 'أخرى'),
                    ],
                    default='manual', max_length=20,
                )),
                ('reference',      models.CharField(blank=True, max_length=200)),
                ('total_debit',    models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('total_credit',   models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('is_balanced',    models.BooleanField(default=True)),
                ('period',         models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='journal_entries', to='finance.financialperiod',
                )),
                ('source_table',   models.CharField(blank=True, max_length=100)),
                ('synced_at',      models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'قيد يومية',
                'verbose_name_plural': 'قيود اليومية',
                'ordering': ['-entry_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['entry_date', 'branch'], name='finance_je_date_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['entry_type'], name='finance_je_entry_type_idx'),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['period'], name='finance_je_period_idx'),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['softech_number'], name='finance_je_softech_idx'),
        ),

        # ── JournalLine ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='JournalLine',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('entry',        models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines', to='finance.journalentry',
                )),
                ('line_number',  models.IntegerField(default=1)),
                ('account',      models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='journal_lines', to='finance.account',
                )),
                ('account_code', models.CharField(blank=True, max_length=50)),
                ('description',  models.CharField(blank=True, max_length=500)),
                ('debit',        models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('credit',       models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('cost_center',  models.CharField(blank=True, max_length=50)),
                ('party_code',   models.CharField(blank=True, max_length=50)),
                ('party_name',   models.CharField(blank=True, max_length=300)),
            ],
            options={
                'verbose_name': 'سطر قيد',
                'verbose_name_plural': 'سطور القيود',
                'ordering': ['entry', 'line_number'],
            },
        ),

        # ── AccountBalance ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='AccountBalance',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account',         models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='balances', to='finance.account',
                )),
                ('period',          models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='balances', to='finance.financialperiod',
                )),
                ('branch',          models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='account_balances', to='branches.branch',
                )),
                ('opening_balance', models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('total_debit',     models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('total_credit',    models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('closing_balance', models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ('movement_count',  models.IntegerField(default=0)),
            ],
            options={
                'verbose_name': 'رصيد حساب',
                'verbose_name_plural': 'أرصدة الحسابات',
                'unique_together': {('account', 'period', 'branch')},
            },
        ),
        migrations.AddIndex(
            model_name='accountbalance',
            index=models.Index(fields=['period', 'branch'], name='finance_ab_period_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='accountbalance',
            index=models.Index(fields=['account', 'period'], name='finance_ab_account_period_idx'),
        ),

        # ── TreasuryMovement ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='TreasuryMovement',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_number', models.CharField(blank=True, db_index=True, max_length=100)),
                ('movement_date',  models.DateField(db_index=True)),
                ('movement_type',  models.CharField(
                    choices=[
                        ('receipt', 'إيصال'), ('payment', 'دفعة'),
                        ('transfer', 'تحويل داخلي'), ('opening', 'رصيد افتتاحي'),
                        ('adjustment', 'تسوية'),
                    ],
                    default='receipt', max_length=20,
                )),
                ('direction',      models.CharField(
                    choices=[('in', 'قبض'), ('out', 'صرف')], max_length=3,
                )),
                ('payment_method', models.CharField(
                    choices=[
                        ('cash', 'نقدي'), ('cheque', 'شيك'),
                        ('transfer', 'تحويل بنكي'), ('card', 'بطاقة'),
                        ('credit', 'آجل / تسهيل'), ('other', 'أخرى'),
                    ],
                    default='cash', max_length=20,
                )),
                ('account_code',   models.CharField(blank=True, max_length=50)),
                ('branch',         models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='treasury_movements', to='branches.branch',
                )),
                ('amount',         models.DecimalField(decimal_places=3, max_digits=18)),
                ('description',    models.CharField(blank=True, max_length=500)),
                ('reference',      models.CharField(blank=True, max_length=200)),
                ('party_code',     models.CharField(blank=True, max_length=50)),
                ('party_name',     models.CharField(blank=True, max_length=300)),
                ('party_type',     models.CharField(
                    blank=True,
                    choices=[
                        ('supplier', 'مورد'), ('customer', 'عميل'),
                        ('employee', 'موظف'), ('bank', 'بنك'), ('other', 'أخرى'),
                    ],
                    max_length=20,
                )),
                ('cheque_number',  models.CharField(blank=True, max_length=50)),
                ('cheque_date',    models.DateField(blank=True, null=True)),
                ('bank_name',      models.CharField(blank=True, max_length=200)),
                ('period',         models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='treasury_movements', to='finance.financialperiod',
                )),
                ('source_table',   models.CharField(blank=True, max_length=100)),
                ('synced_at',      models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'حركة خزينة',
                'verbose_name_plural': 'حركات الخزينة',
                'ordering': ['-movement_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['movement_date', 'branch'], name='finance_tm_date_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['direction'], name='finance_tm_direction_idx'),
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['payment_method'], name='finance_tm_method_idx'),
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['period'], name='finance_tm_period_idx'),
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['party_code'], name='finance_tm_party_idx'),
        ),
        migrations.AddIndex(
            model_name='treasurymovement',
            index=models.Index(fields=['softech_number'], name='finance_tm_softech_idx'),
        ),

        # ── ExpenseRecord ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ExpenseRecord',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_ref',  models.CharField(blank=True, db_index=True, max_length=100)),
                ('expense_date', models.DateField(db_index=True)),
                ('category',     models.CharField(
                    choices=[
                        ('payroll', 'رواتب وأجور'), ('rent', 'إيجارات'),
                        ('utilities', 'مرافق (كهرباء / مياه / اتصالات)'),
                        ('fuel', 'وقود ومواصلات'), ('maintenance', 'صيانة'),
                        ('delivery', 'توصيل وشحن'), ('marketing', 'تسويق وإعلان'),
                        ('finance_cost', 'تكاليف تمويلية'), ('bank_charges', 'رسوم بنكية'),
                        ('taxes', 'ضرائب ورسوم'), ('shrinkage', 'فاقد وعجز'),
                        ('expiry', 'منتهي الصلاحية'), ('returns', 'مرتجعات من العملاء'),
                        ('admin', 'مصروفات إدارية'), ('depreciation', 'استهلاك أصول'),
                        ('insurance', 'تأمين'), ('other', 'أخرى'),
                    ],
                    default='other', max_length=30,
                )),
                ('sub_category', models.CharField(blank=True, max_length=100)),
                ('branch',       models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='expense_records', to='branches.branch',
                )),
                ('amount',       models.DecimalField(decimal_places=3, max_digits=18)),
                ('description',  models.CharField(blank=True, max_length=500)),
                ('vendor',       models.CharField(blank=True, max_length=300)),
                ('reference',    models.CharField(blank=True, max_length=200)),
                ('account_code', models.CharField(blank=True, max_length=50)),
                ('cost_center',  models.CharField(blank=True, max_length=50)),
                ('is_recurring', models.BooleanField(default=False)),
                ('period',       models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='expense_records', to='finance.financialperiod',
                )),
                ('source_table', models.CharField(blank=True, max_length=100)),
                ('synced_at',    models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'سجل مصروفات',
                'verbose_name_plural': 'سجلات المصروفات',
                'ordering': ['-expense_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='expenserecord',
            index=models.Index(fields=['expense_date', 'branch'], name='finance_er_date_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='expenserecord',
            index=models.Index(fields=['category'], name='finance_er_category_idx'),
        ),
        migrations.AddIndex(
            model_name='expenserecord',
            index=models.Index(fields=['period'], name='finance_er_period_idx'),
        ),

        # ── FinancialSnapshot ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='FinancialSnapshot',
            fields=[
                ('id',                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period',                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='snapshots', to='finance.financialperiod',
                )),
                ('branch',                models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='financial_snapshots', to='branches.branch',
                )),
                ('gross_revenue',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('returns_value',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_revenue',           models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('cogs',                  models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('gross_profit',          models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('gross_margin_pct',      models.DecimalField(decimal_places=4, default=0, max_digits=8)),
                ('total_purchases',       models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_purchase_returns',models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_purchases',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_expenses',        models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('payroll_expenses',      models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('rent_expenses',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('utility_expenses',      models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('other_expenses',        models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('operating_profit',      models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('ebitda',                models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_profit',            models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_margin_pct',        models.DecimalField(decimal_places=4, default=0, max_digits=8)),
                ('cash_inflow',           models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('cash_outflow',          models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_cash_flow',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_assets',          models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_liabilities',     models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('equity',                models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('working_capital',       models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('inventory_value',       models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_receivables',     models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('total_payables',        models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('current_ratio',         models.DecimalField(decimal_places=4, default=0, max_digits=8)),
                ('quick_ratio',           models.DecimalField(decimal_places=4, default=0, max_digits=8)),
                ('debt_ratio',            models.DecimalField(decimal_places=4, default=0, max_digits=8)),
                ('data_sources',          models.JSONField(default=list)),
                ('is_complete',           models.BooleanField(default=False)),
                ('computed_at',           models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'لقطة مالية',
                'verbose_name_plural': 'اللقطات المالية',
                'ordering': ['-period'],
                'unique_together': {('period', 'branch')},
            },
        ),
        migrations.AddIndex(
            model_name='financialsnapshot',
            index=models.Index(fields=['period', 'branch'], name='finance_fs_period_branch_idx'),
        ),

        # ── FinanceSyncRun ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='FinanceSyncRun',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at',       models.DateTimeField(auto_now_add=True)),
                ('finished_at',      models.DateTimeField(blank=True, null=True)),
                ('status',           models.CharField(
                    choices=[
                        ('pending', 'قيد الانتظار'), ('running', 'جارٍ'),
                        ('success', 'نجح'), ('partial', 'جزئي'), ('failed', 'فشل'),
                    ],
                    default='pending', max_length=20,
                )),
                ('sync_type',        models.CharField(
                    choices=[
                        ('discovery', 'اكتشاف المخطط'), ('full', 'كامل'),
                        ('incremental', 'تدريجي'), ('snapshot', 'لقطة فقط'),
                    ],
                    default='incremental', max_length=20,
                )),
                ('period_start',     models.DateField(blank=True, null=True)),
                ('period_end',       models.DateField(blank=True, null=True)),
                ('records_synced',   models.JSONField(default=dict)),
                ('errors',           models.JSONField(default=list)),
                ('triggered_by',     models.CharField(blank=True, max_length=100)),
                ('notes',            models.TextField(blank=True)),
                ('duration_seconds', models.IntegerField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'تشغيل مزامنة مالية',
                'verbose_name_plural': 'تشغيلات المزامنة المالية',
                'ordering': ['-started_at'],
            },
        ),
    ]
