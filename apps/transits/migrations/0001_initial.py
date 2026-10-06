import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('transfers', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='InTransitTransfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('erp_doc_number', models.CharField(db_index=True, max_length=50, unique=True, verbose_name='رقم المستند (ERP)')),
                ('erp_doc_code', models.CharField(default='125', max_length=10, verbose_name='كود نوع المستند')),
                ('erp_supplying_branch_code', models.CharField(db_index=True, max_length=20, verbose_name='كود فرع المصدر (ERP)')),
                ('erp_receiving_branch_code', models.CharField(blank=True, max_length=20, verbose_name='كود فرع المستلم (ERP)')),
                ('erp_user_code', models.CharField(blank=True, max_length=20, verbose_name='كود المستخدم (ERP)')),
                ('erp_store_code', models.CharField(blank=True, max_length=20, verbose_name='كود المخزن (ERP)')),
                ('issue_date', models.DateField(verbose_name='تاريخ الإصدار')),
                ('erp_received_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الاستلام (ERP)')),
                ('cancellation_expires_at', models.DateField(blank=True, null=True, verbose_name='انتهاء مهلة الإلغاء')),
                ('doc_value', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='قيمة المستند (ERP)')),
                ('item_count', models.PositiveIntegerField(default=0, verbose_name='عدد الأصناف')),
                ('total_quantity', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True, verbose_name='إجمالي الكميات')),
                ('items_snapshot', models.JSONField(blank=True, default=list, verbose_name='بيانات الأصناف')),
                ('transit_status', models.CharField(choices=[('in_transit', 'قيد النقل'), ('received', 'مستلم'), ('cancelled', 'ملغي في ERP'), ('expired_pending', 'انتهت مهلة الإلغاء — معلق'), ('force_closed', 'مغلق قسراً')], db_index=True, default='in_transit', max_length=20, verbose_name='حالة النقل')),
                ('priority', models.CharField(choices=[('green', '🟢 طازج (0-2 يوم)'), ('yellow', '🟡 تحت المراقبة (3-4 أيام)'), ('orange', '🟠 يحتاج متابعة (5-6 أيام)'), ('red', '🔴 طارئ (7-9 أيام)'), ('critical', '🚨 حرج (10+ أيام)')], db_index=True, default='green', max_length=10, verbose_name='مستوى الأولوية')),
                ('days_in_transit', models.PositiveIntegerField(default=0, verbose_name='أيام النقل')),
                ('cancellation_available', models.BooleanField(default=True, verbose_name='الإلغاء ممكن')),
                ('alert_notification_count', models.PositiveIntegerField(default=0, verbose_name='عدد التنبيهات المُرسَلة')),
                ('last_alert_sent_at', models.DateTimeField(blank=True, null=True, verbose_name='آخر تنبيه مُرسَل')),
                ('last_alert_level', models.CharField(blank=True, max_length=10, verbose_name='مستوى آخر تنبيه')),
                ('internal_notes', models.TextField(blank=True, verbose_name='ملاحظات داخلية')),
                ('manually_received_at', models.DateTimeField(blank=True, null=True, verbose_name='تم تسجيل الاستلام يدوياً في')),
                ('force_close_reason', models.TextField(blank=True, verbose_name='سبب الإغلاق القسري')),
                ('first_seen_at', models.DateTimeField(auto_now_add=True, verbose_name='أول ظهور في النظام')),
                ('last_synced_at', models.DateTimeField(blank=True, null=True, verbose_name='آخر مزامنة مع ERP')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('supplying_branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplying_transits', to='branches.branch', verbose_name='فرع المصدر')),
                ('receiving_branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='receiving_transits', to='branches.branch', verbose_name='فرع المستلم')),
                ('linked_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='in_transit_records', to='transfers.transferrequest', verbose_name='طلب التحويل المرتبط')),
                ('manually_received_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='received_transits', to='users.staffprofile', verbose_name='سجّل الاستلام')),
                ('force_closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='force_closed_transits', to='users.staffprofile', verbose_name='أغلق قسراً بواسطة')),
            ],
            options={
                'verbose_name': 'تحويل قيد النقل',
                'verbose_name_plural': 'التحويلات قيد النقل',
                'ordering': ['-issue_date', '-erp_doc_number'],
            },
        ),
        migrations.CreateModel(
            name='InTransitNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note_type', models.CharField(choices=[('note', '📝 ملاحظة'), ('system', '⚙️ نظام'), ('alert', '🔔 تنبيه')], default='note', max_length=10, verbose_name='نوع الملاحظة')),
                ('body', models.TextField(verbose_name='نص الملاحظة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('transfer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='transits.intransittransfer', verbose_name='التحويل')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transit_notes', to='users.staffprofile', verbose_name='بواسطة')),
            ],
            options={
                'verbose_name': 'ملاحظة تحويل',
                'verbose_name_plural': 'ملاحظات التحويلات',
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='InTransitAuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('viewed', '👁️ عُرض'), ('note_added', '📝 أُضيفت ملاحظة'), ('alert_sent', '🔔 أُرسل تنبيه'), ('received', '✅ سُجِّل الاستلام'), ('cancel_requested', '↩️ طُلب الإلغاء'), ('force_closed', '🔒 أُغلق قسراً'), ('synced', '🔄 مزامنة ERP'), ('printed', '🖨️ طُبع'), ('exported', '📤 صُدِّر'), ('linked', '🔗 رُبط بطلب')], db_index=True, max_length=30, verbose_name='الإجراء')),
                ('detail', models.TextField(blank=True, verbose_name='تفاصيل')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('transfer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audit_events', to='transits.intransittransfer', verbose_name='التحويل')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transit_audit_events', to='users.staffprofile', verbose_name='المُنفِّذ')),
            ],
            options={
                'verbose_name': 'حدث مراجعة',
                'verbose_name_plural': 'سجل المراجعة',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='intransittransfer',
            index=models.Index(fields=['transit_status', 'priority'], name='transits_status_priority_idx'),
        ),
        migrations.AddIndex(
            model_name='intransittransfer',
            index=models.Index(fields=['supplying_branch', 'transit_status'], name='transits_supply_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='intransittransfer',
            index=models.Index(fields=['receiving_branch', 'transit_status'], name='transits_recv_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='intransittransfer',
            index=models.Index(fields=['issue_date'], name='transits_issue_date_idx'),
        ),
    ]
