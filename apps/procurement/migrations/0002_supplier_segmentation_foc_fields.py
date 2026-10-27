"""
apps/procurement/migrations/0002_supplier_segmentation_foc_fields.py

Procurement Intelligence v2:
  - Adds FOC, tax-aware cost, expiry-return, and segmentation fields to PurchaseLine
  - Adds enhanced scoring + FOC/tax stats + category field to SupplierProfile
  - Creates SupplierSegmentation model
  - Extends ALERT_TYPES (choices-only change — no schema impact)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('procurement', '0001_initial'),
    ]

    operations = [

        # ── PurchaseLine new fields ───────────────────────────────────────────

        migrations.AddField(
            model_name='purchaseline',
            name='is_foc',
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name='purchaseline',
            name='foc_type',
            field=models.CharField(max_length=15, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='purchaseline',
            name='vat_value',
            field=models.DecimalField(max_digits=14, decimal_places=3, default=0),
        ),
        migrations.AddField(
            model_name='purchaseline',
            name='effective_cost',
            field=models.DecimalField(max_digits=12, decimal_places=4, default=0),
        ),
        migrations.AddField(
            model_name='purchaseline',
            name='return_type',
            field=models.CharField(max_length=10, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='purchaseline',
            name='supplier_category',
            field=models.CharField(max_length=25, blank=True, default=''),
        ),

        # ── PurchaseLine new indexes ──────────────────────────────────────────

        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['is_foc', 'doc_date'], name='proc_pl_foc_date_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['return_type', 'doc_date'], name='proc_pl_rettype_date_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['supplier_category', 'doc_date'], name='proc_pl_cat_date_idx'),
        ),

        # ── SupplierProfile new fields ────────────────────────────────────────

        migrations.AddField(
            model_name='supplierprofile',
            name='score_effective_cost',
            field=models.DecimalField(max_digits=5, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='score_foc_benefit',
            field=models.DecimalField(max_digits=5, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='score_tax_efficiency',
            field=models.DecimalField(max_digits=5, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='enhanced_total_score',
            field=models.DecimalField(max_digits=5, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='foc_rate_pct',
            field=models.DecimalField(max_digits=7, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='avg_tax_burden_pct',
            field=models.DecimalField(max_digits=7, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='supplier_category',
            field=models.CharField(max_length=25, blank=True, default=''),
        ),

        # ── SupplierSegmentation (new model) ──────────────────────────────────

        migrations.CreateModel(
            name='SupplierSegmentation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('supplier_code',     models.CharField(max_length=10, unique=True, db_index=True)),
                ('supplier_name',     models.CharField(max_length=255, blank=True)),
                ('supplier_category', models.CharField(
                    max_length=25,
                    choices=[
                        ('OFFICIAL_DISTRIBUTOR', 'موزع رسمي'),
                        ('MANUFACTURER',         'مصنع / شركة أدوية'),
                        ('SMALL_WAREHOUSE',      'مستودع صغير'),
                        ('PATIENT_REPURCHASE',   'شراء من مريض / خاص'),
                        ('INTERNAL_TRANSFER',    'تحويل داخلي بين الفروع'),
                        ('SERVICE_VENDOR',       'مورد خدمات'),
                        ('UNKNOWN',              'غير مصنف'),
                    ],
                    default='UNKNOWN',
                    db_index=True,
                )),
                ('persontype',        models.CharField(max_length=20, blank=True)),
                ('persontypeclassif', models.CharField(max_length=20, blank=True)),
                ('ptcode',            models.CharField(max_length=10, blank=True)),
                ('ptclassifcode',     models.CharField(max_length=10, blank=True)),
                ('classified_at',     models.DateTimeField(auto_now=True)),
                ('auto_classified',   models.BooleanField(default=True)),
                ('manual_override',   models.BooleanField(default=False)),
                ('notes',             models.TextField(blank=True)),
                ('purchase_value_365d', models.DecimalField(max_digits=18, decimal_places=2, default=0)),
                ('invoice_count_365d',  models.PositiveIntegerField(default=0)),
                ('foc_rate_pct',        models.DecimalField(max_digits=7, decimal_places=2, default=0)),
                ('return_pct',          models.DecimalField(max_digits=7, decimal_places=2, default=0)),
            ],
            options={
                'verbose_name': 'تصنيف مورد',
                'verbose_name_plural': 'تصنيفات الموردين',
                'ordering': ['supplier_category', 'supplier_code'],
            },
        ),
        migrations.AddIndex(
            model_name='suppliersegmentation',
            index=models.Index(
                fields=['supplier_category', 'purchase_value_365d'],
                name='proc_seg_cat_val_idx',
            ),
        ),
    ]
