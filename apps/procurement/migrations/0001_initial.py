"""
apps/procurement/migrations/0001_initial.py

Initial migration for the Procurement Intelligence Platform.
Creates all 7 models.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0001_initial'),
        ('branches', '0001_initial'),
    ]

    operations = [
        # ── ProcurementEngineRun ──────────────────────────────────────────────
        migrations.CreateModel(
            name='ProcurementEngineRun',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True)),
                ('started_at',       models.DateTimeField(auto_now_add=True)),
                ('finished_at',      models.DateTimeField(blank=True, null=True)),
                ('status',           models.CharField(
                    choices=[('running', 'يعمل'), ('success', 'ناجح'), ('failed', 'فشل')],
                    default='running', max_length=10)),
                ('period_days',      models.PositiveIntegerField(default=365)),
                ('lines_synced',     models.PositiveIntegerField(default=0)),
                ('lines_upserted',   models.PositiveIntegerField(default=0)),
                ('suppliers_updated', models.PositiveIntegerField(default=0)),
                ('mappings_updated', models.PositiveIntegerField(default=0)),
                ('alerts_generated', models.PositiveIntegerField(default=0)),
                ('error_message',    models.TextField(blank=True)),
                ('triggered_by',     models.CharField(blank=True, max_length=50)),
            ],
            options={'ordering': ['-started_at'], 'verbose_name': 'تشغيل محرك المشتريات'},
        ),

        # ── SupplierProfile ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='SupplierProfile',
            fields=[
                ('id',                   models.BigAutoField(auto_created=True, primary_key=True)),
                ('supplier_code',        models.CharField(max_length=10, unique=True)),
                ('supplier_name',        models.CharField(blank=True, max_length=255)),
                ('classif_code',         models.CharField(blank=True, max_length=10)),
                ('net_purchase_value',   models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_purchase_qty',     models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('net_return_value',     models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('return_pct',           models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('distinct_items',       models.PositiveIntegerField(default=0)),
                ('invoice_count',        models.PositiveIntegerField(default=0)),
                ('avg_margin_pct',       models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('branches_supplied',    models.PositiveSmallIntegerField(default=0)),
                ('purchase_frequency',   models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('value_30d',            models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('value_90d',            models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('value_365d',           models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('score_margin',         models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('score_availability',   models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('score_returns',        models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('score_price_stability', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('total_score',          models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('first_purchase_date',  models.DateField(blank=True, null=True)),
                ('last_purchase_date',   models.DateField(blank=True, null=True)),
                ('last_updated',         models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'ملف مورد', 'verbose_name_plural': 'ملفات الموردين',
                'ordering': ['-total_score', '-net_purchase_value'],
            },
        ),
        migrations.AddIndex(
            model_name='supplierprofile',
            index=models.Index(fields=['total_score'], name='proc_supp_score_idx'),
        ),
        migrations.AddIndex(
            model_name='supplierprofile',
            index=models.Index(fields=['avg_margin_pct'], name='proc_supp_margin_idx'),
        ),

        # ── SupplierItemMapping ───────────────────────────────────────────────
        migrations.CreateModel(
            name='SupplierItemMapping',
            fields=[
                ('id',                  models.BigAutoField(auto_created=True, primary_key=True)),
                ('supplier_code',       models.CharField(db_index=True, max_length=10)),
                ('supplier_name',       models.CharField(blank=True, max_length=255)),
                ('item_code',           models.CharField(db_index=True, max_length=6)),
                ('item',                models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='supplier_mappings', to='catalog.item')),
                ('item_name',           models.CharField(blank=True, max_length=255)),
                ('purchase_count',      models.PositiveIntegerField(default=0)),
                ('last_purchase_date',  models.DateField(blank=True, null=True)),
                ('first_purchase_date', models.DateField(blank=True, null=True)),
                ('net_qty_total',       models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ('net_value_total',     models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('min_price',           models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('max_price',           models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('avg_price',           models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('last_price',          models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('price_drift_pct',     models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('confidence_score',    models.DecimalField(decimal_places=2, default=50, max_digits=5)),
                ('is_primary',          models.BooleanField(default=False)),
                ('ocr_match_count',     models.PositiveIntegerField(default=0)),
                ('ocr_correction_count', models.PositiveIntegerField(default=0)),
                ('last_updated',        models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'خريطة مورد-صنف', 'verbose_name_plural': 'خرائط الموردين والأصناف',
                'ordering': ['-purchase_count'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='supplieritemmapping',
            unique_together={('supplier_code', 'item_code')},
        ),
        migrations.AddIndex(
            model_name='supplieritemmapping',
            index=models.Index(fields=['supplier_code', 'is_primary'], name='proc_sim_supp_primary_idx'),
        ),
        migrations.AddIndex(
            model_name='supplieritemmapping',
            index=models.Index(fields=['item_code', 'confidence_score'], name='proc_sim_item_conf_idx'),
        ),
        migrations.AddIndex(
            model_name='supplieritemmapping',
            index=models.Index(fields=['last_purchase_date'], name='proc_sim_last_purchase_idx'),
        ),

        # ── PurchaseLine ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='PurchaseLine',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True)),
                ('branch_code',  models.CharField(db_index=True, max_length=10)),
                ('supplier_code', models.CharField(db_index=True, max_length=10)),
                ('doc_number',   models.CharField(max_length=20)),
                ('doc_date',     models.DateField(db_index=True)),
                ('item_code',    models.CharField(db_index=True, max_length=6)),
                ('store_code',   models.CharField(blank=True, max_length=5)),
                ('doccode',      models.CharField(max_length=5)),
                ('is_return',    models.BooleanField(db_index=True, default=False)),
                ('raw_qty',      models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ('raw_value',    models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('unit_price',   models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('cost_price',   models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('net_qty',      models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ('net_value',    models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('public_price', models.DecimalField(decimal_places=3, default=0, max_digits=12)),
                ('margin_pct',   models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('buyer_code',   models.CharField(blank=True, max_length=20)),
                ('doc_value',    models.DecimalField(decimal_places=3, default=0, max_digits=16)),
                ('item',         models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='purchase_lines', to='catalog.item')),
                ('branch',       models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='purchase_lines', to='branches.branch')),
                ('synced_at',    models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'سطر شراء', 'verbose_name_plural': 'سطور الشراء',
                'ordering': ['-doc_date'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='purchaseline',
            unique_together={('branch_code', 'supplier_code', 'doc_number', 'doc_date', 'item_code', 'doccode')},
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['doc_date', 'supplier_code'], name='proc_pl_date_supp_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['doc_date', 'item_code'], name='proc_pl_date_item_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['supplier_code', 'item_code'], name='proc_pl_supp_item_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['buyer_code', 'doc_date'], name='proc_pl_buyer_date_idx'),
        ),
        migrations.AddIndex(
            model_name='purchaseline',
            index=models.Index(fields=['is_return', 'doc_date'], name='proc_pl_return_date_idx'),
        ),

        # ── ProcurementSnapshot ───────────────────────────────────────────────
        migrations.CreateModel(
            name='ProcurementSnapshot',
            fields=[
                ('id',                       models.BigAutoField(auto_created=True, primary_key=True)),
                ('snapshot_date',            models.DateField(db_index=True, unique=True)),
                ('engine_run',               models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to='procurement.procurementenginerun')),
                ('net_purchase_value_30d',   models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_purchase_value_90d',   models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_purchase_value_365d',  models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('net_purchase_qty_30d',     models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('net_purchase_qty_90d',     models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('net_purchase_qty_365d',    models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('distinct_items_30d',       models.PositiveIntegerField(default=0)),
                ('distinct_items_90d',       models.PositiveIntegerField(default=0)),
                ('distinct_items_365d',      models.PositiveIntegerField(default=0)),
                ('distinct_suppliers_30d',   models.PositiveSmallIntegerField(default=0)),
                ('distinct_suppliers_90d',   models.PositiveSmallIntegerField(default=0)),
                ('distinct_suppliers_365d',  models.PositiveSmallIntegerField(default=0)),
                ('invoice_count_30d',        models.PositiveIntegerField(default=0)),
                ('invoice_count_90d',        models.PositiveIntegerField(default=0)),
                ('invoice_count_365d',       models.PositiveIntegerField(default=0)),
                ('avg_margin_pct_30d',       models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('avg_margin_pct_90d',       models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('avg_margin_pct_365d',      models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('return_value_30d',         models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('return_pct_30d',           models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('top3_supplier_pct_365d',   models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('purchase_growth_pct_mom',  models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('purchase_growth_pct_yoy',  models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('created_at',               models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'لقطة مشتريات يومية', 'ordering': ['-snapshot_date']},
        ),

        # ── BuyerPerformance ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='BuyerPerformance',
            fields=[
                ('id',                  models.BigAutoField(auto_created=True, primary_key=True)),
                ('buyer_code',          models.CharField(db_index=True, max_length=20)),
                ('buyer_name',          models.CharField(blank=True, max_length=100)),
                ('period_start',        models.DateField()),
                ('period_end',          models.DateField()),
                ('net_purchase_value',  models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('invoice_count',       models.PositiveIntegerField(default=0)),
                ('distinct_items',      models.PositiveIntegerField(default=0)),
                ('distinct_suppliers',  models.PositiveSmallIntegerField(default=0)),
                ('avg_margin_pct',      models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('return_pct',          models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('estimated_savings',   models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('procurement_score',   models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('engine_run',          models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.CASCADE,
                    to='procurement.procurementenginerun')),
                ('created_at',          models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'أداء المشتري', 'ordering': ['-procurement_score']},
        ),
        migrations.AlterUniqueTogether(
            name='buyerperformance',
            unique_together={('buyer_code', 'period_start', 'period_end')},
        ),

        # ── ProcurementAlert ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProcurementAlert',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True)),
                ('alert_type',      models.CharField(
                    choices=[
                        ('price_spike', 'ارتفاع مفاجئ في السعر'),
                        ('price_drop', 'انخفاض مفاجئ في السعر'),
                        ('high_return_rate', 'معدل مرتجعات عالٍ'),
                        ('supplier_overpriced', 'مورد بسعر أعلى من السوق'),
                        ('low_margin', 'هامش ربح منخفض'),
                        ('preferred_supplier', 'مورد مفضل متاح'),
                        ('missed_discount', 'خصم فائت'),
                        ('price_drift', 'تذبذب في الأسعار'),
                        ('high_concentration', 'تركز عالٍ على مورد واحد'),
                        ('stockout_risk', 'خطر نفاد المخزون'),
                    ],
                    db_index=True, max_length=30)),
                ('severity',        models.CharField(
                    choices=[('info', 'معلومة'), ('warning', 'تحذير'), ('critical', 'حرجة')],
                    default='warning', max_length=10)),
                ('entity_type',     models.CharField(blank=True, max_length=20)),
                ('entity_code',     models.CharField(blank=True, db_index=True, max_length=20)),
                ('entity_name',     models.CharField(blank=True, max_length=255)),
                ('title',           models.CharField(max_length=255)),
                ('message',         models.TextField()),
                ('metric_value',    models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('threshold',       models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('detected_at',     models.DateTimeField(auto_now_add=True, db_index=True)),
                ('is_resolved',     models.BooleanField(db_index=True, default=False)),
                ('resolved_at',     models.DateTimeField(blank=True, null=True)),
                ('resolved_by',     models.CharField(blank=True, max_length=100)),
                ('resolution_notes', models.TextField(blank=True)),
                ('engine_run',      models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to='procurement.procurementenginerun')),
            ],
            options={
                'verbose_name': 'تنبيه مشتريات', 'verbose_name_plural': 'تنبيهات المشتريات',
                'ordering': ['-detected_at'],
            },
        ),
        migrations.AddIndex(
            model_name='procurementalert',
            index=models.Index(fields=['is_resolved', 'severity'], name='proc_alert_resolved_sev_idx'),
        ),
        migrations.AddIndex(
            model_name='procurementalert',
            index=models.Index(fields=['alert_type', 'detected_at'], name='proc_alert_type_date_idx'),
        ),
    ]
