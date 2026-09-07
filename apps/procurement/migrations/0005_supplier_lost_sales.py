"""
0005_supplier_lost_sales.py

Adds avoidable_loss_value and service_level_pct to SupplierProfile.
Populated by MODULE 13 (Lost Sales Engine) after each DemandCalculationRun.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('procurement', '0004_rename_proc_alert_resolved_sev_idx_procurement_is_reso_11d529_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierprofile',
            name='avoidable_loss_value',
            field=models.DecimalField(
                max_digits=18, decimal_places=2, default=0,
                verbose_name='الإيراد الضائع المنسوب للمورد (30 يوم) ج.م',
                help_text='Lost revenue where root_cause=supplier and this supplier is primary',
            ),
        ),
        migrations.AddField(
            model_name='supplierprofile',
            name='service_level_pct',
            field=models.DecimalField(
                max_digits=6, decimal_places=2, default=100,
                verbose_name='مستوى الخدمة % (30 يوم)',
                help_text='(expected - lost_qty) / expected × 100',
            ),
        ),
    ]
