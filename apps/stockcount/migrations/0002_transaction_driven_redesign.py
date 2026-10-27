"""
Migration 0002 — Transaction-driven stock count redesign

Transforms the old simple line-based model into the new architecture:
  • Drops StockCountLine
  • Replaces StockCountSession (adds new fields, drops old ERP-doc fields)
  • Creates StockCountSnapshot (immutable per-item records)
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stockcount', '0001_initial'),
        ('users',      '0001_initial'),
    ]

    operations = [

        # ── 1. Drop the old StockCountLine model ──────────────────────────────
        migrations.DeleteModel(name='StockCountLine'),

        # ── 2. Transform StockCountSession ───────────────────────────────────

        # Remove old fields
        migrations.RemoveField(model_name='stockcountsession', name='branch'),
        migrations.RemoveField(model_name='stockcountsession', name='erp_doc_code'),
        migrations.RemoveField(model_name='stockcountsession', name='erp_doc_number'),
        migrations.RemoveField(model_name='stockcountsession', name='count_date'),
        migrations.RemoveField(model_name='stockcountsession', name='completed_at'),

        # Alter status choices & default
        migrations.AlterField(
            model_name='stockcountsession',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft',          'مسودة'),
                    ('snapshot_taken', 'تم أخذ اللقطة'),
                    ('exported',       'تم التصدير'),
                    ('uploaded',       'تم رفع النتائج'),
                    ('variance_ready', 'الفروق جاهزة'),
                    ('closed',         'مغلق'),
                ],
                default='draft', max_length=20, verbose_name='الحالة',
            ),
        ),

        # Alter created_by related_name to avoid conflict
        migrations.AlterField(
            model_name='stockcountsession',
            name='created_by',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sc_sessions_created',
                to='users.staffprofile',
                verbose_name='أُنشئت بواسطة',
            ),
        ),

        # Add new fields
        migrations.AddField(
            model_name='stockcountsession', name='name',
            field=models.CharField(default='جلسة جرد', max_length=200, verbose_name='اسم جلسة الجرد'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='stockcountsession', name='mode',
            field=models.CharField(
                choices=[('transaction','مبني على الحركات'),('full','جرد شامل'),('filtered','جرد مفلتر')],
                default='transaction', max_length=20, verbose_name='النوع',
            ),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='branch_code',
            field=models.CharField(default='', max_length=20, verbose_name='كود الفرع'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='stockcountsession', name='date_from',
            field=models.DateField(blank=True, null=True, verbose_name='من تاريخ'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='date_to',
            field=models.DateField(blank=True, null=True, verbose_name='إلى تاريخ'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='doccodes',
            field=models.JSONField(default=list, verbose_name='أكواد المستند'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='user_code_filter',
            field=models.CharField(blank=True, max_length=50, verbose_name='فلتر كود المستخدم'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='category_filter',
            field=models.CharField(blank=True, max_length=50, verbose_name='فلتر التصنيف'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='item_codes_filter',
            field=models.JSONField(default=list, verbose_name='قائمة أصناف محددة'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='item_count',
            field=models.IntegerField(default=0, verbose_name='عدد الأصناف'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='surplus_count',
            field=models.IntegerField(default=0, verbose_name='عدد الزيادات'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='deficit_count',
            field=models.IntegerField(default=0, verbose_name='عدد النواقص'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='ok_count',
            field=models.IntegerField(default=0, verbose_name='عدد المطابقات'),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='snapshot_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sc_sessions_snapshot',
                to='users.staffprofile', verbose_name='تم اللقطة بواسطة',
            ),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='uploaded_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sc_sessions_uploaded',
                to='users.staffprofile', verbose_name='رُفع بواسطة',
            ),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='snapshot_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='exported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='uploaded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='variance_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockcountsession', name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),

        # Indexes on StockCountSession
        migrations.AddIndex(
            model_name='stockcountsession',
            index=models.Index(
                fields=['branch_code', 'status'],
                name='sc_session_branch_status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stockcountsession',
            index=models.Index(
                fields=['created_at'],
                name='sc_session_created_idx',
            ),
        ),

        # ── 3. Create StockCountSnapshot ──────────────────────────────────────
        migrations.CreateModel(
            name='StockCountSnapshot',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                )),
                ('item_code',     models.CharField(db_index=True, max_length=20, verbose_name='كود الصنف')),
                ('item_name',     models.CharField(max_length=255, verbose_name='اسم الصنف')),
                ('item_medicine', models.CharField(blank=True, max_length=10, verbose_name='تصنيف الدواء (itemmedicine)')),
                ('category_name', models.CharField(blank=True, max_length=255, verbose_name='التصنيف')),
                ('branch_code',   models.CharField(max_length=20, verbose_name='كود الفرع')),
                ('expected_qty',  models.DecimalField(decimal_places=3, max_digits=12, verbose_name='الكمية المتوقعة')),
                ('snapshot_time', models.DateTimeField(auto_now_add=True, verbose_name='وقت أخذ اللقطة')),
                ('counted_qty',   models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name='الكمية المعدودة')),
                ('difference',    models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name='الفارق')),
                ('variance_type', models.CharField(
                    blank=True, default='', max_length=10,
                    choices=[('','لم يُجرَد بعد'),('ok','مطابق'),('surplus','زيادة'),('deficit','نقص')],
                    verbose_name='نوع الانحراف',
                )),
                ('session', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='snapshots',
                    to='stockcount.stockcountsession',
                    verbose_name='الجلسة',
                )),
            ],
            options={
                'verbose_name':        'لقطة جرد',
                'verbose_name_plural': 'لقطات الجرد',
                'ordering':            ['item_name'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='stockcountsnapshot',
            unique_together={('session', 'item_code')},
        ),
        migrations.AddIndex(
            model_name='stockcountsnapshot',
            index=models.Index(
                fields=['session', 'variance_type'],
                name='sc_snap_variance_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stockcountsnapshot',
            index=models.Index(
                fields=['session', 'item_code'],
                name='sc_snap_item_idx',
            ),
        ),
    ]
