from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [

        # ── AuditLog ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True)),
                ('user_name',   models.CharField(blank=True, max_length=150)),
                ('user_role',   models.CharField(blank=True, max_length=20)),
                ('ip_address',  models.GenericIPAddressField(blank=True, null=True)),
                ('action',      models.CharField(
                    choices=[
                        ('reservation_created','حجز — إنشاء'),
                        ('reservation_updated','حجز — تعديل'),
                        ('reservation_status_changed','حجز — تغيير حالة'),
                        ('reservation_cancelled','حجز — إلغاء'),
                        ('reservation_erp_validated','حجز — تحقق ERP'),
                        ('transfer_created','تحويل — إنشاء'),
                        ('transfer_submitted','تحويل — تقديم'),
                        ('transfer_approved','تحويل — اعتماد'),
                        ('transfer_rejected','تحويل — رفض'),
                        ('transfer_sent_to_erp','تحويل — إرسال للـ ERP'),
                        ('transfer_erp_validated','تحويل — تحقق ERP'),
                        ('customer_created','عميل — إنشاء'),
                        ('customer_updated','عميل — تعديل'),
                        ('customer_tag_added','عميل — إضافة تاج'),
                        ('customer_location_added','عميل — إضافة عنوان'),
                        ('demand_created','طلب — إنشاء'),
                        ('demand_status_changed','طلب — تغيير حالة'),
                        ('demand_lost','طلب — بيع ضائع'),
                        ('followup_created','متابعة — إنشاء'),
                        ('followup_done','متابعة — اكتمال'),
                        ('followup_auto_closed','متابعة — إغلاق تلقائي'),
                        ('user_login','مستخدم — دخول'),
                        ('user_login_failed','مستخدم — محاولة دخول فاشلة'),
                        ('sync_completed','مزامنة — اكتمال'),
                        ('sync_failed','مزامنة — فشل'),
                    ],
                    db_index=True, max_length=40,
                )),
                ('model_name',  models.CharField(blank=True, db_index=True, max_length=50)),
                ('object_id',   models.CharField(blank=True, db_index=True, max_length=50)),
                ('object_repr', models.CharField(blank=True, max_length=200)),
                ('old_data',    models.JSONField(blank=True, null=True)),
                ('new_data',    models.JSONField(blank=True, null=True)),
                ('changes',     models.JSONField(blank=True, null=True)),
                ('extra',       models.JSONField(blank=True, null=True)),
                ('note',        models.CharField(blank=True, max_length=255)),
                ('created_at',  models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_logs', to='users.staffprofile',
                )),
            ],
            options={'ordering': ['-created_at'], 'verbose_name': 'سجل مراجعة'},
        ),
        migrations.AddIndex(model_name='auditlog',
            index=models.Index(fields=['action', 'created_at'], name='audit_action_date_idx')),
        migrations.AddIndex(model_name='auditlog',
            index=models.Index(fields=['model_name', 'object_id'], name='audit_model_obj_idx')),
        migrations.AddIndex(model_name='auditlog',
            index=models.Index(fields=['user', 'created_at'], name='audit_user_date_idx')),

        # ── AbuseFlag ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='AbuseFlag',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True)),
                ('flag_type',   models.CharField(
                    choices=[
                        ('frequent_cancellations','⚠️ إلغاءات متكررة'),
                        ('frequent_status_changes','⚠️ تغييرات حالة متكررة'),
                        ('frequent_edits','⚠️ تعديلات متكررة'),
                        ('erp_mismatch','⚠️ عدم تطابق ERP'),
                        ('after_hours_activity','⚠️ نشاط خارج أوقات العمل'),
                        ('bulk_deletions','⚠️ حذف جماعي'),
                        ('override_pattern','⚠️ تجاوزات متكررة'),
                    ],
                    db_index=True, max_length=30,
                )),
                ('severity',    models.CharField(
                    choices=[('info','معلومة'),('warning','تحذير'),('critical','حرج')],
                    db_index=True, default='warning', max_length=10,
                )),
                ('status',      models.CharField(
                    choices=[('open','مفتوح'),('reviewed','تمت المراجعة'),('dismissed','تم التجاهل'),('escalated','تم التصعيد')],
                    db_index=True, default='open', max_length=12,
                )),
                ('description', models.TextField()),
                ('evidence',    models.JSONField(blank=True, null=True)),
                ('count',       models.PositiveIntegerField(default=0)),
                ('window_hours', models.PositiveIntegerField(default=24)),
                ('review_note', models.TextField(blank=True)),
                ('detected_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_abuse_flags', to='users.staffprofile',
                )),
                ('staff', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='abuse_flags', to='users.staffprofile',
                )),
            ],
            options={'ordering': ['-detected_at'], 'verbose_name': 'إشارة مشكلة'},
        ),
        migrations.AddIndex(model_name='abuseflag',
            index=models.Index(fields=['staff', 'flag_type', 'detected_at'], name='abuse_staff_type_idx')),
        migrations.AddIndex(model_name='abuseflag',
            index=models.Index(fields=['status', 'severity'], name='abuse_status_sev_idx')),
    ]
