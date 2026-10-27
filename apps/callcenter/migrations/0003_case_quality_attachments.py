# Generated migration: Phase 1 Call Center — Case management, quality scoring, attachments
# Adds: CustomerCase, CaseEvent, CallLogAttachment, CallQualityScore
# Extends CallLog with: case FK, recording_url, voice_transcript, prescription_image,
#                       AI fields, quality_score

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('callcenter', '0002_fix_applied_location_ref'),
        # Demand & delivery apps (for CustomerCase FK fields)
        ('demand', '0002_rename_demand_status_branch_idx_demand_dema_status_7047e1_idx_and_more'),
        ('delivery', '0001_initial'),
        # Already required by 0001 but re-listed for clarity
        ('branches', '0001_initial'),
        ('customers', '0014_purchasehistory_trans_time'),
        ('reservations', '0007_ensure_activity_tables'),
        ('users', '0011_staffprofile_notification_prefs'),
    ]

    operations = [

        # ── 1. Create CustomerCase ─────────────────────────────────────────────
        migrations.CreateModel(
            name='CustomerCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('case_number', models.CharField(blank=True, max_length=20, unique=True, verbose_name='رقم الحالة')),
                ('category', models.CharField(
                    choices=[
                        ('complaint',  '⚠️ شكوى'),
                        ('inquiry',    '❓ استفسار'),
                        ('request',    '📋 طلب'),
                        ('lost_sale',  '❌ بيعة مفقودة'),
                        ('delivery',   '🚚 توصيل'),
                        ('support',    '🛠️ دعم'),
                        ('refund',     '↩️ إرجاع/استبدال'),
                        ('other',      '💬 أخرى'),
                    ],
                    db_index=True, max_length=15, verbose_name='تصنيف الحالة',
                )),
                ('priority', models.CharField(
                    choices=[
                        ('low',    'منخفضة'),
                        ('normal', 'عادية'),
                        ('high',   'مرتفعة'),
                        ('urgent', 'عاجلة 🔴'),
                    ],
                    default='normal', max_length=10, verbose_name='الأولوية',
                )),
                ('status', models.CharField(
                    choices=[
                        ('open',       '🆕 مفتوحة'),
                        ('working',    '⚙️ قيد المعالجة'),
                        ('waiting',    '⏳ انتظار العميل'),
                        ('escalated',  '🔴 مُصعَّدة'),
                        ('resolved',   '✅ محلولة'),
                        ('closed',     '🔒 مغلقة'),
                    ],
                    db_index=True, default='open', max_length=12, verbose_name='الحالة',
                )),
                ('title',       models.CharField(max_length=255, verbose_name='عنوان الحالة')),
                ('description', models.TextField(blank=True, verbose_name='الوصف التفصيلي')),
                ('root_cause',  models.TextField(blank=True, verbose_name='السبب الجذري')),
                ('resolution',  models.TextField(blank=True, verbose_name='طريقة الحل')),
                ('sla_due',     models.DateTimeField(blank=True, null=True, verbose_name='موعد SLA')),
                ('resolved_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الحل')),
                ('closed_at',   models.DateTimeField(blank=True, null=True, verbose_name='وقت الإغلاق')),
                ('csat_score',  models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='تقييم العميل (1-5)')),
                ('csat_note',   models.TextField(blank=True, verbose_name='تعليق التقييم')),
                ('escalated_at',       models.DateTimeField(blank=True, null=True)),
                ('escalation_reason',  models.TextField(blank=True)),
                ('created_at',  models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at',  models.DateTimeField(auto_now=True)),
                # ── FK fields ──────────────────────────────────────────────────
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cases', to='customers.customer', verbose_name='العميل',
                )),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='customer_cases', to='branches.branch', verbose_name='الفرع',
                )),
                ('demand', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cases', to='demand.demandrecord', verbose_name='الطلب المرتبط',
                )),
                ('reservation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cases', to='reservations.reservation', verbose_name='الحجز المرتبط',
                )),
                ('delivery', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cases', to='delivery.deliveryorder', verbose_name='التوصيل المرتبط',
                )),
                ('opened_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='opened_cases', to='users.staffprofile', verbose_name='فُتح بواسطة',
                )),
                ('assigned_to', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_cases', to='users.staffprofile', verbose_name='مُعيَّن لـ',
                )),
                ('escalated_to', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='escalated_cases', to='users.staffprofile', verbose_name='صُعِّدت لـ',
                )),
            ],
            options={
                'verbose_name': 'حالة عميل',
                'verbose_name_plural': 'حالات العملاء',
                'ordering': ['-created_at'],
            },
        ),

        # ── 2. Add indexes for CustomerCase ────────────────────────────────────
        migrations.AddIndex(
            model_name='customercase',
            index=models.Index(fields=['customer', 'status'], name='callcenter__cust_status_idx'),
        ),
        migrations.AddIndex(
            model_name='customercase',
            index=models.Index(fields=['status', 'branch'], name='callcenter__status_branch_idx'),
        ),
        migrations.AddIndex(
            model_name='customercase',
            index=models.Index(fields=['assigned_to', 'status'], name='callcenter__assigned_status_idx'),
        ),
        migrations.AddIndex(
            model_name='customercase',
            index=models.Index(fields=['category', 'status'], name='callcenter__cat_status_idx'),
        ),

        # ── 3. Extend CallLog with new fields ──────────────────────────────────
        migrations.AddField(
            model_name='calllog',
            name='case',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='calls',
                to='callcenter.customercase',
                verbose_name='الحالة المرتبطة',
            ),
        ),
        migrations.AddField(
            model_name='calllog',
            name='recording_url',
            field=models.URLField(blank=True, verbose_name='رابط التسجيل'),
        ),
        migrations.AddField(
            model_name='calllog',
            name='voice_transcript',
            field=models.TextField(blank=True, verbose_name='النص الصوتي',
                                   help_text='نص المكالمة بعد التعرف على الصوت'),
        ),
        migrations.AddField(
            model_name='calllog',
            name='prescription_image',
            field=models.ImageField(
                blank=True, null=True,
                upload_to='callcenter/prescriptions/%Y/%m/',
                verbose_name='صورة الروشتة',
            ),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_summary',
            field=models.TextField(blank=True, verbose_name='ملخص الذكاء الاصطناعي'),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_intent',
            field=models.CharField(
                blank=True, max_length=50, verbose_name='نية المكالمة (AI)',
                help_text='purchase / complaint / inquiry / refill / delivery …',
            ),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_sentiment',
            field=models.CharField(
                blank=True, max_length=15,
                choices=[
                    ('positive', 'إيجابي 😊'),
                    ('neutral',  'محايد 😐'),
                    ('negative', 'سلبي 😟'),
                ],
                verbose_name='مشاعر العميل (AI)',
            ),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_urgency',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                verbose_name='درجة الإلحاح (AI)',
                help_text='1 = منخفض … 5 = عاجل جداً',
            ),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_next_action',
            field=models.CharField(blank=True, max_length=255, verbose_name='الإجراء المقترح (AI)'),
        ),
        migrations.AddField(
            model_name='calllog',
            name='ai_processed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت معالجة AI'),
        ),
        migrations.AddField(
            model_name='calllog',
            name='quality_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='نقاط الجودة (1-100)'),
        ),

        # ── 4. Create CaseEvent ────────────────────────────────────────────────
        migrations.CreateModel(
            name='CaseEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(
                    choices=[
                        ('note',   '📝 ملاحظة'),
                        ('call',   '📞 مكالمة'),
                        ('status', '🔄 تغيير حالة'),
                        ('system', '⚙️ نظام'),
                    ],
                    default='note', max_length=10,
                )),
                ('message',    models.TextField(verbose_name='الرسالة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('case', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='events', to='callcenter.customercase', verbose_name='الحالة',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile', verbose_name='بواسطة',
                )),
            ],
            options={
                'verbose_name': 'حدث حالة',
                'verbose_name_plural': 'أحداث الحالة',
                'ordering': ['created_at'],
            },
        ),

        # ── 5. Create CallLogAttachment ────────────────────────────────────────
        migrations.CreateModel(
            name='CallLogAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='callcenter/attachments/%Y/%m/', verbose_name='الملف')),
                ('file_type', models.CharField(
                    choices=[
                        ('prescription', '💊 روشتة'),
                        ('image',        '🖼️ صورة'),
                        ('voice',        '🎙️ مقطع صوتي'),
                        ('document',     '📄 مستند'),
                    ],
                    default='image', max_length=15, verbose_name='نوع الملف',
                )),
                ('description', models.CharField(blank=True, max_length=255, verbose_name='الوصف')),
                ('file_size',   models.PositiveIntegerField(default=0, verbose_name='الحجم (بايت)')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('call_log', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attachments', to='callcenter.calllog', verbose_name='سجل المكالمة',
                )),
                ('uploaded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile', verbose_name='رُفع بواسطة',
                )),
            ],
            options={
                'verbose_name': 'مرفق مكالمة',
                'verbose_name_plural': 'مرفقات المكالمات',
                'ordering': ['-uploaded_at'],
            },
        ),

        # ── 6. Create CallQualityScore ─────────────────────────────────────────
        migrations.CreateModel(
            name='CallQualityScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(
                    choices=[
                        ('supervisor', '👤 مشرف'),
                        ('ai',         '🤖 ذكاء اصطناعي'),
                    ],
                    default='supervisor', max_length=12, verbose_name='مصدر التقييم',
                )),
                ('greeting',      models.PositiveSmallIntegerField(default=0, verbose_name='الترحيب والتعريف (0-20)')),
                ('resolution',    models.PositiveSmallIntegerField(default=0, verbose_name='حل المشكلة (0-30)')),
                ('communication', models.PositiveSmallIntegerField(default=0, verbose_name='وضوح التواصل (0-25)')),
                ('accuracy',      models.PositiveSmallIntegerField(default=0, verbose_name='دقة المعلومات (0-25)')),
                ('total_score',   models.PositiveSmallIntegerField(default=0, verbose_name='الدرجة الإجمالية (0-100)')),
                ('notes',         models.TextField(blank=True, verbose_name='ملاحظات التقييم')),
                ('scored_at',     models.DateTimeField(auto_now_add=True)),
                ('call_log', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='quality', to='callcenter.calllog', verbose_name='سجل المكالمة',
                )),
                ('scored_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='quality_scores_given',
                    to='users.staffprofile', verbose_name='المقيِّم',
                )),
            ],
            options={
                'verbose_name': 'تقييم جودة مكالمة',
                'verbose_name_plural': 'تقييمات جودة المكالمات',
                'ordering': ['-scored_at'],
            },
        ),
    ]
