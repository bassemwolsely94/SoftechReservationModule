from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='IncentiveProgram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='اسم البرنامج')),
                ('description', models.TextField(blank=True, verbose_name='الوصف')),
                ('start_date', models.DateField(verbose_name='تاريخ البداية')),
                ('end_date', models.DateField(verbose_name='تاريخ النهاية')),
                ('calculation_period', models.CharField(
                    choices=[('weekly', 'أسبوعي'), ('monthly', 'شهري'), ('custom', 'مخصص')],
                    default='monthly', max_length=10, verbose_name='دورة الاحتساب',
                )),
                ('is_active', models.BooleanField(default=True, verbose_name='نشط')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='incentive_programs',
                    to='users.staffprofile',
                    verbose_name='أُنشئ بواسطة',
                )),
            ],
            options={
                'verbose_name': 'برنامج حوافز',
                'verbose_name_plural': 'برامج الحوافز',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='IncentiveRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rule_name', models.CharField(blank=True, max_length=200, verbose_name='اسم القاعدة')),
                ('item_code', models.CharField(blank=True, max_length=50, verbose_name='كود الصنف',
                                               help_text='اتركه فارغاً للتطبيق على فئة كاملة')),
                ('item_name', models.CharField(blank=True, max_length=300, verbose_name='اسم الصنف (للعرض)')),
                ('category_code', models.CharField(blank=True, max_length=50, verbose_name='كود الفئة (groupcode)',
                                                   help_text='يُطبَّق على كل أصناف هذه الفئة إن لم يُحدَّد كود صنف بعينه')),
                ('incentive_type', models.CharField(
                    choices=[('percent', 'نسبة مئوية %'), ('fixed', 'مبلغ ثابت / وحدة')],
                    default='percent', max_length=10, verbose_name='نوع الحافز',
                )),
                ('incentive_value', models.DecimalField(decimal_places=4, max_digits=10,
                                                        verbose_name='قيمة الحافز')),
                ('min_qty', models.DecimalField(decimal_places=3, default=Decimal('0'),
                                                max_digits=10, verbose_name='الحد الأدنى للكمية')),
                ('person_code_filter', models.CharField(blank=True, max_length=50,
                                                        verbose_name='فلتر كود المندوب (phcode)')),
                ('expiry_within_days', models.PositiveIntegerField(blank=True, null=True,
                                                                   verbose_name='أيام الصلاحية')),
                ('priority', models.PositiveIntegerField(default=0, verbose_name='الأولوية')),
                ('is_active', models.BooleanField(default=True, verbose_name='نشطة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('program', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='rules',
                    to='incentives.incentiveprogram',
                    verbose_name='البرنامج',
                )),
            ],
            options={
                'verbose_name': 'قاعدة حوافز',
                'verbose_name_plural': 'قواعد الحوافز',
                'ordering': ['-priority', 'item_code'],
            },
        ),
        migrations.CreateModel(
            name='IncentiveTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_code', models.CharField(db_index=True, max_length=50, verbose_name='كود الصنف')),
                ('item_name', models.CharField(blank=True, max_length=300, verbose_name='اسم الصنف')),
                ('doc_no', models.CharField(db_index=True, max_length=50, verbose_name='رقم الفاتورة')),
                ('doc_type', models.CharField(
                    choices=[('sale', 'بيع'), ('return', 'مرتجع')],
                    default='sale', max_length=10, verbose_name='نوع الحركة',
                )),
                ('ref_doc_no', models.CharField(blank=True, db_index=True, max_length=50,
                                                verbose_name='الفاتورة المرجعية')),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=12, verbose_name='الكمية')),
                ('unit_price', models.DecimalField(decimal_places=4, max_digits=12, verbose_name='سعر الوحدة')),
                ('incentive_amount', models.DecimalField(decimal_places=4, default=Decimal('0'),
                                                         max_digits=12, verbose_name='مبلغ الحافز')),
                ('is_reversed', models.BooleanField(db_index=True, default=False, verbose_name='مُعكوس')),
                ('period_start', models.DateField(verbose_name='بداية الفترة')),
                ('period_end', models.DateField(verbose_name='نهاية الفترة')),
                ('erp_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الحركة')),
                ('branch_code', models.CharField(blank=True, max_length=20, verbose_name='كود الفرع')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('program', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='transactions',
                    to='incentives.incentiveprogram',
                    verbose_name='البرنامج',
                )),
                ('rule', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transactions',
                    to='incentives.incentiverule',
                    verbose_name='القاعدة المطبقة',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='incentive_transactions',
                    to='users.staffprofile',
                    verbose_name='المندوب',
                )),
            ],
            options={
                'verbose_name': 'حركة حافز',
                'verbose_name_plural': 'حركات الحوافز',
                'ordering': ['-erp_date', 'doc_no'],
            },
        ),
        migrations.AddIndex(
            model_name='incentivetransaction',
            index=models.Index(fields=['program', 'period_start', 'period_end'],
                               name='incv_prog_period_idx'),
        ),
        migrations.AddIndex(
            model_name='incentivetransaction',
            index=models.Index(fields=['user', 'period_start'],
                               name='incv_user_period_idx'),
        ),
        migrations.AddIndex(
            model_name='incentivetransaction',
            index=models.Index(fields=['doc_no', 'item_code'],
                               name='incv_doc_item_idx'),
        ),
        migrations.CreateModel(
            name='IncentiveSettlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField(verbose_name='بداية الفترة')),
                ('period_end', models.DateField(verbose_name='نهاية الفترة')),
                ('total_incentive', models.DecimalField(decimal_places=4, default=Decimal('0'),
                                                        max_digits=14, verbose_name='إجمالي الحوافز')),
                ('transaction_count', models.PositiveIntegerField(default=0, verbose_name='عدد الحركات')),
                ('is_finalized', models.BooleanField(db_index=True, default=False, verbose_name='مُعتمد')),
                ('finalized_at', models.DateTimeField(blank=True, null=True, verbose_name='تاريخ الاعتماد')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('finalized_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='finalized_settlements',
                    to='users.staffprofile',
                    verbose_name='اعتمد بواسطة',
                )),
                ('program', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='settlements',
                    to='incentives.incentiveprogram',
                    verbose_name='البرنامج',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='incentive_settlements',
                    to='users.staffprofile',
                    verbose_name='المندوب',
                )),
            ],
            options={
                'verbose_name': 'تسوية حوافز',
                'verbose_name_plural': 'تسويات الحوافز',
                'ordering': ['-period_end', 'user'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='incentivesettlement',
            unique_together={('program', 'user', 'period_start', 'period_end')},
        ),
    ]
