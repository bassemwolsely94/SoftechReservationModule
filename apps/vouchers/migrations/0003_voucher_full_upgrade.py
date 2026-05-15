"""
Migration 0003 — Full voucher system upgrade.

Additive only — no column drops, no renames. Safe on live data.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('branches',  '0001_initial'),
        ('catalog',   '0001_initial'),
        ('customers', '0001_initial'),
        ('users',     '0001_initial'),
        ('vouchers',  '0002_alter_voucher_id_alter_voucherotp_id_and_more'),
    ]

    operations = [

        # ── Voucher: new scalar fields ────────────────────────────────────────
        migrations.AddField(
            model_name='voucher',
            name='voucher_category',
            field=models.CharField(
                choices=[('public','عام — لأي عميل'),('private','خاص — عميل محدد'),
                         ('first_time','أول مرة'),('assigned','مخصص بالهاتف')],
                default='public', max_length=15, verbose_name='فئة التوزيع',
            ),
        ),
        migrations.AddField(
            model_name='voucher',
            name='max_discount_cap',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=10,
                                       null=True, verbose_name='الحد الأقصى للخصم (ج.م)'),
        ),
        migrations.AddField(
            model_name='voucher',
            name='min_order_value',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=10,
                                       null=True, verbose_name='الحد الأدنى للطلب (ج.م)'),
        ),
        migrations.AddField(
            model_name='voucher',
            name='usage_limit_per_customer',
            field=models.PositiveSmallIntegerField(default=1,
                                                    verbose_name='حد الاستخدام للعميل الواحد'),
        ),
        migrations.AddField(
            model_name='voucher',
            name='usage_limit_per_day',
            field=models.PositiveSmallIntegerField(blank=True, null=True,
                                                    verbose_name='حد الاستخدام في اليوم'),
        ),
        migrations.AddField(
            model_name='voucher',
            name='validity_days_after_assignment',
            field=models.PositiveSmallIntegerField(blank=True, null=True,
                                                    verbose_name='صلاحية بعد التخصيص (أيام)'),
        ),
        migrations.AlterField(
            model_name='voucher',
            name='times_used',
            field=models.PositiveIntegerField(default=0, verbose_name='مرات الاستخدام'),
        ),

        # ── Voucher: M2M fields ───────────────────────────────────────────────
        migrations.AddField(
            model_name='voucher',
            name='applicable_items',
            field=models.ManyToManyField(blank=True, related_name='vouchers',
                                          to='catalog.item',
                                          verbose_name='الأصناف المؤهلة'),
        ),
        migrations.AddField(
            model_name='voucher',
            name='applicable_branches',
            field=models.ManyToManyField(blank=True, related_name='applicable_vouchers',
                                          to='branches.branch',
                                          verbose_name='الفروع المؤهلة'),
        ),

        # ── VoucherOTP: new fields ────────────────────────────────────────────
        migrations.AddField(
            model_name='voucherotp',
            name='otp_salt',
            field=models.CharField(default='', max_length=32, verbose_name='الملح'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='voucherotp',
            name='retry_count',
            field=models.PositiveSmallIntegerField(default=0,
                                                    verbose_name='عدد المحاولات'),
        ),
        migrations.AddField(
            model_name='voucherotp',
            name='resend_count',
            field=models.PositiveSmallIntegerField(default=0,
                                                    verbose_name='عدد إعادة الإرسال'),
        ),

        # ── VoucherAssignment: new model ──────────────────────────────────────
        migrations.CreateModel(
            name='VoucherAssignment',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True,
                                                        serialize=False, verbose_name='ID')),
                ('customer_phone', models.CharField(db_index=True, max_length=20,
                                                     verbose_name='هاتف العميل')),
                ('assigned_at',    models.DateTimeField(auto_now_add=True)),
                ('expires_at',     models.DateTimeField(blank=True, null=True,
                                                         verbose_name='ينتهي في')),
                ('usage_count',    models.PositiveSmallIntegerField(default=0,
                                                                      verbose_name='مرات الاستخدام')),
                ('is_active',      models.BooleanField(default=True, verbose_name='نشط')),
                ('assigned_by',    models.ForeignKey(null=True,
                                                      on_delete=django.db.models.deletion.SET_NULL,
                                                      related_name='voucher_assignments',
                                                      to='users.staffprofile',
                                                      verbose_name='خُصِّصت بواسطة')),
                ('customer',       models.ForeignKey(blank=True, null=True,
                                                      on_delete=django.db.models.deletion.SET_NULL,
                                                      related_name='voucher_assignments',
                                                      to='customers.customer',
                                                      verbose_name='العميل')),
                ('voucher',        models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                      related_name='assignments',
                                                      to='vouchers.voucher',
                                                      verbose_name='القسيمة')),
            ],
            options={
                'verbose_name':        'تخصيص قسيمة',
                'verbose_name_plural': 'تخصيصات القسائم',
                'ordering':            ['-assigned_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='voucherassignment',
            constraint=models.UniqueConstraint(
                fields=['voucher', 'customer_phone'],
                name='unique_voucher_phone_assignment',
            ),
        ),

        # ── VoucherRedemptionDocument: new model ──────────────────────────────
        migrations.CreateModel(
            name='VoucherRedemptionDocument',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True,
                                                          serialize=False, verbose_name='ID')),
                ('customer_phone',   models.CharField(db_index=True, max_length=20,
                                                       verbose_name='هاتف العميل')),
                ('generated_at',     models.DateTimeField(auto_now_add=True)),
                ('expires_at',       models.DateTimeField(verbose_name='ينتهي في')),
                ('status',           models.CharField(
                    choices=[('active','نشط'),('used','مُستخدَم'),
                             ('expired','منتهي'),('cancelled','ملغى')],
                    default='active', max_length=15, verbose_name='الحالة')),
                ('reference_code',   models.CharField(db_index=True, max_length=20,
                                                       unique=True,
                                                       verbose_name='كود المرجع (POS)')),
                ('discount_applied', models.DecimalField(blank=True, decimal_places=3,
                                                          max_digits=10, null=True,
                                                          verbose_name='الخصم المحسوب')),
                ('order_amount',     models.DecimalField(blank=True, decimal_places=3,
                                                          max_digits=10, null=True,
                                                          verbose_name='قيمة الطلب')),
                ('used_at',          models.DateTimeField(blank=True, null=True)),
                ('notes',            models.CharField(blank=True, max_length=300)),
                ('branch',           models.ForeignKey(null=True,
                                                        on_delete=django.db.models.deletion.SET_NULL,
                                                        related_name='voucher_documents',
                                                        to='branches.branch',
                                                        verbose_name='الفرع')),
                ('employee',         models.ForeignKey(null=True,
                                                        on_delete=django.db.models.deletion.SET_NULL,
                                                        related_name='voucher_documents',
                                                        to='users.staffprofile',
                                                        verbose_name='الموظف')),
                ('otp',              models.OneToOneField(blank=True, null=True,
                                                           on_delete=django.db.models.deletion.SET_NULL,
                                                           related_name='document',
                                                           to='vouchers.voucherotp',
                                                           verbose_name='OTP المرتبط')),
                ('voucher',          models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                        related_name='documents',
                                                        to='vouchers.voucher',
                                                        verbose_name='القسيمة')),
            ],
            options={
                'verbose_name':        'وثيقة استرداد',
                'verbose_name_plural': 'وثائق الاسترداد',
                'ordering':            ['-generated_at'],
            },
        ),

        # ── VoucherRedemption: new fields ─────────────────────────────────────
        migrations.AddField(
            model_name='voucherredemption',
            name='document',
            field=models.OneToOneField(blank=True, null=True,
                                        on_delete=django.db.models.deletion.SET_NULL,
                                        related_name='redemption',
                                        to='vouchers.voucherredemptiondocument'),
        ),
        migrations.AddField(
            model_name='voucherredemption',
            name='customer_phone',
            field=models.CharField(db_index=True, default='', max_length=20),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='voucherredemption',
            name='discount_applied',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='voucherredemption',
            name='order_amount',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=10),
        ),
    ]
