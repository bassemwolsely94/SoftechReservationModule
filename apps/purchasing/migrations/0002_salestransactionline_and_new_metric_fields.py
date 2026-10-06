"""
Migration: purchasing 0002

1. Add SalesTransactionLine — PG cache of raw SOFTECH stktrans rows (rolling 365d).
2. Add new columns to ItemDemandMetrics:
     trns_30d, trns_90d, trns_365d  — transaction row counts per window
     monthly_avg_trns               — simple average of TRNs rates (Excel: MonthlyAvg3RatesofTRNsCount)
     pct_stock_of_total             — branch stock / total network stock (Excel: %StockOfTotal)
3. Add new columns to DemandCalculationRun:
     sync_lookback_days, rows_synced, rows_purged
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0001_initial'),
        ('catalog',    '0006_rename_item_price_fields'),
        ('branches',   '0001_initial'),
    ]

    operations = [

        # ── SalesTransactionLine ──────────────────────────────────────────────
        migrations.CreateModel(
            name='SalesTransactionLine',
            fields=[
                ('id',                  models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_branchcode',  models.CharField(db_index=True, max_length=20)),
                ('softech_itemcode',    models.CharField(db_index=True, max_length=50)),
                ('doccode',             models.CharField(help_text="'115' = sale | '30' = return", max_length=10)),
                ('docnumber',           models.CharField(max_length=50)),
                ('doc_date',            models.DateField(db_index=True)),
                ('transqty',            models.DecimalField(decimal_places=3, help_text='Raw qty from SOFTECH (always ≥ 0)', max_digits=14)),
                ('net_qty',             models.DecimalField(decimal_places=3, help_text='+transqty for sales, -transqty for returns', max_digits=14)),
                ('synced_at',           models.DateTimeField(auto_now=True)),
                ('item',   models.ForeignKey(blank=True, db_index=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sales_lines',   to='catalog.item')),
                ('branch', models.ForeignKey(blank=True, db_index=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sales_lines', to='branches.branch')),
            ],
            options={
                'verbose_name':        'حركة مبيعات',
                'verbose_name_plural': 'حركات المبيعات',
            },
        ),
        migrations.AddConstraint(
            model_name='salestransactionline',
            constraint=models.UniqueConstraint(
                fields=['softech_branchcode', 'softech_itemcode', 'doccode', 'docnumber', 'doc_date'],
                name='unique_stktrans_line',
            ),
        ),
        migrations.AddIndex(
            model_name='salestransactionline',
            index=models.Index(fields=['doc_date'], name='stl_doc_date'),
        ),
        migrations.AddIndex(
            model_name='salestransactionline',
            index=models.Index(fields=['item', 'branch', 'doc_date'], name='stl_item_branch_date'),
        ),
        migrations.AddIndex(
            model_name='salestransactionline',
            index=models.Index(
                fields=['softech_branchcode', 'softech_itemcode', 'doc_date'],
                name='stl_soft_key_date',
            ),
        ),

        # ── DemandCalculationRun — new sync tracking fields ───────────────────
        migrations.AddField(
            model_name='demandcalculationrun',
            name='sync_lookback_days',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Days fetched from SOFTECH (0 = calc-only)',
            ),
        ),
        migrations.AddField(
            model_name='demandcalculationrun',
            name='rows_synced',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Rows upserted into SalesTransactionLine',
            ),
        ),
        migrations.AddField(
            model_name='demandcalculationrun',
            name='rows_purged',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Old rows deleted (>365 days)',
            ),
        ),

        # ── ItemDemandMetrics — new fields ────────────────────────────────────
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='trns_30d',
            field=models.PositiveIntegerField(default=0, verbose_name='عدد حركات البيع (30 يوم)'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='trns_90d',
            field=models.PositiveIntegerField(default=0, verbose_name='عدد حركات البيع (90 يوم)'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='trns_365d',
            field=models.PositiveIntegerField(default=0, verbose_name='عدد حركات البيع (365 يوم)'),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='monthly_avg_trns',
            field=models.DecimalField(
                decimal_places=4, default=0, max_digits=10,
                verbose_name='معدل عدد حركات البيع الشهري',
            ),
        ),
        migrations.AddField(
            model_name='itemdemandmetrics',
            name='pct_stock_of_total',
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=8, null=True,
                verbose_name='نسبة الرصيد لإجمالي المخزون',
                help_text='branch_stock / total_network_stock for this item',
            ),
        ),
    ]
