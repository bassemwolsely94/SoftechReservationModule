"""
apps/payments/migrations/0001_initial.py
"""
import datetime

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('customers', '0007_pic_as_unique_key'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── ExternalPayment ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='ExternalPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_invoice_code', models.CharField(blank=True, db_index=True, max_length=100, verbose_name='كود فاتورة SOFTECH')),
                ('softech_doc_number', models.CharField(blank=True, max_length=100, verbose_name='رقم مستند SOFTECH')),
                ('customer_name', models.CharField(blank=True, max_length=255, verbose_name='اسم العميل')),
                ('customer_phone', models.CharField(blank=True, max_length=50, verbose_name='هاتف العميل')),
                ('method', models.CharField(
                    choices=[
                        ('cash', 'كاش'),
                        ('instapay', 'إنستاباي'),
                        ('vodafone_cash', 'فودافون كاش'),
                        ('bank_transfer', 'تحويل بنكي'),
                        ('other', 'أخرى'),
                    ],
                    max_length=20, verbose_name='طريقة الدفع',
                )),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='المبلغ المدفوع')),
                ('invoice_total', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='إجمالي الفاتورة')),
                ('is_partial', models.BooleanField(default=False, verbose_name='دفع جزئي')),
                ('remaining_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='المبلغ المتبقي')),
                ('reference_number', models.CharField(blank=True, db_index=True, max_length=200, verbose_name='رقم المرجع / رقم التحويل')),
                ('screenshot', models.ImageField(blank=True, null=True, upload_to='payments/screenshots/', verbose_name='صورة الإيصال')),
                ('payment_date', models.DateField(default=datetime.date.today, verbose_name='تاريخ الدفع')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'انتظار'),
                        ('confirmed', 'مؤكد'),
                        ('reconciled', 'مُسوَّى'),
                        ('disputed', 'متنازع عليه'),
                        ('cancelled', 'ملغى'),
                    ],
                    db_index=True, default='pending', max_length=15, verbose_name='الحالة',
                )),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('confirmed_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت التأكيد')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_payments',
                    to='branches.branch',
                    verbose_name='الفرع',
                )),
                ('customer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='external_payments',
                    to='customers.customer',
                    verbose_name='العميل',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_payments',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشأ بواسطة',
                )),
                ('confirmed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='confirmed_payments',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أكد بواسطة',
                )),
            ],
            options={
                'verbose_name': 'دفعة خارجية',
                'verbose_name_plural': 'الدفعات الخارجية',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='externalpayment',
            index=models.Index(fields=['method'], name='pay_method'),
        ),
        migrations.AddIndex(
            model_name='externalpayment',
            index=models.Index(fields=['status'], name='pay_status'),
        ),
        migrations.AddIndex(
            model_name='externalpayment',
            index=models.Index(fields=['payment_date'], name='pay_payment_date'),
        ),
        migrations.AddIndex(
            model_name='externalpayment',
            index=models.Index(fields=['branch'], name='pay_branch'),
        ),
        migrations.AddIndex(
            model_name='externalpayment',
            index=models.Index(fields=['payment_date', 'branch'], name='pay_date_branch'),
        ),

        # ── PaymentReconciliationLog ──────────────────────────────────────────
        migrations.CreateModel(
            name='PaymentReconciliationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(
                    help_text='confirmed / disputed / reconciled / note_added',
                    max_length=50, verbose_name='الإجراء',
                )),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('variance', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='الفارق')),
                ('performed_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت الإجراء')),
                ('payment', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reconciliation_logs',
                    to='payments.externalpayment',
                    verbose_name='الدفعة',
                )),
                ('performed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='بواسطة',
                )),
            ],
            options={
                'verbose_name': 'سجل تسوية دفعة',
                'verbose_name_plural': 'سجلات تسوية الدفعات',
                'ordering': ['performed_at'],
            },
        ),
    ]
