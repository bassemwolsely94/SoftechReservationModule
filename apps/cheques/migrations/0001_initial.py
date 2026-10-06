"""
apps/cheques/migrations/0001_initial.py
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='EgyptianHoliday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True, unique=True, verbose_name='التاريخ')),
                ('name_ar', models.CharField(max_length=200, verbose_name='الاسم')),
                ('name_en', models.CharField(blank=True, max_length=200, verbose_name='Name')),
                ('holiday_type', models.CharField(
                    choices=[('national', 'عيد وطني'), ('islamic', 'عيد إسلامي'), ('adhoc', 'إغلاق استثنائي')],
                    default='national', max_length=10, verbose_name='النوع',
                )),
                ('is_annual', models.BooleanField(
                    default=False,
                    help_text='إذا كان True، يتكرر كل عام في نفس الشهر واليوم',
                    verbose_name='سنوي',
                )),
            ],
            options={
                'verbose_name': 'إجازة مصرية',
                'verbose_name_plural': 'الإجازات المصرية',
                'ordering': ['date'],
            },
        ),
        migrations.CreateModel(
            name='ChequePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='عنوان الخطة')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('status', models.CharField(
                    choices=[('draft', 'مسودة'), ('active', 'نشطة'), ('completed', 'مكتملة'), ('cancelled', 'ملغاة')],
                    db_index=True, default='draft', max_length=10, verbose_name='الحالة',
                )),
                ('payee_name', models.CharField(max_length=255, verbose_name='اسم المستفيد')),
                ('bank_name', models.CharField(blank=True, max_length=100, verbose_name='البنك')),
                ('account_number', models.CharField(blank=True, max_length=50, verbose_name='رقم الحساب')),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=14, verbose_name='إجمالي المبلغ')),
                ('reference_doc', models.CharField(
                    blank=True, max_length=100,
                    verbose_name='رقم المستند المرجعي',
                    help_text='رقم الفاتورة أو أمر الشراء',
                )),
                ('cheque_count', models.PositiveSmallIntegerField(default=1, verbose_name='عدد الشيكات')),
                ('first_due_date', models.DateField(verbose_name='تاريخ الشيك الأول')),
                ('interval_value', models.PositiveSmallIntegerField(default=1, verbose_name='فترة التكرار')),
                ('interval_unit', models.CharField(
                    choices=[('days', 'أيام'), ('weeks', 'أسابيع'), ('months', 'أشهر')],
                    default='months', max_length=6, verbose_name='وحدة التكرار',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cheque_plans',
                    to='branches.branch',
                    verbose_name='الفرع',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cheque_plans_created',
                    to='users.staffprofile',
                    verbose_name='أنشئ بواسطة',
                )),
            ],
            options={
                'verbose_name': 'خطة شيكات',
                'verbose_name_plural': 'خطط الشيكات',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ChequeInstalment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('instalment_no', models.PositiveSmallIntegerField(verbose_name='رقم الشيك')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, verbose_name='المبلغ')),
                ('nominal_date', models.DateField(
                    help_text='التاريخ قبل تعديل الإجازات', verbose_name='التاريخ الاسمي',
                )),
                ('due_date', models.DateField(
                    db_index=True,
                    help_text='أول يوم عمل مصرفي ≥ التاريخ الاسمي',
                    verbose_name='تاريخ الاستحقاق',
                )),
                ('cheque_number', models.CharField(blank=True, max_length=50, verbose_name='رقم الشيك')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'لم يُصدَر'),
                        ('issued', 'صادر'),
                        ('presented', 'مُقدَّم للبنك'),
                        ('cleared', 'تمّ الصرف'),
                        ('bounced', 'ارتدّ / رُفض'),
                        ('cancelled', 'ملغي'),
                    ],
                    db_index=True, default='pending', max_length=10, verbose_name='الحالة',
                )),
                ('issued_at', models.DateField(blank=True, null=True, verbose_name='تاريخ الإصدار')),
                ('cleared_at', models.DateField(blank=True, null=True, verbose_name='تاريخ الصرف')),
                ('notes', models.CharField(blank=True, max_length=500, verbose_name='ملاحظات')),
                ('plan', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='instalments',
                    to='cheques.chequeplan',
                    verbose_name='الخطة',
                )),
            ],
            options={
                'verbose_name': 'شيك',
                'verbose_name_plural': 'شيكات',
                'ordering': ['instalment_no'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='chequeinstalment',
            unique_together={('plan', 'instalment_no')},
        ),
        migrations.AddIndex(
            model_name='chequeinstalment',
            index=models.Index(fields=['plan', 'status'], name='cheques_ins_plan_s_idx'),
        ),
        migrations.AddIndex(
            model_name='chequeinstalment',
            index=models.Index(fields=['due_date', 'status'], name='cheques_ins_due_s_idx'),
        ),
    ]
