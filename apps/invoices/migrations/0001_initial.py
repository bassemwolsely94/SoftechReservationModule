import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('catalog',  '0001_initial'),
        ('users',    '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupplierInvoice',
            fields=[
                ('id',                  models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('status',              models.CharField(choices=[('pending','في الانتظار'),('processing','جاري المعالجة'),('review','قيد المراجعة'),('confirmed','مُأكَّدة'),('rejected','مرفوضة')], default='pending', max_length=20, verbose_name='الحالة')),
                ('supplier_name',       models.CharField(blank=True, max_length=200, verbose_name='اسم المورد')),
                ('invoice_number',      models.CharField(blank=True, max_length=50, verbose_name='رقم الفاتورة')),
                ('invoice_date',        models.DateField(blank=True, null=True, verbose_name='تاريخ الفاتورة')),
                ('currency',            models.CharField(default='EGP', max_length=10, verbose_name='العملة')),
                ('global_discount_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='خصم عام %')),
                ('global_discount_amt', models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='خصم عام بمبلغ')),
                ('source_image',        models.ImageField(blank=True, null=True, upload_to='invoice_images/', verbose_name='صورة الفاتورة')),
                ('raw_ocr_text',        models.TextField(blank=True, verbose_name='نص OCR الخام')),
                ('notes',               models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at',          models.DateTimeField(auto_now_add=True)),
                ('updated_at',          models.DateTimeField(auto_now=True)),
                ('branch',              models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='branches.branch', verbose_name='الفرع')),
                ('created_by',          models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoices', to='users.staffprofile', verbose_name='أُنشئت بواسطة')),
            ],
            options={'verbose_name': 'فاتورة مورد', 'verbose_name_plural': 'فواتير الموردين', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='InvoiceLine',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('raw_text',     models.CharField(blank=True, max_length=500, verbose_name='النص الخام')),
                ('manual_name',  models.CharField(blank=True, max_length=300, verbose_name='اسم يدوي')),
                ('quantity',     models.DecimalField(decimal_places=3, default=1, max_digits=10, verbose_name='الكمية')),
                ('unit_price',   models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='سعر الوحدة')),
                ('discount_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='خصم السطر %')),
                ('discount_amt', models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='خصم السطر بمبلغ')),
                ('line_total',   models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name='الإجمالي')),
                ('match_score',  models.FloatField(blank=True, null=True, verbose_name='نسبة التطابق')),
                ('is_confirmed', models.BooleanField(default=False, verbose_name='مُأكَّد')),
                ('notes',        models.CharField(blank=True, max_length=300, verbose_name='ملاحظات')),
                ('order',        models.PositiveSmallIntegerField(default=0)),
                ('invoice',      models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='invoices.supplierinvoice', verbose_name='الفاتورة')),
                ('item',         models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='catalog.item', verbose_name='الصنف المطابق')),
            ],
            options={'verbose_name': 'سطر فاتورة', 'verbose_name_plural': 'سطور الفواتير', 'ordering': ['order', 'id']},
        ),
    ]
