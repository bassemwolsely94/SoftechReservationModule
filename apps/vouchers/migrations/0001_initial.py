import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches',  '0001_initial'),
        ('catalog',   '0001_initial'),
        ('customers', '0001_initial'),
        ('users',     '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Voucher',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('code',            models.CharField(db_index=True, max_length=30, unique=True, verbose_name='كود القسيمة')),
                ('title',           models.CharField(max_length=200, verbose_name='العنوان')),
                ('description',     models.TextField(blank=True, verbose_name='الوصف')),
                ('voucher_type',    models.CharField(choices=[('discount_pct','خصم بالنسبة المئوية'),('discount_fixed','خصم بمبلغ ثابت'),('credit','رصيد نقدي'),('free_item','صنف مجاني')], max_length=20, verbose_name='النوع')),
                ('discount_pct',    models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='نسبة الخصم %')),
                ('discount_amount', models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='مبلغ الخصم')),
                ('credit_amount',   models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='قيمة الرصيد')),
                ('valid_from',      models.DateField(verbose_name='صالح من')),
                ('valid_until',     models.DateField(blank=True, null=True, verbose_name='صالح حتى')),
                ('max_uses',        models.PositiveSmallIntegerField(default=1, verbose_name='الحد الأقصى للاستخدام')),
                ('times_used',      models.PositiveSmallIntegerField(default=0, verbose_name='مرات الاستخدام')),
                ('status',          models.CharField(choices=[('active','نشط'),('used','مُستخدَم'),('expired','منتهي'),('cancelled','ملغى')], default='active', max_length=15, verbose_name='الحالة')),
                ('notes',           models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at',      models.DateTimeField(auto_now_add=True)),
                ('updated_at',      models.DateTimeField(auto_now=True)),
                ('branch',          models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers', to='branches.branch', verbose_name='الفرع (تقييد)')),
                ('created_by',      models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers_created', to='users.staffprofile', verbose_name='أُنشئت بواسطة')),
                ('customer',        models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers', to='customers.customer', verbose_name='العميل')),
                ('free_item',       models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='catalog.item', verbose_name='الصنف المجاني')),
            ],
            options={'verbose_name': 'قسيمة', 'verbose_name_plural': 'قسائم', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='VoucherOTP',
            fields=[
                ('id',         models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('phone',      models.CharField(max_length=20, verbose_name='رقم الهاتف')),
                ('code_hash',  models.CharField(max_length=64, verbose_name='هاش الرمز')),
                ('is_used',    models.BooleanField(default=False, verbose_name='مُستخدَم')),
                ('expires_at', models.DateTimeField(verbose_name='ينتهي في')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('used_at',    models.DateTimeField(blank=True, null=True)),
                ('sent_via',   models.CharField(default='whatsapp', max_length=20, verbose_name='أُرسل عبر')),
                ('voucher',    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='otps', to='vouchers.voucher', verbose_name='القسيمة')),
            ],
            options={'verbose_name': 'رمز OTP', 'verbose_name_plural': 'رموز OTP', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='VoucherRedemption',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('redeemed_at', models.DateTimeField(auto_now_add=True)),
                ('notes',       models.CharField(blank=True, max_length=300)),
                ('branch',      models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='branches.branch')),
                ('otp',         models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='vouchers.voucherotp')),
                ('redeemed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='users.staffprofile')),
                ('voucher',     models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='redemptions', to='vouchers.voucher')),
            ],
            options={'ordering': ['-redeemed_at']},
        ),
    ]
