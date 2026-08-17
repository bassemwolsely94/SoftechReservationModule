from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog',  '0001_initial'),
        ('branches', '0001_initial'),
        # VendorProfile (referenced by StockBatch.vendor below) is created in
        # invoices 0003 — depend on it so a fresh migration graph resolves the FK.
        ('invoices', '0003_vendorprofile_vendoritemmapping_vendor_fk'),
        ('users',    '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('batch_number',   models.CharField(max_length=100, verbose_name='رقم التشغيلة')),
                ('expiry_date',    models.DateField(db_index=True, verbose_name='تاريخ الصلاحية')),
                ('invoice_number', models.CharField(blank=True, max_length=50, verbose_name='رقم الفاتورة')),
                ('manufacturer',   models.CharField(blank=True, max_length=200, verbose_name='المصنّع')),
                ('purchase_price', models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name='سعر الشراء (للوحدة)')),
                ('original_qty',   models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name='الكمية الأصلية')),
                ('current_qty',    models.DecimalField(db_index=True, decimal_places=3, default=0, max_digits=12, verbose_name='الكمية الحالية')),
                ('storage_condition', models.CharField(
                    choices=[('ambient', 'درجة حرارة الغرفة'), ('fridge', 'مبرّد (2–8°C)'), ('freezer', 'مجمّد')],
                    default='ambient', max_length=10, verbose_name='شرط التخزين',
                )),
                ('is_quarantined',    models.BooleanField(db_index=True, default=False, verbose_name='معزولة')),
                ('quarantine_reason', models.TextField(blank=True, verbose_name='سبب العزل')),
                ('is_expired',        models.BooleanField(db_index=True, default=False, verbose_name='منتهية الصلاحية')),
                ('received_at',       models.DateTimeField(default=django.utils.timezone.now, verbose_name='تاريخ الاستلام')),
                ('created_at',        models.DateTimeField(auto_now_add=True)),
                ('updated_at',        models.DateTimeField(auto_now=True)),
                ('item',    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='batches',   to='catalog.item',    verbose_name='الصنف')),
                ('branch',  models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='batches',   to='branches.branch', verbose_name='الفرع')),
                ('vendor',  models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='batches',   to='invoices.vendorprofile',  verbose_name='المورد')),
                ('invoice', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='batches',   to='invoices.supplierinvoice', verbose_name='فاتورة الاستلام')),
                ('received_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='received_batches', to='users.staffprofile', verbose_name='استلم بواسطة')),
            ],
            options={
                'verbose_name': 'دفعة مخزون',
                'verbose_name_plural': 'دفعات المخزون',
                'ordering': ['expiry_date', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='stockbatch',
            constraint=models.UniqueConstraint(fields=['item', 'branch', 'batch_number'], name='batch_unique_item_branch_lot'),
        ),
        migrations.AddIndex(
            model_name='stockbatch',
            index=models.Index(fields=['item', 'branch', 'expiry_date'], name='batch_fefo_idx'),
        ),
        migrations.AddIndex(
            model_name='stockbatch',
            index=models.Index(fields=['expiry_date', 'is_quarantined', 'is_expired'], name='batch_expiry_filter_idx'),
        ),
        migrations.AddIndex(
            model_name='stockbatch',
            index=models.Index(fields=['vendor', 'expiry_date'], name='batch_vendor_expiry_idx'),
        ),
        migrations.CreateModel(
            name='BatchMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_type', models.CharField(
                    choices=[
                        ('receive', 'استلام من مورد'), ('transfer_out', 'تحويل صادر'),
                        ('transfer_in', 'تحويل وارد'), ('sale', 'بيع'),
                        ('return_in', 'مرتجع من عميل'), ('return_out', 'مرتجع لمورد'),
                        ('adjustment', 'تسوية يدوية'), ('stockcount', 'تصحيح جرد'),
                        ('quarantine', 'تحويل لعزل'), ('destroy', 'إتلاف'),
                    ],
                    db_index=True, max_length=15, verbose_name='نوع الحركة',
                )),
                ('qty_change',    models.DecimalField(decimal_places=3, max_digits=12, verbose_name='تغيير الكمية')),
                ('qty_after',     models.DecimalField(decimal_places=3, max_digits=12, verbose_name='الكمية بعد الحركة')),
                ('reference_type', models.CharField(blank=True, max_length=50, verbose_name='نوع المرجع')),
                ('reference_id',   models.PositiveIntegerField(blank=True, null=True, verbose_name='رقم المرجع')),
                ('notes',         models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at',    models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت الحركة')),
                ('batch',        models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='movements',       to='batches.stockbatch',  verbose_name='الدفعة')),
                ('branch',       models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='batch_movements', to='branches.branch',     verbose_name='الفرع')),
                ('performed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='batch_movements', to='users.staffprofile', verbose_name='بواسطة')),
            ],
            options={
                'verbose_name': 'حركة دفعة',
                'verbose_name_plural': 'حركات الدفعات',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='batchmovement',
            index=models.Index(fields=['batch', 'created_at'], name='batchmov_batch_time_idx'),
        ),
        migrations.AddIndex(
            model_name='batchmovement',
            index=models.Index(fields=['movement_type', 'created_at'], name='batchmov_type_time_idx'),
        ),
        migrations.AddIndex(
            model_name='batchmovement',
            index=models.Index(fields=['reference_type', 'reference_id'], name='batchmov_ref_idx'),
        ),
        migrations.CreateModel(
            name='NearExpiryAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('threshold_days', models.PositiveSmallIntegerField(
                    choices=[(30, '< 30 يوماً — خطر'), (60, '30–60 يوماً — تحذير'), (90, '60–90 يوماً — تنبيه'), (180, '90–180 يوماً — مراقبة')],
                    db_index=True, verbose_name='عتبة التنبيه (أيام)',
                )),
                ('alerted_at',  models.DateTimeField(auto_now_add=True, verbose_name='وقت التنبيه')),
                ('resolved_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الحل')),
                ('resolution',  models.CharField(blank=True, max_length=30, verbose_name='طريقة الحل')),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expiry_alerts', to='batches.stockbatch', verbose_name='الدفعة')),
            ],
            options={
                'verbose_name': 'تنبيه انتهاء صلاحية',
                'verbose_name_plural': 'تنبيهات انتهاء الصلاحية',
                'ordering': ['batch__expiry_date'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='nearexpiryalert',
            unique_together={('batch', 'threshold_days')},
        ),
    ]
