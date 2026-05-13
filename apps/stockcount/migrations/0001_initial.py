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
            name='StockCountSession',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status',         models.CharField(choices=[('open','قيد الجرد'),('completed','مكتمل'),('cancelled','ملغى')], default='open', max_length=15, verbose_name='الحالة')),
                ('notes',          models.TextField(blank=True, verbose_name='ملاحظات')),
                ('erp_doc_code',   models.CharField(blank=True, max_length=10, verbose_name='كود المستند ERP')),
                ('erp_doc_number', models.CharField(blank=True, max_length=20, verbose_name='رقم المستند ERP')),
                ('count_date',     models.DateField(verbose_name='تاريخ الجرد')),
                ('created_at',     models.DateTimeField(auto_now_add=True)),
                ('completed_at',   models.DateTimeField(null=True, blank=True)),
                ('branch',         models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_counts', to='branches.branch', verbose_name='الفرع')),
                ('created_by',     models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stock_counts', to='users.staffprofile', verbose_name='أُنشئت بواسطة')),
            ],
            options={'verbose_name': 'جلسة جرد', 'verbose_name_plural': 'جلسات الجرد', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='StockCountLine',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('manual_item_name', models.CharField(blank=True, max_length=200, verbose_name='اسم الصنف (يدوي)')),
                ('system_qty',       models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='كمية النظام')),
                ('counted_qty',      models.DecimalField(decimal_places=3, max_digits=10, null=True, blank=True, verbose_name='الكمية المعدودة')),
                ('difference',       models.DecimalField(decimal_places=3, max_digits=10, null=True, blank=True, verbose_name='الفرق')),
                ('has_discrepancy',  models.BooleanField(default=False, verbose_name='يوجد فرق')),
                ('erp_transqty',     models.DecimalField(decimal_places=3, max_digits=10, null=True, blank=True, verbose_name='كمية ERP')),
                ('notes',            models.CharField(blank=True, max_length=300, verbose_name='ملاحظات السطر')),
                ('updated_at',       models.DateTimeField(auto_now=True)),
                ('session',          models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='stockcount.stockcountsession', verbose_name='جلسة الجرد')),
                ('item',             models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='catalog.item', verbose_name='الصنف')),
            ],
            options={'verbose_name': 'سطر جرد', 'verbose_name_plural': 'سطور الجرد', 'ordering': ['item__name']},
        ),
    ]
